"""Read-only diagnosis after actual save; counter STOP remains in effect.

The comparison removes one old failure notification only in memory, keeping
the actual scope proposal, offer, card IDs and Mac ACK unchanged. It is not
a production fix, provider replay or rewrite of the actual conversation.
"""
import copy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "agent-service"))
from agent_service import knowledge_capture_status as status
from agent_service.topic_capture import source_transparent


def main():
    data = json.loads((EVIDENCE / "phase-06-status-mismatch.json").read_text())
    run = list(data["runs"].values())[-1]
    proposal = run["intent"]["status_context"]
    focus = proposal["focus"][0]
    offer = next(iter(data["capture_offers"].values()))
    original = status.facts(data, status_context=proposal)
    assert original["stage"] == "unorganized"
    assert offer["status"] == "saved"
    assert status._offer_covers_focus(offer, focus)
    message = next(m for m in data["messages"] if m["message_id"] == focus["message_id"])
    assert focus["quote"] in message["content"]
    blockers = []
    for m in data["messages"]:
        r = data["runs"].get(m.get("run_id"), {})
        if (m["role"] == "coach" and not status._is_learning(r) and not source_transparent(r)
                and r.get("capture_offer_id") == offer["id"]):
            blockers.append(m)
    assert len(blockers) == 1
    old = blockers[0]
    comparison = copy.deepcopy(data)
    comparison["messages"] = [m for m in comparison["messages"] if m["message_id"] != old["message_id"]]
    compared = status.facts(comparison, status_context=proposal)
    assert compared["stage"] == "saved"
    assert set(compared["current_knowledge_ids"]) == set(offer["knowledge_ids"])
    assert len(compared["current_knowledge_ids"]) == 4
    result = dict(layer="read_only_actual_checkpoint_comparison", production_changed=False,
                  remote_requests=0, actual_saved_count=4, actual_stage=original["stage"],
                  actual_discussion_sources=original["discussion_sources"], literal_focus_quote=True,
                  offer_covers_focus=True, focus_message_id=focus["message_id"],
                  cleared_by_message_id=old["message_id"], cleared_by_run_id=old["run_id"],
                  cleared_by_text=old["content"], compared_stage=compared["stage"],
                  compared_saved_ids=compared["current_knowledge_ids"],
                  comparison="Exclude old failed-save notification from discussion scan in a copy only; retain all receipt and version evidence",
                  conclusion="Old failed-save result resets the discussion anchor; valid same-scope selection is then rejected and real saved cards are called prior cards.")
    (EVIDENCE / "status-query-baseline.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
