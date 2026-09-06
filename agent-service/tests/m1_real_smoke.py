#!/usr/bin/env python3
"""Run the explicit, paid M1 smoke against a running Agent service.

The default unittest suite uses mocks and never calls a model. This script is
intentionally separate so a real provider call is always an explicit choice.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m1_acceptance.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8742"


class SmokeFailure(RuntimeError):
    pass


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise SmokeFailure(f"{method} {path} returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", "connection failed")
        raise SmokeFailure(f"{method} {path} could not reach the service: {reason}") from None
    try:
        result = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SmokeFailure(f"{method} {path} returned invalid JSON") from None
    if not isinstance(result, dict):
        raise SmokeFailure(f"{method} {path} returned a non-object JSON value")
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def poll_capture(
    base_url: str,
    task_id: str,
    *,
    timeout: float,
    interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = request_json(
            base_url,
            f"/v1/capture/tasks/{task_id}",
            timeout=min(10.0, max(1.0, deadline - time.monotonic())),
        )
        status = view.get("status")
        if status in {"committing", "completed"}:
            return view
        if status in {"retryable_failed", "needs_attention", "cancelled"}:
            code = view.get("error_code") or "unknown"
            raise SmokeFailure(f"capture reached {status}: {code}")
        time.sleep(interval)
    raise SmokeFailure("capture did not reach committing before the timeout")


def validate_capture(view: dict[str, Any], source: str) -> tuple[str, dict[str, Any]]:
    require(view.get("status") in {"committing", "completed"}, "capture did not produce a committable result")
    result = view.get("result")
    require(isinstance(result, dict), "capture result is missing")
    cards = result.get("knowledge")
    require(isinstance(cards, list) and len(cards) == 1, "fixed sample did not produce exactly one knowledge card")
    card = cards[0]
    require(isinstance(card, dict), "knowledge card is not an object")
    required_fields = {
        "id",
        "learning_goal",
        "knowledge_type",
        "theme",
        "content_language",
        "question_language",
        "answer_language",
        "evidence_excerpt",
        "evidence_locator",
        "title",
        "explanation",
        "scoring_spec",
        "questions",
    }
    require(required_fields.issubset(card), "knowledge card is missing a stable field")
    try:
        uuid.UUID(card["id"])
    except (ValueError, TypeError, AttributeError):
        raise SmokeFailure("knowledge card id is not a UUID") from None
    require(card["knowledge_type"] == "concept", "fixed sample knowledge type is not concept")
    require("光合作用" in card.get("title", "") or "光合作用" in card.get("theme", ""), "fixed sample topic is not photosynthesis")
    require(card.get("content_language") == "zh", "content language is not zh")
    require(card.get("question_language") == "zh", "question language is not zh")
    require(card.get("answer_language") == "zh", "answer language is not zh")
    require(card["evidence_excerpt"] in source, "evidence excerpt is not a source substring")
    spec = card["scoring_spec"]
    require(isinstance(spec, dict), "scoring spec is missing")
    require(isinstance(spec.get("evidence"), str) and spec["evidence"] in source, "scoring evidence is not a source substring")
    require(isinstance(spec.get("must_cover"), list) and spec["must_cover"], "scoring key points are missing")
    questions = card["questions"]
    require(isinstance(questions, list) and questions, "questions are missing")
    main_questions = [question for question in questions if question.get("variant_index") == 0]
    require(len(main_questions) == 1, "capture did not produce exactly one main question")
    require(main_questions[0].get("prompt_text"), "main question text is missing")
    return main_questions[0]["prompt_text"], card


def grade_case(
    base_url: str,
    *,
    case: dict[str, Any],
    prompt_text: str,
    scoring_spec: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    attempt_id = str(uuid.uuid4())
    body = {
        "attempt_id": attempt_id,
        "prompt_text": prompt_text,
        "scoring_spec": scoring_spec,
        "answer_text": case["answer_text"],
        "hint_used": case["hint_used"],
        "primary_language": "zh",
    }
    first = request_json(
        base_url,
        "/v1/review/grade",
        method="POST",
        body=body,
        timeout=timeout,
    )
    require(first.get("attempt_id") == attempt_id, f"{case['case_id']} returned the wrong attempt id")
    require(first.get("agent_grade") == case["expected_grade"], f"{case['case_id']} returned an unexpected grade")
    require(first.get("brief_feedback"), f"{case['case_id']} returned empty feedback")

    duplicate = request_json(
        base_url,
        "/v1/review/grade",
        method="POST",
        body=body,
        timeout=timeout,
    )
    require(duplicate == first, f"{case['case_id']} was not idempotent")

    ack_path = f"/v1/review/attempts/{attempt_id}/ack"
    ack_body = {"attempt_id": attempt_id}
    ack = request_json(base_url, ack_path, method="POST", body=ack_body, timeout=timeout)
    duplicate_ack = request_json(base_url, ack_path, method="POST", body=ack_body, timeout=timeout)
    require(ack == {"attempt_id": attempt_id, "status": "acked"}, f"{case['case_id']} ACK failed")
    require(duplicate_ack == ack, f"{case['case_id']} ACK was not idempotent")

    return {
        "case_id": case["case_id"],
        "attempt_id": attempt_id,
        "agent_grade": first["agent_grade"],
        "feedback_present": True,
    }


def run_smoke(base_url: str, *, timeout: float, poll_timeout: float, poll_interval: float) -> dict[str, Any]:
    fixture = load_fixture()
    source = fixture["capture_request"]["raw_text"]
    task_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    capture_request = dict(fixture["capture_request"])
    capture_request["task_id"] = task_id
    capture_request["source_id"] = source_id

    request_json(base_url, "/healthz", timeout=timeout)
    initial = request_json(
        base_url,
        "/v1/capture/tasks",
        method="POST",
        body=capture_request,
        timeout=timeout,
    )
    view = poll_capture(base_url, task_id, timeout=poll_timeout, interval=poll_interval)
    prompt_text, card = validate_capture(view, source)
    if view["status"] == "committing":
        knowledge_ids = [card["id"]]
        acked = request_json(
            base_url,
            f"/v1/capture/tasks/{task_id}/ack",
            method="POST",
            body={"knowledge_ids": knowledge_ids},
            timeout=timeout,
        )
        require(acked.get("status") == "completed", "capture ACK did not complete the task")
        view = request_json(base_url, f"/v1/capture/tasks/{task_id}", timeout=timeout)
    require(view.get("status") == "completed", "capture did not finish after ACK")

    scoring_spec = card["scoring_spec"]
    grade_results = [
        grade_case(
            base_url,
            case=case,
            prompt_text=prompt_text,
            scoring_spec=scoring_spec,
            timeout=timeout,
        )
        for case in fixture["grade_cases"]
    ]
    return {
        "capture": {
            "task_id": task_id,
            "source_id": source_id,
            "initial_status": initial.get("status"),
            "final_status": view["status"],
            "knowledge_count": len(view["result"]["knowledge"]),
        },
        "grades": grade_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("REVIEW_TODAY_AGENT_URL", DEFAULT_BASE_URL),
        help="running Agent service URL (default: %(default)s)",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds")
    parser.add_argument("--poll-timeout", type=float, default=360.0, help="capture polling timeout in seconds")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="capture polling interval in seconds")
    args = parser.parse_args()
    try:
        result = run_smoke(
            args.base_url,
            timeout=args.timeout,
            poll_timeout=args.poll_timeout,
            poll_interval=args.poll_interval,
        )
    except SmokeFailure as exc:
        print(f"M1 real smoke failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
