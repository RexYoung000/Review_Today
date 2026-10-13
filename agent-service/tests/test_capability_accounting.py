"""Four-round service recovery and durable facts through the real SDK adapter."""
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest

from agent_service import model_capabilities as cap
from agent_service import openai_client as llm
from agent_service.capability_accounting import CapabilityLedger


def sdk_success(**kwargs):
    return NS(id="supplier-reused", status="completed", output=[],
              output_parsed=kwargs["text_format"].model_validate({"ready": True}),
              usage=NS(input_tokens=100, output_tokens=20))


def sdk_create(**kwargs):
    text = json.dumps({"ready": True, "message": "one two three four five"})
    response = NS(id="supplier-reused", status="completed", usage=NS(input_tokens=100, output_tokens=20),
                  output=[NS(content=[NS(type="output_text", text=text)])])
    if not kwargs.get("stream"):
        return response
    stream = MagicMock()
    stream.__enter__.return_value = iter([
        NS(type="response.created", response=NS(id="supplier-reused")),
        NS(type="response.output_text.delta", delta='{"ready":true,"message":"one '),
        NS(type="response.output_text.delta", delta='two three four five"}'),
        NS(type="response.completed", response=response)])
    return stream


@pytest.fixture
def f(tmp_path, monkeypatch):
    from agent_service.conversation import conversation_harness
    ledger = CapabilityLedger(tmp_path / "capabilities.sqlite3")
    states = {role: dict(model="offline-" + role, status="checking", error="", streaming="checking")
              for role in ("router", "coach", "risk")}
    for name, value in {"_ledger": ledger, "_batch_id": None, "_retry_attempt": 0, "_next_probe": 0,
                        "_probing": False, "_scheduler_started": True, "_state": states,
                        "PROVIDER": "openai_compatible"}.items():
        monkeypatch.setattr(cap, name, value)
    monkeypatch.setattr(cap, "openai_key", lambda: "offline-placeholder")
    monkeypatch.setattr(conversation_harness.store, "sessions", lambda: [])
    monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    client = MagicMock()
    client.responses.parse.side_effect = sdk_success
    client.responses.create.side_effect = sdk_create
    monkeypatch.setattr(llm, "_client", lambda **kw: client)
    return NS(ledger=ledger, client=client, states=states)


def run_round(reset=False):
    with patch.object(cap.threading, "Thread") as thread:
        cap.start_probe(reset=reset)
        if not thread.called:
            return False
        job = thread.call_args.kwargs
    job["target"](*job.get("args", ()), **job.get("kwargs", {}))
    return True


def wire_count(f):
    return (f.client.responses.parse.call_count + f.client.responses.create.call_count
            + f.client.chat.completions.parse.call_count)


def new_call(ledger):
    bid = ledger.begin("offline-provider")
    ledger.start_round(bid, 1)
    cid = ledger.reserve(bid, 1, model="offline-model", roles=["coach"], kind="structured", strength="smart")
    return bid, cid


def test_four_rounds_stop_all_future_auto_dispatch_and_keep_actual_requests(f, monkeypatch):
    monkeypatch.setattr(cap.time, "time", lambda: 100)
    f.client.responses.parse.side_effect = llm.ModelCallError("CONNECTION", "offline failure")
    for index, deadline in enumerate([110, 130, 220, 0]):
        assert run_round(reset=index == 0)
        assert cap._next_probe == deadline
    before = f.ledger.get(cap._batch_id)
    assert before["rounds"] == 4 and before["status"] == "exhausted"
    assert len(before["calls"]) == wire_count(f) == 12
    assert all(c["transport_requests"] == 1 and c["usage_state"] == "unavailable" for c in before["calls"])
    assert not run_round() and not run_round()
    cap.probe_with_streaming()  # Direct helper cannot bypass the exhausted batch.
    assert wire_count(f) == 12 and f.ledger.get(cap._batch_id) == before


def test_manual_reprobe_starts_new_batch_and_preserves_old_exhausted_ledger(f):
    f.client.responses.parse.side_effect = llm.ModelCallError("CONNECTION")
    for index in range(4): assert run_round(reset=index == 0)
    old_id = cap._batch_id
    old = f.ledger.get(old_id)
    f.client.responses.parse.side_effect = sdk_success
    assert run_round(reset=True)
    assert cap._batch_id != old_id and cap._next_probe == 0
    assert f.ledger.get(old_id) == old
    current = f.ledger.get(cap._batch_id)
    assert current["rounds"] == 1 and current["status"] == "finished"
    assert len(current["calls"]) == 4
    assert all(c["usage_state"] == "reported" for c in current["calls"])
    assert len(f.ledger.recent()) == 2


@pytest.mark.parametrize("error", [llm.ModelCallError("PROVIDER", "HTTP 401"),
                                  llm.ModelCallError("PROVIDER", "HTTP 403"), llm.ModelCallError("UNSUPPORTED")])
def test_access_and_unsupported_failures_do_not_auto_retry(f, error):
    f.client.responses.parse.side_effect = error
    assert run_round(reset=True)
    assert cap._next_probe == 0 and not run_round()
    assert wire_count(f) == 3
    assert f.ledger.get(cap._batch_id)["status"] == "finished"


