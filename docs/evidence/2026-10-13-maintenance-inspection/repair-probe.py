"""Replay the inspected boundaries after decision230, keeping old reports intact."""
import importlib.util
import json
from pathlib import Path
import tempfile

# The original probe fences the default database before importing the service.
spec = importlib.util.spec_from_file_location("maintenance_baseline", Path(__file__).with_name("probe.py"))
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)

from pytest import MonkeyPatch
from agent_service import model_capabilities as cap
from agent_service import openai_client as llm
from tests import test_capability_accounting as helpers


def capability(case):
    with tempfile.TemporaryDirectory(prefix="review-today-capability-replay-") as directory, MonkeyPatch.context() as mp:
        f = helpers.f.__wrapped__(Path(directory), mp)
        if case == "transient_and_manual":
            clock = 100_000.0
            mp.setattr(cap.time, "time", lambda: clock)
            f.client.responses.parse.side_effect = llm.ModelCallError("CONNECTION", "offline failure")
            rounds = []
            for index in range(8):
                if not helpers.run_round(reset=index == 0): break
                deadline = cap._next_probe
                rounds.append(dict(round=index+1, retry_scheduled=bool(deadline),
                    delay_seconds=deadline-clock if deadline else None, sdk_requests=helpers.wire_count(f)))
                if deadline: clock = deadline
            exhausted_id = cap._batch_id
            exhausted = f.ledger.get(exhausted_id)
            assert len(rounds) == 4 and helpers.wire_count(f) == 12 and not rounds[-1]["retry_scheduled"]
            assert exhausted["status"] == "exhausted" and len(exhausted["calls"]) == 12
            assert not helpers.run_round()
            f.client.responses.parse.side_effect = helpers.sdk_success
            assert helpers.run_round(reset=True)
            current = f.ledger.get(cap._batch_id)
            assert current["batch_id"] != exhausted_id and f.ledger.get(exhausted_id) == exhausted
            return dict(case="capability_"+case, rounds=rounds, exhausted_batch=exhausted,
                        manual_new_batch=current, old_batch_unchanged=True)
        if case == "deepseek_grouped":
            mp.setattr(cap, "PROVIDER", "deepseek")
            mp.setattr(llm, "PROVIDER", "deepseek")
            for value in f.states.values(): value["model"] = "offline-shared"
        assert helpers.run_round(reset=True)
        current = f.ledger.get(cap._batch_id)
        assert helpers.wire_count(f) == 4 and len(current["calls"]) == 4
        assert all(c["usage_state"] == "reported" and len(c["usage"]) == 1 for c in current["calls"])
        return dict(case="capability_"+case, sdk_requests=helpers.wire_count(f), batch=current)


def main():
    try:
        summaries = [baseline.inspect_summary(case) for case in (
            "success", "usage_missing", "request_failure", "calls_limit", "input_limit", "time_limit", "archive_race", "shared_attempt_limit")]
        capabilities = [capability(case) for case in ("transient_and_manual", "compatible_success", "deepseek_grouped")]
        print(json.dumps(dict(kind="repair_verification", decision=230, date="2026-10-13",
            real_provider_requests=0, summary_case_count=8, capability_case_count=3,
            results=summaries+capabilities), ensure_ascii=False, indent=2))
    finally:
        baseline._isolated.cleanup()


if __name__ == "__main__":
    main()
