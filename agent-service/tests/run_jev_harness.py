"""Live opt-in Harness comparison. Default only inventories synthetic fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.case_library.schema import load
from tests.judgment_comparison.cases import FIXTURES
from tests.judgment_comparison.harness_integration import node_cases, run_node, summary

BINDING_ANSWER = ("不能靠重排找回未召回的资料。检索先快速召回并缩小候选范围；"
    "重排把问题与每个已召回片段联合打分，筛出更相关的内容。"
    "精排计算代价高，不适合全库逐一比较，分两步兼顾效率和匹配精度。"
    "如果检索根本没召回正确片段，重排只能看已有候选，无法补回它。")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--jev-key-stdin", action="store_true")
    p.add_argument("--output", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--stage", choices=("all", "dialogue", "nodes"), default="all")
    p.add_argument("--case", action="append", default=[])
    p.add_argument("--verify-question-binding", action="store_true",
                   help="Add one fixed answer after an existing RAG teaching scenario; verify pre-answer and next-question binding.")
    args = p.parse_args(argv)
    if args.report:
        if args.live or args.output or args.jev_key_stdin or args.case or args.stage != "all" or args.verify_question_binding:
            p.error("--report cannot be combined with execution")
        result = summary(args.report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["result"] == "PASS" else 1
    _, suite = load()
    dialogues = suite.scenarios if args.stage != "nodes" else []
    nodes = node_cases() if args.stage != "dialogue" else []
    known = {s.id for s in dialogues} | {s["id"] for s in nodes}
    if set(args.case) - known or len(args.case) != len(set(args.case)):
        p.error("unknown or duplicate case")
    if args.case:
        dialogues = [s for s in dialogues if s.id in args.case]
        nodes = [s for s in nodes if s["id"] in args.case]
    if args.verify_question_binding and (len(dialogues) != 1 or nodes or dialogues[0].id not in {"A007-resume-unique", "A013-current-plan-next"}):
        p.error("question binding flow requires one existing RAG teaching --case")
    items = [("dialogue", s.id, s) for s in dialogues] + [(s["kind"], s["id"], s) for s in nodes]
    planned = [identity + suffix + "/" + variant for i, (_, identity, _) in enumerate(items)
               for variant in (("baseline", "jev") if i % 2 == 0 else ("jev", "baseline"))
               for suffix in (("", "/generated-answer") if args.verify_question_binding else ("",))]
    if not args.live:
        if args.output or args.jev_key_stdin:
            p.error("output and credentials require --live")
        print(json.dumps(dict(result="VALID", dialogues=len(dialogues), node_cases=len(nodes),
                              paired_runs=len(planned), note="Offline inventory only; no providers or stores imported.")))
        return 0
    if not args.output or args.output.exists():
        p.error("--live requires a new output file")
    key = sys.stdin.readline().strip() if args.jev_key_stdin else os.getenv("TYPESAFE_API_KEY", "").strip()
    if not key:
        p.error("Jev credential unavailable")
    with tempfile.TemporaryDirectory(prefix="review-jev-harness-") as folder:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(folder) / "unused.sqlite3")
        from agent_service import conversation, config
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.jev_client import JevClient
        from agent_service.judgments import JudgmentEngine
        from tests.case_library.recording import RunReport
        from tests.case_library.replay import run_one
        from tests.judgment_comparison.resource_replay import observed_boundaries
        from agent_service.judgment_grading import standard_for
        from agent_service.schemas import SessionMessageRequest
        if config.PROVIDER != "deepseek":
            p.error("existing provider must be DeepSeek; configuration not changed")
        gold = json.loads((FIXTURES / "dialogue.json").read_text())["expected"]

        class Report(RunReport):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.lock = threading.Lock()

            def write(self, row):
                with self.lock:
                    super().write(row)

            def __enter__(self):
                super().__enter__()
                observed = conversation.parse_model
                def capture(system, prompt, schema, **kwargs):
                    # Capture before I/O; no late-response case identity lookup.
                    self.write(dict(type="prompt", system_sha256=hashlib.sha256(system.encode()).hexdigest(),
                                    system=system, json_schema=schema.model_json_schema()))
                    return observed(system, prompt, schema, **kwargs)
                self.stack.enter_context(patch("agent_service.conversation.parse_model", side_effect=capture))
                return self

            def add(self, identity, record, checks):
                record["scope_audit"] = observed_boundaries(record, gold[identity])
                checks = dict(checks, completed=record["run"]["status"] == "completed" and bool(record["replies"]),
                    real_intent=any(c["schema"] in {"IntentDecision", "IntentRemainder"} and "output" in c for c in record["model_calls"]),
                    no_blocked_tool_attempt=not record["tool_attempts"],
                    scope=record["scope_audit"]["passed"])
                if args.verify_question_binding and self.variant == "jev":
                    task = record["after"]["tasks"].get(record["after"]["active_task_id"])
                    checks["standard_bound_before_answer"] = bool(task and standard_for(task, task["context"].get("check_question")))
                self.finish(identity, "dialogue", record, checks)

            def finish(self, identity, kind, record, checks):
                row = dict(type="result", id=identity + "/" + self.variant, variant=self.variant, kind=kind,
                           **record, elapsed_ms=round((time.perf_counter() - self.started) * 1000, 3),
                           checks=checks, automatic_result="PASS" if all(checks.values()) else "FAIL",
                           human_review="pending")
                self.records.append(row)
                self.write(row)

        fixture = dict(dialogues=[s.model_dump() for s in dialogues], nodes=nodes,
            binding_answer=BINDING_ANSWER if args.verify_question_binding else None,
            prices=json.loads((FIXTURES / "prices.json").read_text()),
            limitations=["合成材料与临时数据库；日常 App 未启用。",
                         "对话分支的真实网页与知识写入被阻断；节点探针冻结非焦点准备和网页数据，不代表真实联网成功。",
                         "节点与整轮耗时分开统计；入口保留 LLM 检查，不预设提速。",
                         "已知回归样例，不是独立校准或生产置信度阈值验证。"])
        # One client per experimental Harness instance: auth disablement is local.
        with Report(args.output, layer="live_fixed_context", planned=planned, fixture=fixture) as report:
            for i, (kind, identity, case) in enumerate(items):
                for variant in (("baseline", "jev") if i % 2 == 0 else ("jev", "baseline")):
                    report.variant, report.started = variant, time.perf_counter()
                    client = JevClient(key) if variant == "jev" else None
                    engine = JudgmentEngine(client, observer=lambda event, name=identity + "/" + variant:
                        report.write(dict(event, type="judgment_" + event.get("type", "response"), trial=name))) if client else None
                    harness = ConversationHarness(ConversationStore(HarnessStore(
                        str(Path(folder) / f"{i}-{variant}.sqlite3"))), judgments=engine)
                    start_calls, start_tools = len(report.calls), len(report.tool_attempts)
                    current_identity, current_kind = identity, kind
                    try:
                        if kind == "dialogue":
                            run_one(harness, report, case)
                            if args.verify_question_binding:
                                current_identity, current_kind = identity + "/generated-answer", "binding_flow"
                                report.started = time.perf_counter()
                                sid = report.records[-1]["after"]["session_id"]
                                record = report.turn(harness, sid, SessionMessageRequest(
                                    client_message_id=str(uuid.uuid4()), content=BINDING_ANSWER))
                                tid = record["before"]["active_task_id"]
                                task = record["after"]["tasks"][tid]
                                checks = dict(completed=record["run"]["status"] == "completed" and bool(record["replies"]),
                                              evaluated=bool(task["context"].get("practice")),
                                              no_blocked_tool_attempt=not record["tool_attempts"])
                                if variant == "jev":
                                    before = record["before"]["tasks"][tid]["context"].get("check_standard")
                                    point = record["run"].get("point_evaluation")
                                    checks.update(same_frozen_standard=bool(before and point and point["standard_fingerprint"] == before["fingerprint"]),
                                        next_question_bound=bool(standard_for(task, task["context"].get("check_question"))))
                                report.finish(current_identity, current_kind, record, checks)
                        else:
                            record = run_node(harness, case)
                            checks = record.pop("checks")
                            record.update(model_calls=report.calls[start_calls:], tool_attempts=report.tool_attempts[start_tools:])
                            report.finish(identity, kind, record, checks)
                    except Exception as exc:
                        runs = []
                        with harness.store.tasks._connection() as db:
                            sessions = [row[0] for row in db.execute("SELECT session_id FROM agent_sessions_v2")]
                        for session in sessions:
                            runs.extend(harness.store.get(session)["runs"].values())
                        failed_run = dict(status="failed", model_calls=[c for r in runs for c in r.get("model_calls", [])],
                                          judgments=[j for r in runs for j in r.get("judgments", [])])
                        report.finish(current_identity, current_kind, dict(error_type=type(exc).__name__, run=failed_run,
                            model_calls=report.calls[start_calls:], tool_attempts=report.tool_attempts[start_tools:]), {"completed": False})
                    finally:
                        if client:
                            client.close()
                    print(json.dumps(dict(case=identity, variant=variant, result=report.records[-1]["automatic_result"])), flush=True)
        result = summary(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
