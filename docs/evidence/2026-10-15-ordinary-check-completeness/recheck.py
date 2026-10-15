"""CHECK-01 bounded real grading recheck. One case per explicit invocation.

Uses the original real pre-answer lesson in new isolated sessions; it does not
regenerate the lesson, replace model responses, start a server/App or run probes.
The original audit's SDK request gate continues the shared counter from 13/30.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import uuid


EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[2]
ORIGINAL = EVIDENCE.parent / "2026-10-14-live-learning-save"
CASES = {
    "incomplete": "相似度高只说明资料与问题在语义上接近，所以可能相关；但原资料仍可能有错误或过时。",
    "complete": ("找出来的文字只是看着切题，不能凭这个分数保证事实。材料可能早就失效，或者本身写错。"
                 "写回答时也可能自行添话，删掉原来的限制。要逐句找到原文根据，再看版本和使用场景是否合适。"),
    "single_point": "只能说明找到的文字和问题比较相关，不能据此保证它说的是事实。",
}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CASES)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    assert directory.name.startswith("review-today-ordinary-check-")
    assert (directory / "request-count.json").is_file()
    if (directory / "STOP").exists():
        raise SystemExit("This batch has stopped; do not rerun it for a pass")
    output = directory / (args.case + "-result.json")
    if output.exists():
        raise SystemExit("Case already recorded; do not overwrite or rerun")
    for name, expected in setup["provider_config_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    initial_requests = json.loads((directory / "request-count.json").read_text())["actual_requests"]
    assert 13 <= initial_requests < 30
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(directory / "checkpoint.sqlite3")
    sys.path.insert(0, str(ROOT / "agent-service"))
    module = importlib.util.spec_from_file_location("original_live_audit", ORIGINAL / "audit_runtime.py")
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)
    audit.install(str(directory), str(ROOT / "agent-service"))

    from agent_service import config
    from agent_service.conversation import ConversationHarness
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    from agent_service.learning_progress import bind_check, current_step
    from agent_service.schemas import SessionMessageRequest

    assert config.PROVIDER == "deepseek"
    # Remap every UUID consistently so parallel case histories cannot overwrite
    # each other in the same isolated DB. The real text and reference stay exact.
    namespace = uuid.uuid4()
    original_text = (ORIGINAL / "phase-01-lesson.json").read_text()
    clone = re.sub(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                   lambda match: str(uuid.uuid5(namespace, match[0])), original_text)
    seed = json.loads(clone)["checkpoint"]
    sid, tid = seed["session_id"], seed["active_task_id"]
    original_binding = copy.deepcopy(seed["tasks"][tid]["context"]["check_binding"])
    store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
    harness = ConversationHarness(store)
    with store.transaction(sid) as data:
        data.update(seed)
        if args.case == "single_point":
            task = data["tasks"][tid]
            task["context"]["check_question"] = "检索相似度高说明什么，能否据此保证资料正确？"
            bind_check(task, task["context"]["check_question"], dict(
                step_title=original_binding["step_title"], concepts=["检索相似度"], scope="concept",
                evidence_quotes=[original_binding["evidence_quotes"][0]]))
    save(directory / (args.case + "-before.json"), store.get(sid))
    audit.emit("recheck_case_start", case=args.case, session_id=sid,
               original_requests=13, actual_requests=initial_requests, pre_answer_seed="phase-01-lesson.json",
               seed_sha256=setup["phase1_seed_sha256"], model_substituted=False, fresh_probes=False)
    accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=CASES[args.case],
                                                       mode_preset=seed["mode"]))
    harness.drain(sid)
    data = store.get(sid)
    save(directory / (args.case + "-after.json"), data)
    task = data["tasks"][tid]
    run = data["runs"][accepted.run_id]
    practice = next((p for p in reversed(task["context"].get("practice", []))
                     if p.get("run_id") == accepted.run_id), None)
    grade = (practice or {}).get("evaluation")
    offers = list(data.get("capture_offers", {}).values())
    expected_pass = args.case != "incomplete"
    expected_concepts = ["检索相似度"] if args.case == "single_point" else original_binding["concepts"]
    checks = dict(run_completed=run["status"] == "completed", evaluation_exists=grade is not None,
                  answer_pass_matches=grade is not None and grade["passed"] == expected_pass,
                  concepts_match=(practice or {}).get("verified_concepts") == (expected_concepts if expected_pass else []),
                  invitation_count_matches=len(offers) == int(expected_pass),
                  chapter_not_verified=current_step(task)["understanding"] == "unknown",
                  no_knowledge_write=all(not offer["knowledge_ids"] for offer in offers) and data.get("draft") is None)
    if not expected_pass:
        checks["supplement_question_exists"] = bool(task["context"].get("check_question"))
    requests = json.loads((directory / "request-count.json").read_text())["actual_requests"]
    result = dict(case=args.case, result="PASS" if all(checks.values()) else "FAIL", checks=checks,
                  question=original_binding["question"] if args.case != "single_point" else data["tasks"][tid]["context"]["check_binding"]["question"],
                  answer=CASES[args.case], session_id=sid, run_id=accepted.run_id, run_status=run["status"],
                  error_code=run.get("error_code"), evaluation=grade,
                  verified_concepts=(practice or {}).get("verified_concepts"),
                  offers=[{k: offer.get(k) for k in ("id", "title", "concepts", "status", "trigger", "knowledge_ids")} for offer in offers],
                  reply=[m["content"] for m in data["messages"] if m.get("role") == "coach" and m.get("run_id") == accepted.run_id],
                  actual_requests=requests, additional_case_requests=requests-initial_requests,
                  batch_additional_requests=requests-13,
                  provider=config.PROVIDER, router_model=config.ROUTER_MODEL, coach_model=config.COACH_MODEL,
                  scope="real fixed-context service grading; no fresh lesson, native App/HTTP or save chain")
    save(output, result)
    audit.emit("recheck_case_end", case=args.case, result=result["result"], actual_requests=requests)
    if result["result"] != "PASS" or requests >= 30:
        (directory / "STOP").write_text("Stopped on failure or original total request cap\n")
    print(json.dumps({k: result[k] for k in ("case", "result", "checks", "actual_requests", "additional_case_requests")}, ensure_ascii=False), flush=True)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
