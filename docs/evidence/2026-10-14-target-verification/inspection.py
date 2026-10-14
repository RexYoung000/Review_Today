"""Inspect existing completion boundaries with controlled callbacks and temp DBs.

This is a read-only production audit, not an implementation or a semantic model
evaluation. Run from agent-service with its venv; all model and capture calls are
fixtures. Do not run against the daily database.
"""
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def isolated_fixture(kind="comprehensive"):
    from tests.test_comprehensive_check import ComprehensiveCheckTests
    from tests.test_conversation_v2 import ConversationTests
    fixture = ComprehensiveCheckTests() if kind == "comprehensive" else ConversationTests()
    fixture.setUp()
    try:
        with patch.object(fixture.harness, "start"), patch.object(fixture.harness, "_schedule_summary"):
            yield fixture
    finally:
        fixture.tearDown()


def snapshot(fixture, label):
    state = fixture.state()
    task = state["tasks"].get(state.get("active_task_id"))
    run = list(state["runs"].values())[-1]
    context = (task or {}).get("context", {})
    plan = context.get("learning_plan") or {}
    return dict(label=label, run_status=run["status"], task_status=(task or {}).get("status"),
                task_stage=(task or {}).get("stage"), understanding=context.get("understanding", "unknown"),
                independent_passed=context.get("independent_passed", False),
                transfer_passed=context.get("transfer_passed", False),
                steps=[dict(title=step["title"], state=step["state"], understanding=step["understanding"],
                            verified_concepts=len(step.get("verified_concepts", []))) for step in plan.get("steps", [])],
                draft=bool(state.get("draft")), capture_calls=fixture.capture.call_count,
                error_code=run.get("error_code"), last_reply=next((message["content"] for message in
                    reversed(state["messages"]) if message["role"] == "coach"), ""),
                input_retained=any(message["message_id"] in run["input_ids"] for message in state["messages"]),
                final_failure_events=[event["user_summary"] for event in state["events"]
                                      if event.get("run_id") == run["run_id"] and event["stage"] == "failed"])


def inspect():
    from agent_service.schemas import MasteryEvaluation
    from agent_service.call_errors import ModelCallError
    from tests.test_conversation_v2 import intent
    rows = []
    with isolated_fixture() as f:
        f.start_lesson(); f.claim_whole = True; f.answer()
        row = snapshot(f, "ordinary question cannot certify a whole goal")
        assert row["run_status"] == "completed" and row["task_status"] != "completed"
        assert all(step["understanding"] == "unknown" for step in row["steps"])
        assert row["capture_calls"] == 0 and not row["draft"]
        rows.append(row)

    with isolated_fixture() as f:
        task = f.start_lesson(); f.request(task); f.claim_whole = True; f.with_proof = False; f.answer()
        row = snapshot(f, "comprehensive model pass without learner evidence")
        assert row["task_status"] != "completed" and row["understanding"] == "unknown"
        assert not row["draft"] and row["capture_calls"] == 0
        rows.append(row)

    with isolated_fixture() as f:
        task = f.start_lesson(); f.request(task); f.claim_whole = True; f.answer()
        row = snapshot(f, "first complete step does not complete a two-step goal")
        assert [step["understanding"] for step in row["steps"]] == ["verified", "unknown"]
        assert row["task_status"] != "completed" and row["understanding"] == "unknown"
        rows.append(row)
        f.decision = intent("continue", workflow="source_learning", scope="continue_goal")
        f.send("继续下一节")
        f.request(f.state()["tasks"][f.state()["active_task_id"]]); f.answer()
        row = snapshot(f, "all steps verified creates a completed learning result, not a saved card")
        assert all(step["understanding"] == "verified" for step in row["steps"])
        assert row["task_status"] == "completed" and row["task_stage"] == "mastered"
        assert row["draft"] and row["capture_calls"] == 0
        rows.append(row)

    with isolated_fixture() as f:
        f.start_lesson()
        f.decision = intent("skip_check", workflow="source_learning", scope="continue_goal")
        f.send("跳过检查，继续下一节"); f.send("最后一节也跳过检查，结束讲解")
        row = snapshot(f, "skipped checks finish explanation, not mastery")
        assert row["task_status"] == "completed" and row["task_stage"] == "lesson_complete"
        assert row["understanding"] == "unknown" and "未检查或跳过" in row["last_reply"]
        assert not row["draft"] and row["capture_calls"] == 0
        rows.append(row)

    with isolated_fixture("problem") as f:
        f.decision = intent("question", workflow="problem_solving", scope="learning")
        f.send("RAG 是什么", mode="problem_solving")
        f.decision = intent("answer", workflow="problem_solving", scope="continue_goal")
        f.send("准备工程师面试"); f.send("先检索再生成")
        row = snapshot(f, "problem independent pass still waits for transfer")
        assert row["independent_passed"] and not row["transfer_passed"]
        assert row["task_status"] != "completed" and not row["draft"]
        rows.append(row)
        f.send("没有相关证据时应明确边界")
        row = snapshot(f, "problem independent and transfer gates complete without saving")
        assert row["independent_passed"] and row["transfer_passed"]
        assert row["task_status"] == "completed" and row["understanding"] == "verified"
        assert row["draft"] and row["capture_calls"] == 0
        rows.append(row)

    for kind in ("SCHEMA", "TIMEOUT", "unexpected"):
        with isolated_fixture() as f:
            task = f.start_lesson(); f.request(task)
            before = snapshot(f, "before failed evaluation")
            base, attempts = f.model, []
            def fail(system, user, schema, **kwargs):
                if schema is MasteryEvaluation:
                    attempts.append(schema.__name__)
                    if kind == "unexpected":
                        raise RuntimeError("synthetic evaluation unavailable")
                    raise ModelCallError(kind, "controlled audit failure")
                return base(system, user, schema, **kwargs)
            with patch("agent_service.conversation.parse_model", side_effect=fail):
                f.answer()
            row = snapshot(f, "evaluation failure: " + kind)
            row["synthetic_evaluation_callbacks"] = len(attempts)
            assert row["run_status"] == "retryable_failed" and row["task_status"] == "retryable_failed"
            assert row["understanding"] == "unknown" and row["steps"] == before["steps"]
            assert row["input_retained"] and not row["draft"] and row["capture_calls"] == 0
            rows.append(row)

    with isolated_fixture() as f:
        task = f.start_lesson(); f.request(task); f.claim_whole = True
        base = f.model
        def stop_before_result(system, user, schema, **kwargs):
            result = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                f.control(f.state()["foreground"], "stop")
            return result
        with patch("agent_service.conversation.parse_model", side_effect=stop_before_result):
            f.answer()
        row = snapshot(f, "stopped evaluation rejects late positive result")
        assert row["run_status"] == "interrupted" and row["task_status"] != "completed"
        assert all(step["understanding"] == "unknown" for step in row["steps"])
        assert not row["draft"] and row["capture_calls"] == 0
        rows.append(row)
    return dict(kind="target_completion_inspection", scenarios=rows, assertions_passed=len(rows),
                supplier_requests=0, daily_database_written=False, semantic_accuracy_verified=False,
                http_chain_verified=False, ui_verified=False, production_changed=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="review-today-target-global-") as directory:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "isolated.sqlite3")
        # This selects the compatibility fixture branch only within this process.
        os.environ["REVIEW_TODAY_LLM_PROVIDER"] = "openai_compatible"
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
