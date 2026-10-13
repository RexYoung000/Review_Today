"""Replay the former scope counterexample in a temporary synthetic session.

Only lesson setup is controlled using the previously recorded real teaching
output. Intent routing and grading for all five subsequent turns are real.
Web and knowledge writes stay blocked by the existing RunReport helper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "agent-service"))
REQUEST = "检查一下我是否掌握这一节"
SHORT = "RAG 引入外部资料是为了补充模型训练未涵盖或后来更新的知识；检索到资料仍不保证资料相关、最新或回答正确。"
FULL = "模型的知识有训练时间边界，训练之后的新变化它不会自动知道；公司内部和个人私有资料通常没有进入训练；没有可靠依据时，它还可能编造看起来合理的回答。RAG 先检索外部资料，把相关资料与问题一起放进上下文，补充这些训练中缺失或后来更新的知识，为回答提供可追溯的依据。但检索仍可能找错或漏掉内容，资料可能过期或矛盾，模型也可能误读，所以不保证检索资料相关、最新，更不保证最终回答正确。"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-dir", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("a new append-only output is required")
    with tempfile.TemporaryDirectory(prefix="review-today-conservative-live-") as folder:
        database = Path(folder) / "checkpoint.sqlite3"
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(database)
        os.environ["REVIEW_TODAY_JEV_TEST"] = "0"
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.learning_progress import bound_check, comprehensive_bound, current_step
        from agent_service.schemas import ConversationOutput, SessionMessageRequest
        from tests.case_library.recording import RunReport
        from tests.test_conversation_v2 import ConversationTests, intent

        source = ROOT / "docs/evidence/2026-10-12-coach-rule-loading/real-samples.json"
        samples = json.loads(source.read_text())
        sample = next(s for s in samples["samples"] if s["scene"] == "teaching" and s["version"] == "new")
        output = sample["output"]
        harness = ConversationHarness(ConversationStore(HarnessStore(str(database))))
        sid = str(uuid.uuid4())
        fixture = ConversationTests()
        fixture.calls = []
        fixture.decision = intent("goal", workflow="source_learning", direct_teaching=True)

        def seed_model(system, user, schema, **kwargs):
            if issubclass(schema, ConversationOutput):
                return ConversationOutput.model_validate(output)
            return fixture.model(system, user, schema, **kwargs)

        with patch("agent_service.conversation.parse_model", side_effect=seed_model), \
             patch("agent_service.conversation.run_capture"), \
             patch("agent_service.conversation.web_search_capability", return_value={"status": "unverified"}):
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                content="直接教我 RAG", mode_preset="source_learning"))
            harness.drain(sid)
        seeded = harness.store.get(sid)
        if seeded["runs"][accepted.run_id]["status"] != "completed":
            raise RuntimeError("synthetic setup did not complete")
        task_id = seeded["active_task_id"]
        task = seeded["tasks"][task_id]
        assert bound_check(task)["scope"] == "concept", "old model step label must be narrowed"
        seed_path = args.output.with_suffix(".seed.json")
        with seed_path.open("x", encoding="utf-8") as seed_file:
            seed_file.write(json.dumps(dict(session_id=sid, task_id=task_id,
            source=str(source.relative_to(ROOT)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            source_model_scope=output["check_binding"]["scope"],
                initial_state=seeded), ensure_ascii=False, indent=2) + "\n")
        if args.native_dir:
            native = args.native_dir.resolve()
            if not native.name.startswith("review-today-") or not native.is_relative_to(Path("/tmp").resolve()):
                raise ValueError("native seed must use a private temporary QA directory")
            native.mkdir(parents=True, exist_ok=True)
            shutil.copy2(database, native / "checkpoint.sqlite3")
            (native / "session.json").write_text(json.dumps(dict(session_id=sid, task_id=task_id)) + "\n")

        planned = ["ordinary_short_pass", "request_comprehensive", "incomplete_comprehensive",
                   "request_again", "complete_comprehensive"]
        with RunReport(args.output, layer="live_fixed_context", planned=planned,
                fixture=dict(source=str(source.relative_to(ROOT)), initial_teaching="controlled reuse of recorded real output",
                    source_model_scope="step", mode="source_learning", jev=False,
                    answers="synthetic, selected before model calls", no_daily_data=True)) as report:
            def send(identity, text, expected):
                record = report.turn(harness, sid, SessionMessageRequest(
                    client_message_id=str(uuid.uuid4()), content=text, mode_preset="source_learning"))
                after = record["after"]
                current = after["tasks"][task_id]
                ctx = current["context"]
                step = current_step(current)
                checks = dict(same_task=after["active_task_id"] == task_id,
                    same_step=step["id"] == current_step(task)["id"],
                    no_automatic_save=after["draft"] is None and after["pending"] is None,
                    other_steps_unknown=all(s["understanding"] == "unknown"
                        for s in ctx["learning_plan"]["steps"] if s["id"] != step["id"]),
                    **expected(record, current))
                report.add(identity, record, checks)
                evaluation = ctx.get("practice", [])[-1].get("evaluation", {}) if ctx.get("practice") else {}
                print(json.dumps(dict(id=identity, checks=checks, replies=record["replies"],
                    current_step_understanding=step["understanding"],
                    binding=bound_check(current), evaluation=evaluation,
                    calls=[c["schema"] for c in record["model_calls"]]), ensure_ascii=False), flush=True)

            def ordinary(record, current):
                evaluation = current["context"].get("practice", [{}])[-1].get("evaluation", {})
                return dict(ordinary_passed=evaluation.get("passed") is True,
                    no_whole_flag=evaluation.get("step_completion_demonstrated") is False,
                    unverified=current_step(current)["understanding"] == "unknown")

            def requested(record, current):
                binding = bound_check(current)
                return dict(explicit_binding=comprehensive_bound(binding),
                    full_requirement_visible=current_step(current)["completion_condition"] in binding["question"] if binding else False,
                    no_new_coach_or_checker=[c["schema"] for c in record["model_calls"]] == ["IntentDecision"],
                    no_early_mastery=current_step(current)["understanding"] == "unknown")

            def incomplete(record, current):
                evaluation = current["context"].get("practice", [{}])[-1].get("evaluation", {})
                return dict(incomplete_rejected=evaluation.get("passed") is False,
                    no_whole_flag=evaluation.get("step_completion_demonstrated") is False,
                    unverified=current_step(current)["understanding"] == "unknown",
                    followup_concept_only=not comprehensive_bound(bound_check(current)))

            def complete(record, current):
                evaluation = current["context"].get("practice", [{}])[-1].get("evaluation", {})
                return dict(full_answer_passed=evaluation.get("passed") is True,
                    full_ability_proof=evaluation.get("step_completion_demonstrated") is True,
                    only_current_step_verified=current_step(current)["understanding"] == "verified",
                    whole_plan_not_verified=current["context"]["understanding"] == "unknown")

            send(planned[0], SHORT, ordinary)
            send(planned[1], REQUEST, requested)
            send(planned[2], SHORT, incomplete)
            send(planned[3], REQUEST, requested)
            send(planned[4], FULL, complete)
        print(json.dumps(dict(result="PASS" if report.passed else "FAIL", layer="live_fixed_context")), flush=True)
        return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
