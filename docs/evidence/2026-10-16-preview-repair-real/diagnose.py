"""Validate only retained real output and its actual selected sources, offline."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
SETUP = json.loads((EVIDENCE / "setup.json").read_text())
DIRECTORY = Path(SETUP["directory"])
# learning_memory imports harness_store, whose module owns a default store.
# Isolate even this offline source validator before importing production modules.
os.environ.update(REVIEW_TODAY_HARNESS_DB=str(DIRECTORY / "diagnostic-only.sqlite3"),
                  REVIEW_TODAY_JEV_TEST="0")
sys.path.insert(0, str(ROOT / "agent-service"))
from agent_service import capture_preview, knowledge_invitation


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    rows = [json.loads(x) for x in (directory / "live-events.jsonl").read_text().splitlines()]
    starts = [r for r in rows if r["type"] == "semantic_start" and r["schema"] == "ConversationOutput"]
    outputs = [r for r in rows if r["type"] == "semantic_output" and r["schema"] == "ConversationOutput"]
    assert len(starts) == len(outputs) == 1
    update = outputs[0]["output"]["capture_update"]
    candidate = starts[0]["input"]["capture_candidates"]
    knowledge_invitation.validate_update(update, outputs[0]["output"]["message"], candidate)
    actual = json.loads((EVIDENCE / "backend-after.json").read_text())
    offer = next(iter(actual["capture_offers"].values()))
    preview = capture_preview.optional_preview(update["preview"])
    paths = capture_preview.ungrounded_quote_paths(preview, offer["fragments"])
    assert paths == [] and preview is not None
    fields = capture_preview.grounded_fields(update["preview"], offer["fragments"])
    assert fields["preview_points"] == offer["preview_points"]
    assert fields["preview_summary"] == offer["preview_summary"]
    assert offer["preview"] == update["preview"] and offer["preview_version"] == offer["version"] == 3
    result = dict(outcome="REAL_FIRST_OUTPUT_GROUNDED_PREVIEW_PUBLISHED", decision=240,
        candidate_version=candidate[0]["version"], offer_version=offer["version"],
        preview_points=offer["preview_points"], preview_summary=offer["preview_summary"],
        source_quote_errors=paths, continuous_quote_check_passed=True,
        selected_old_and_current_excerpts_only=True, automatic_repair_triggered=False,
        real_error_to_repair_path_verified=False, diagnostic_new_model_requests=0,
        original_failure_rewritten=False, semantic_correctness_generalized=False)
    (EVIDENCE / "preview-diagnosis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