def test_missing_key_records_batch_without_claiming_any_request(f, monkeypatch):
    monkeypatch.setattr(cap, "openai_key", lambda: "")
    assert run_round(reset=True)
    batch = f.ledger.get(cap._batch_id)
    assert batch["rounds"] == 1 and batch["calls"] == [] and batch["status"] == "finished"
    assert wire_count(f) == 0 and not run_round()


def test_retry_only_affected_role_and_preserve_unrelated_capabilities(f):
    f.states["router"].update(status="ready", retryable=False)
    f.states["risk"].update(status="unavailable", retryable=False, category="access_denied")
    f.states["coach"].update(status="unavailable", retryable=True)
    f.client.responses.parse.side_effect = llm.ModelCallError("CONNECTION")
    assert run_round()
    batch = f.ledger.get(cap._batch_id)
    assert wire_count(f) == 1 and batch["calls"][0]["roles"] == ["coach"]
    assert f.states["router"]["status"] == "ready" and f.states["risk"]["category"] == "access_denied"


@pytest.mark.parametrize("grouped", [True, False])
def test_deepseek_grouping_keeps_smart_deep_and_streaming_facts_distinct(f, monkeypatch, grouped):
    monkeypatch.setattr(cap, "PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "PROVIDER", "deepseek")
    if grouped:
        for value in f.states.values(): value["model"] = "offline-shared"
    assert run_round(reset=True)
    batch = f.ledger.get(cap._batch_id)
    assert wire_count(f) == len(batch["calls"]) == (4 if grouped else 8)
    assert {(c["kind"], c["strength"]) for c in batch["calls"]} == {
        ("structured", "smart"), ("structured", "deep"), ("streaming", "smart"), ("streaming", "deep")}
    assert all(c["usage_state"] == "reported" for c in batch["calls"])
    assert all(len(c["roles"]) == (3 if grouped and c["kind"] == "structured" else 1) for c in batch["calls"])


def test_deep_probe_failure_keeps_verified_smart_capability_and_its_usage(f, monkeypatch):
    monkeypatch.setattr(cap, "PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "PROVIDER", "deepseek")
    def create(**kw):
        if kw["model"] == "offline-coach" and kw.get("reasoning", {}).get("effort") == "high":
            raise llm.ModelCallError("CONNECTION")
        return sdk_create(**kw)
    f.client.responses.create.side_effect = create
    assert run_round(reset=True)
    assert f.states["coach"]["status"] == "ready" and f.states["coach"]["streaming"] == "ready"
    assert f.states["coach"]["strengths"]["deep"]["status"] == "unavailable" and cap._next_probe
    calls = f.ledger.get(cap._batch_id)["calls"]
    failed = next(c for c in calls if c["model"] == "offline-coach" and c["strength"] == "deep")
    assert failed["transport_requests"] == 1 and failed["usage_state"] == "unavailable"
    assert not any(c["kind"] == "streaming" and c["strength"] == "deep" for c in calls)


@pytest.mark.parametrize("counts,state", [({"input_tokens": None, "output_tokens": None}, "unavailable"),
    ({"input_tokens": 10, "output_tokens": None}, "partial"),
    ({"input_tokens": None, "output_tokens": 2}, "partial"), ({"input_tokens": 0, "output_tokens": 0}, "reported")])
def test_unknown_partial_and_explicit_zero_survive_reopen(f, counts, state):
    bid, cid = new_call(f.ledger)
    identity = f.ledger.request(bid, cid)
    f.ledger.record(bid, cid, usage=dict(request_id=identity, **counts))
    saved = CapabilityLedger(f.ledger.path).get(bid)["calls"][0]
    assert saved["usage_state"] == state and saved["usage"][0] == dict(request_id=identity, **counts)


def test_repeated_receipts_enrich_same_request_without_erasing_known_values(f):
    bid, cid = new_call(f.ledger)
    identity = f.ledger.request(bid, cid)
    first = dict(input_tokens=100, output_tokens=None)
    f.ledger.record(bid, cid, usage=first)
    f.ledger.record(bid, cid, usage=first)
    f.ledger.record(bid, cid, usage=dict(input_tokens=None, output_tokens=20, cached_input_tokens=0))
    f.ledger.record(bid, cid, usage=dict(input_tokens=None, output_tokens=None))
    call = f.ledger.get(bid)["calls"][0]
    assert call["usage_state"] == "reported" and len(call["usage"]) == 1
    assert call["usage"][0] == dict(request_id=identity, input_tokens=100, output_tokens=20, cached_input_tokens=0)
    assert first == dict(input_tokens=100, output_tokens=None)


def test_two_actual_fallback_requests_with_reused_supplier_id_are_separate(f):
    count = 0
    def parse(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return NS(id="supplier-reused", output=[], output_parsed=None, usage=NS(input_tokens=100, output_tokens=20))
        return sdk_success(**kwargs)
    f.client.responses.parse.side_effect = parse
    f.client.chat.completions.parse.side_effect = lambda **kw: NS(id="supplier-reused", usage=NS(input_tokens=100, output_tokens=20),
        choices=[NS(message=NS(parsed=kw["response_format"].model_validate({"ready": True}), refusal=None))])
    assert run_round(reset=True)
    calls = f.ledger.get(cap._batch_id)["calls"]
    fallback = next(c for c in calls if c["transport_requests"] == 2)
    assert len(fallback["request_ids"]) == len(fallback["usage"]) == 2
    assert len(set(fallback["request_ids"])) == 2 and fallback["usage_state"] == "reported"
    assert sum(row["input_tokens"] for row in fallback["usage"]) == 200
    assert wire_count(f) == 5


def test_real_stream_repeat_and_enrichment_stay_one_receipt(f):
    def stream(**kw):
        text = '{"ready":true,"message":"one two three"}'
        events = [NS(type="response.output_text.delta", delta=text)]
        for counts in [{"input_tokens": 100}, {"input_tokens": 100, "output_tokens": 20}, {"input_tokens": 100}]:
            events.append(NS(type="response.completed", response=NS(id=None, status="completed", usage=NS(**counts),
                output=[NS(content=[NS(type="output_text", text=text)])])))
        result = MagicMock(); result.__enter__.return_value = iter(events)
        return result
    f.client.responses.create.side_effect = stream
    assert run_round(reset=True)
    call = next(c for c in f.ledger.get(cap._batch_id)["calls"] if c["kind"] == "streaming")
    assert call["transport_requests"] == len(call["usage"]) == 1 and call["usage_state"] == "reported"
    assert call["usage"][0]["output_tokens"] == 20


def test_late_receipt_updates_only_original_finished_batch_and_whitelists_fields(f):
    bid, cid = new_call(f.ledger)
    identity = f.ledger.request(bid, cid)
    f.ledger.finish(bid, "finished")
    new_id, _ = new_call(f.ledger)
    before = deepcopy(f.ledger.get(new_id))
    f.ledger.record(bid, cid, usage=dict(request_id=identity, input_tokens=10, output_tokens=2,
                                       prompt="not retained", credential="not retained"), status="returned")
    old = f.ledger.get(bid)
    assert old["status"] == "finished" and old["calls"][0]["usage_state"] == "reported"
    assert "not retained" not in json.dumps(old) and f.ledger.get(new_id) == before


def test_new_table_and_reopen_preserve_existing_session_payload(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE agent_sessions_v2 (session_id TEXT PRIMARY KEY, payload TEXT)")
        db.execute("INSERT INTO agent_sessions_v2 VALUES ('existing', ?)", ('{"messages":["keep"]}',))
    ledger = CapabilityLedger(path)
    bid, cid = new_call(ledger)
    identity = ledger.request(bid, cid)
    ledger.record(bid, cid, usage=dict(request_id=identity, input_tokens=10, output_tokens=2))
    assert CapabilityLedger(path).get(bid) == ledger.get(bid)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM agent_sessions_v2").fetchall() == [("existing", '{"messages":["keep"]}')]


def test_request_accounting_failure_prevents_sdk_send(f, monkeypatch):
    def fail(*args): raise OSError("offline ledger failure")
    monkeypatch.setattr(f.ledger, "request", fail)
    assert run_round(reset=True)
    assert wire_count(f) == 0
    calls = f.ledger.get(cap._batch_id)["calls"]
    assert len(calls) == 3 and all(c["transport_requests"] == 0 and c["usage_state"] == "unavailable" for c in calls)


def test_manual_overlap_does_not_allocate_another_batch_and_finish_remains_single_flight(f, monkeypatch):
    with patch.object(cap.threading, "Thread") as thread:
        cap.start_probe()
        job = thread.call_args.kwargs
        cap.start_probe()
        assert thread.call_count == 1 and len(f.ledger.recent()) == 1
    original = f.ledger.finish
    def finish(*args):
        assert cap._probing
        cap.start_probe()  # Same-thread callback must still see the single-flight guard.
        return original(*args)
    monkeypatch.setattr(f.ledger, "finish", finish)
    job["target"](*job["args"], **job["kwargs"])
    assert not cap._probing and len(f.ledger.recent()) == 1


def test_batch_admission_failure_keeps_previous_state_and_does_not_send(f, monkeypatch):
    for value in f.states.values(): value.update(status="ready", streaming="ready")
    before = deepcopy(cap.snapshot())
    def fail(*args): raise OSError("offline storage unavailable")
    monkeypatch.setattr(f.ledger, "begin", fail)
    with pytest.raises(OSError): cap.start_probe()
    assert wire_count(f) == 0 and not cap._probing and cap.snapshot() == before


def test_existing_configuration_change_uses_reset_trigger(f, monkeypatch):
    keys = iter(["old", "changed", "changed"])
    monkeypatch.setattr(cap, "openai_key", lambda: next(keys))
    ticks = iter([None, None])
    monkeypatch.setattr(cap.time, "sleep", lambda _: next(ticks))
    with patch.object(cap, "start_probe") as start, pytest.raises(StopIteration):
        cap._schedule()
    start.assert_called_once_with(reset=True)
