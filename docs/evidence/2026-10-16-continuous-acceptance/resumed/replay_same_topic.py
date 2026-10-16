"""Replay only retained real state/model output; no production edits or model calls."""
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def main():
    qa = Path(json.loads((EVIDENCE.parent / "live/setup.json").read_text())["directory"])
    before = (qa / "request-count.json").read_bytes()
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(qa / "checkpoint.sqlite3"), REVIEW_TODAY_JEV_TEST="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service import knowledge_invitation
    from agent_service.learning_progress import quote_matches
    from agent_service.openai_client import ModelCallError
    from agent_service.schemas import ConversationOutput, IntentDecision
    data = json.loads((EVIDENCE / "phase-04-same-topic-result.json").read_text())
    rows = [json.loads(line) for line in (qa / "live-events.jsonl").read_text().splitlines()]
    decision_row = [r for r in rows if r["type"] == "semantic_output" and r.get("schema") == "IntentDecision"][-1]
    decision = IntentDecision.model_validate(decision_row["output"])
    assert decision.intents == ["correction", "reject", "defer"]
    assert len(decision.proposed_actions) == 1
    assert decision.proposed_actions[0].kind == "save" and decision.proposed_actions[0].disposition == "reject"
    run = list(data["runs"].values())[-1]
    assert run["status"] == "retryable_failed" and run["error_code"] == "RT.MODEL.SCHEMA"
    starts = [r for r in rows if r["type"] == "semantic_start" and r.get("schema") == "ConversationOutput"]
    assert len(starts) == 2 and all(r["input"]["capture_candidates"] == [] for r in starts)
    output_row = [r for r in rows if r["type"] == "semantic_output" and r.get("schema") == "ConversationOutput"][-1]
    output = ConversationOutput.model_validate(output_row["output"])
    # Every retained reference is actually empty; this local harness has no
    # memory data and cannot silently accept any nonempty reference.
    references = next(iter(data["capture_offers"].values()))["draft"]["memory_references"]
    assert references == []
    harness = SimpleNamespace(store=SimpleNamespace(memory_valid=lambda refs: refs == []))
    with patch.object(socket.socket, "connect", side_effect=AssertionError("No network in retained-data replay")):
        actual_candidates = knowledge_invitation.candidates(harness, data, run, decision)
        # Diagnostic counterfactual only: remove this real noncommitting action
        # in memory. No persisted state or production function is changed.
        without_noncommitting_action = decision.model_copy(update={"proposed_actions": []})
        eligible = knowledge_invitation.candidates(harness, data, run, without_noncommitting_action)
        assert actual_candidates == [] and len(eligible) == 1
        outcomes = []
        for label, candidates in [("actual_empty_payload", []), ("candidate_only_counterfactual", eligible)]:
            payload = dict(starts[-1]["input"], capture_candidates=candidates)
            try:
                output.validate_request(payload)
            except ModelCallError as exc:
                outcomes.append(dict(case=label, code=exc.code, diagnostic=exc.diagnostic))
            else:
                raise AssertionError("Retained invalid quotations must not be accepted")
        quotes = output.capture_update.evidence_quotes
        quote_grounding = [quote_matches(q.strip(), output.message) for q in quotes]
        assert quote_grounding == [False] * len(quotes)
    assert (qa / "request-count.json").read_bytes() == before
    result = dict(
        result="REPRODUCED_WITH_RETAINED_DATA", new_model_calls=0,
        actual_decision=dict(intents=decision.intents, proposed_actions=[a.model_dump() for a in decision.proposed_actions]),
        actual_model_payload_candidate_counts=[len(r["input"]["capture_candidates"]) for r in starts],
        current_candidate_count=len(actual_candidates), candidate_count_without_reject_action=len(eligible),
        original_offer_identity_version=[dict(id=o["id"], version=o["version"]) for o in eligible],
        returned_update_identity_version=dict(id=output.capture_update.offer_id, version=output.capture_update.version),
        returned_new_quotes_match_current_message=quote_grounding,
        validation=outcomes,
        interpretation="Noncommitting save rejection suppresses otherwise eligible same-topic invitation. Candidate-only change is not proof the retained model output becomes valid; its new-source quotes are also invalid.",
        proposed_scope="Consider keeping editable invitation context for explicit same-topic updates with rejected/deferred saving, preserving explicit save consent, current version, real quote validation, and one repair limit.",
        production_changes=False, remote_revalidation=False,
    )
    (EVIDENCE / "same-topic-replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
