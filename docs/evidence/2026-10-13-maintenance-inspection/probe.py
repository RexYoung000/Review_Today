"""Offline inspection of background compaction and service capability probes.

Run from agent-service with its venv and PYTHONPATH=.; no real SDK transport,
service startup, user database, provider configuration or production mutation.
Assertions preserve today's baseline, not proposed behavior.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

# Imports instantiate the default store. Fence that too before importing.
_isolated = tempfile.TemporaryDirectory(prefix="review-today-maintenance-probe-")
os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(_isolated.name) / "global.sqlite3")
os.environ["REVIEW_TODAY_JEV_TEST"] = "0"

from agent_service import model_capabilities as capabilities
from agent_service import openai_client as client_module
from agent_service import run_accounting as accounting
from agent_service.conversation import conversation_harness
from agent_service.interruptible_call import pool
from agent_service.schemas import ConversationSummary
from tests import test_context_compaction as compaction


def inspect_summary(case):
    fixture = compaction.ContextCompactionTests()
    fixture.setUp()
    try:
        with patch.object(fixture.harness, "start"), patch.object(fixture.harness, "_schedule_summary"):
            fixture.seed()
            rid = list(fixture.state()["runs"])[-1]
            with fixture.store.transaction(fixture.sid) as data:
                run = data["runs"][rid]
                run["execution_budget"]["started"] -= accounting.RUN_SECONDS + 10
                run["execution_budget"]["attempts"] = accounting.MODEL_ATTEMPTS
                if case in {"calls_limit", "input_limit", "time_limit"}:
                    run["maintenance_budget"] = dict(id="offline-maintenance-budget",
                        started=accounting.time.time(), attempts=0, estimated_input_tokens=0)
                    budget = run["maintenance_budget"]
                    if case == "calls_limit": budget["attempts"] = accounting.MODEL_ATTEMPTS
                    if case == "input_limit": budget["estimated_input_tokens"] = accounting.ESTIMATED_INPUT_LIMIT
                    if case == "time_limit": budget["started"] -= accounting.RUN_SECONDS + 1
            before = fixture.state()
            original_calls = len(before["runs"][rid].get("model_calls", []))
            sdk = MagicMock()
            def reply(**kwargs):
                if case == "request_failure":
                    raise client_module.ModelCallError("TIMEOUT", "offline timeout")
                if case == "archive_race":
                    with fixture.store.transaction(fixture.sid) as data:
                        data.update(status="archived", lifecycle_revision=data.get("lifecycle_revision", 0) + 1)
                parsed = ConversationSummary(goal="RAG", confirmed_decisions=[], open_questions=[], summary="受控交接摘要")
                return NS(id="offline-summary", status="completed", output=[], output_parsed=parsed,
                    usage=None if case == "usage_missing" else NS(input_tokens=100, output_tokens=20))
            sdk.responses.parse.side_effect = reply
            with patch.object(client_module, "PROVIDER", "openai_compatible"), \
                 patch.object(client_module, "_client", return_value=sdk), \
                 patch("agent_service.conversation.parse_model", side_effect=client_module.parse_model), \
                 patch("agent_service.conversation.configured_window", return_value=64000 if case == "shared_attempt_limit" else 256000):
                fixture.harness.maintain_summary(fixture.sid)
                # Archive can release the caller before its detached request finishes
                # recording. Observe the settled ledger before removing the fixture.
                deadline = time.monotonic() + 3
                key = (fixture.sid, rid)
                while time.monotonic() < deadline:
                    with pool.lock:
                        if key not in pool.active:
                            break
                    time.sleep(.01)
                with pool.lock:
                    assert key not in pool.active
            after = fixture.state()
            run = after["runs"][rid]
            calls = run.get("model_calls", [])[original_calls:]
            assert run["status"] == "completed"
            assert run["execution_budget"] == before["runs"][rid]["execution_budget"]
            assert after["messages"] == before["messages"]
            saved = after["summary_version"] == 1
            assert saved == (case in {"success", "usage_missing"})
            if case in {"calls_limit", "input_limit", "time_limit"}:
                assert not sdk.responses.parse.called and not calls
                assert after["summary_error"]["code"] == {
                    "calls_limit": "RT.RUN.BUDGET_CALLS", "input_limit": "RT.RUN.BUDGET_INPUT",
                    "time_limit": "RT.RUN.BUDGET_TIME"}[case]
            elif case == "shared_attempt_limit":
                assert sdk.responses.parse.call_count == 2
                assert len(calls) == 3 and [c["transport_requests"] for c in calls] == [1, 1, 0]
                assert after["summary_error"]["code"] == "RT.MODEL.ATTEMPTS_EXHAUSTED"
                assert calls[-1]["usage_state"] == "unavailable"
            else:
                assert sdk.responses.parse.call_count == 1 and len(calls) == 1
                assert calls[0]["background"] and calls[0]["transport_requests"] == 1
                assert len(calls[0]["request_ids"]) == 1
                expected = "unavailable" if case in {"usage_missing", "request_failure"} else "reported"
                assert calls[0]["usage_state"] == expected
                if expected == "reported":
                    assert calls[0]["usage"][0]["input_tokens"] == 100
                    assert calls[0]["usage"][0]["request_id"] == calls[0]["request_ids"][0]
            return dict(case="summary_" + case, summary_saved=saved, sdk_requests=sdk.responses.parse.call_count,
                completed_reply_preserved=True, foreground_budget_unchanged=True, raw_messages_unchanged=True,
                summary_error=after.get("summary_error", {}).get("code"),
                maintenance_attempts=run.get("maintenance_budget", {}).get("attempts"),
                calls=[dict(background=c["background"], requests=c["transport_requests"], usage_state=c["usage_state"],
                            usage=c["usage"], status=c["status"]) for c in calls])
    finally:
        fixture.tearDown()


def inspect_capabilities(case):
    provider = "deepseek" if case == "deepseek_grouped" else "openai_compatible"
    states = {role: dict(model="offline-shared" if case == "deepseek_grouped" else "offline-" + role,
                        status="checking", error="", streaming="checking") for role in ("router", "coach", "risk")}
    sdk = MagicMock()
    receipts = []
    actual_report = client_module._report_usage
    def observe(response, callback, **kwargs):
        receipts.append(dict(has_usage_callback=callback is not None, response_id=getattr(response, "id", None),
                             supplier_usage_present=getattr(response, "usage", None) is not None))
        return actual_report(response, callback, **kwargs)
    def success(**kwargs):
        return NS(id="offline-structured", status="completed", output=[],
            output_parsed=kwargs["text_format"].model_validate({"ready": True}),
            usage=NS(input_tokens=100, output_tokens=20))
    stream_text = json.dumps(dict(ready=True, message="one two three four five"))
    def create(**kwargs):
        response = NS(id="offline-stream", status="completed", usage=NS(input_tokens=100, output_tokens=20),
                      output=[NS(content=[NS(type="output_text", text=stream_text if kwargs.get("stream") else '{"ready":true}')])])
        if not kwargs.get("stream"):
            return response
        result = MagicMock()
        result.__enter__.return_value = iter([
            NS(type="response.created", response=NS(id="offline-stream")),
            NS(type="response.output_text.delta", delta='{"ready":true,"message":"one '),
            NS(type="response.output_text.delta", delta='two three four five"}'),
            NS(type="response.completed", response=response)])
        return result
    sdk.responses.create.side_effect = create
    sdk.responses.parse.side_effect = (client_module.ModelCallError("CONNECTION", "offline failure") if case == "transient_loop"
        else client_module.ModelCallError("PROVIDER", "HTTP 403") if case == "access_denied" else success)
    clock = 100_000.0
    rounds = []
    with ExitStack() as stack:
        for name, value in {"_state": states, "_retry_attempt": 0, "_next_probe": 0.0,
                            "_probing": False, "_scheduler_started": True, "PROVIDER": provider}.items():
            stack.enter_context(patch.object(capabilities, name, value))
        stack.enter_context(patch.object(capabilities, "openai_key", return_value="offline-placeholder"))
        stack.enter_context(patch.object(client_module, "PROVIDER", provider))
        stack.enter_context(patch.object(client_module, "_client", return_value=sdk))
        stack.enter_context(patch.object(client_module, "_report_usage", side_effect=observe))
        stack.enter_context(patch.object(conversation_harness.store, "sessions", return_value=[]))
        with patch.object(capabilities.time, "time", side_effect=lambda: clock):
            for index in range(8 if case == "transient_loop" else 1):
                # Capture start_probe's worker, then execute it with real ThreadPool
                # threads restored. No scheduler or wall-clock sleeps are started.
                with patch.object(capabilities.threading, "Thread") as thread:
                    capabilities.start_probe(reset=index == 0)
                    job = thread.call_args.kwargs
                job["target"](*job.get("args", ()))
                next_probe = capabilities._next_probe
                rounds.append(dict(round=index + 1, retry_counter=capabilities._retry_attempt,
                    retry_scheduled=bool(next_probe), delay_seconds=next_probe - clock if next_probe else None,
                    sdk_requests=sdk.responses.parse.call_count + sdk.responses.create.call_count))
                if not next_probe: break
                clock = next_probe
        snapshot = capabilities.snapshot()
    if case == "transient_loop":
        assert len(rounds) == 8 and rounds[-1]["retry_scheduled"]
        assert [row["delay_seconds"] for row in rounds] == [10, 30] + [120] * 6
        assert sdk.responses.parse.call_count == 24
    elif case == "access_denied":
        assert len(rounds) == 1 and not rounds[0]["retry_scheduled"]
    else:
        assert all(value["status"] == "ready" for value in snapshot.values())
        assert sdk.responses.parse.call_count + sdk.responses.create.call_count == 4
        assert receipts and all(row["supplier_usage_present"] and not row["has_usage_callback"] for row in receipts)
    return dict(case="capability_" + case, provider_branch=provider, rounds=rounds,
        sdk_requests=sdk.responses.parse.call_count + sdk.responses.create.call_count,
        receipt_observations=receipts, states=snapshot, real_provider_requests=0)


def main():
    results = [inspect_summary(case) for case in (
        "success", "usage_missing", "request_failure", "calls_limit", "input_limit", "time_limit", "archive_race", "shared_attempt_limit")]
    results += [inspect_capabilities(case) for case in (
        "transient_loop", "compatible_success", "deepseek_grouped", "access_denied")]
    report = dict(kind="baseline_inspection", date="2026-10-13", production_changed=False,
                  real_provider_requests=0, case_count=len(results), results=results)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    _isolated.cleanup()


if __name__ == "__main__":
    main()
