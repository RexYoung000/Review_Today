"""Opt-in synthetic teaching/check replay against the configured real models.

Run from agent-service:
    .venv/bin/python -m tests.teaching_alignment_real_smoke --live --output /tmp/new-report.jsonl

The first lesson is printed before an operator supplies a synthetic answer on
stdin. --answer replays an already chosen answer; --skip also skips the second
lesson's check. Structural assertions do not establish semantic teaching quality.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid


def active_task(state):
    return state.get("tasks", {}).get(state.get("active_task_id"), {})


def current_step(task):
    plan = task.get("context", {}).get("learning_plan") or {}
    return next((step for step in plan.get("steps", [])
                 if step["id"] == plan.get("current_step_id")), {})


def verified_ids(task):
    return {step["id"] for step in (task.get("context", {}).get("learning_plan") or {}).get("steps", [])
            if step.get("understanding") == "verified"}


def show(identity, record, checks):
    task = active_task(record["after"])
    context = task.get("context", {})
    print(json.dumps(dict(case=identity, status=record["run"]["status"],
        replies=record["replies"], question=context.get("check_question"),
        learning_plan=context.get("learning_plan"), task_stage=task.get("stage"),
        understanding=context.get("understanding"),
        evaluation_calls=[call for call in record["model_calls"]
                          if call["schema"] == "MasteryEvaluation"],
        checks=checks, semantic_review="pending; inspect raw teaching, question, answer and feedback"),
        ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True, help="New append-only evidence file")
    parser.add_argument("--answer", help="Synthetic answer; otherwise read after displaying the actual lesson")
    parser.add_argument("--skip", action="store_true", help="Also skip the next lesson's check after continuing")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("a new evidence file is required")
    if args.answer is not None and not args.answer.strip():
        parser.error("--answer must not be empty")
    if args.answer is None and not sys.stdin.isatty():
        parser.error("use a PTY for interactive synthetic answers, or pass --answer")

    with tempfile.TemporaryDirectory(prefix="review-today-teaching-alignment-") as folder:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(folder) / "synthetic.sqlite3")
        os.environ["REVIEW_TODAY_JEV_TEST"] = "0"
        # Import only after isolation is set, including module-level stores.
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        from tests.case_library.recording import RunReport

        harness = ConversationHarness(ConversationStore(HarnessStore(os.environ["REVIEW_TODAY_HARNESS_DB"])))
        sid = str(uuid.uuid4())
        planned = ["first_lesson", "answer", "continue"] + (["skip_check"] if args.skip else [])
        with RunReport(args.output, layer="live_generated_flow", planned=planned,
                fixture=dict(initial_input="直接教我 RAG", mode="source_learning", jev=False,
                    answer_source="operator-supplied synthetic answer",
                    purpose="Teaching, question and grading evidence alignment; no daily data",
                    semantic_review="Review actual content; no keyword-based semantic PASS")) as report:

            def send(identity, content, checks_for):
                record = report.turn(harness, sid, SessionMessageRequest(
                    client_message_id=str(uuid.uuid4()), content=content, mode_preset="source_learning"))
                checks = checks_for(record)
                report.add(identity, record, checks)
                show(identity, record, checks)
                if record["run"]["status"] != "completed":
                    raise RuntimeError("synthetic run did not complete; inspect saved evidence")
                return record

            def first_checks(record):
                task = active_task(record["after"])
                plan = task.get("context", {}).get("learning_plan") or {}
                conditions = [step.get("completion_condition", "") for step in plan.get("steps", [])]
                return dict(one_task=len(record["after"].get("tasks", {})) == 1,
                    plan_exists=bool(plan.get("steps")),
                    per_step_conditions=bool(conditions) and all(conditions)
                        and len(set(conditions)) == len(conditions),
                    unanswered_remains_unknown=task.get("context", {}).get("understanding") == "unknown"
                        and not verified_ids(task),
                    has_check=bool(task.get("context", {}).get("check_question")))

            first = send("first_lesson", "直接教我 RAG", first_checks)
            task_id = active_task(first["after"]).get("task_id")
            if not task_id:
                raise RuntimeError("first lesson did not create a learning task")
            answer = args.answer
            if answer is None:
                print("SYNTHETIC ANSWER (based on the question above; do not enter personal data):", flush=True)
                answer = input().strip()
            if not answer:
                raise ValueError("synthetic answer must not be empty")

            def answer_checks(record):
                before = active_task(record["before"])
                before_context = before.get("context", {})
                expected_step = current_step(before)
                calls = [call for call in record["model_calls"] if call["schema"] == "MasteryEvaluation"]
                inputs = [call.get("input", {}) for call in calls]
                return dict(same_task=active_task(record["after"]).get("task_id") == task_id,
                    evaluated_answer=bool(inputs),
                    exact_answer=bool(inputs) and all(value.get("answer") == answer for value in inputs),
                    correct_question=bool(inputs) and all(value.get("question") == before_context.get("check_question") for value in inputs),
                    lesson_reference=bool(inputs) and bool(before_context.get("last_lesson"))
                        and all(value.get("reference") == before_context.get("last_lesson") for value in inputs),
                    bound_current_step=bool(inputs) and bool(expected_step)
                        and all(all((value.get("learning_step") or {}).get(key) == expected_step.get(key)
                                    for key in ("id", "title")) for value in inputs),
                    no_plan_criterion_as_rubric=bool(inputs) and all("completion_condition" not in (value.get("learning_step") or {}) for value in inputs),
                    evaluated_current_step=record["run"].get("evaluated_step_id") == expected_step.get("id"))

            send("answer", answer, answer_checks)

            def continue_checks(record):
                before = active_task(record["before"])
                after = active_task(record["after"])
                prior_ids = [step["id"] for step in (before.get("context", {}).get("learning_plan") or {}).get("steps", [])]
                prior_id = current_step(before).get("id")
                next_id = current_step(after).get("id")
                return dict(same_task=after.get("task_id") == task_id,
                    advanced_one_step=(prior_id in prior_ids and next_id in prior_ids
                        and prior_ids.index(next_id) == prior_ids.index(prior_id) + 1),
                    continue_does_not_verify=verified_ids(after) == verified_ids(before),
                    next_lesson_unknown=current_step(after).get("understanding") == "unknown",
                    has_next_check=bool(after.get("context", {}).get("check_question")))

            send("continue", "继续下一节", continue_checks)
            if args.skip:
                def skip_checks(record):
                    before = active_task(record["before"])
                    after = active_task(record["after"])
                    return dict(same_task=after.get("task_id") == task_id,
                        skip_does_not_verify=verified_ids(after) == verified_ids(before),
                        no_grading=not any(call["schema"] == "MasteryEvaluation" for call in record["model_calls"]))

                send("skip_check", "这道检查题先跳过，继续下一节", skip_checks)
        raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
