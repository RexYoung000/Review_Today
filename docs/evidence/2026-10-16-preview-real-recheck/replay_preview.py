"""Read-only reproduction of the actual structured-preview fallback, zero RPC."""
import copy
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def main():
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[name] = ""
    sys.path.insert(0, str(ROOT / "agent-service"))
    with tempfile.TemporaryDirectory(prefix="review-today-preview-diagnosis-", dir="/tmp") as temp:
        os.environ.update(REVIEW_TODAY_HARNESS_DB=str(Path(temp) / "checkpoint.sqlite3"), REVIEW_TODAY_JEV_TEST="0")
        with patch.object(socket.socket, "connect", side_effect=AssertionError("No network in preview diagnosis")):
            from agent_service.capture_preview import grounded_fields
            from agent_service.learning_progress import quote_matches
            from agent_service.schemas import ConversationOutput
            data = json.loads((EVIDENCE / "backend-after.json").read_text())
            setup = json.loads((EVIDENCE / "setup.json").read_text())
            directory = Path(setup["directory"])
            counter_before = (directory / "request-count.json").read_bytes()
            rows = [json.loads(line) for line in (directory / "live-events.jsonl").read_text().splitlines()]
            start = next(r for r in reversed(rows) if r["type"] == "semantic_start" and r.get("schema") == "ConversationOutput")
            output_row = next(r for r in reversed(rows) if r["type"] == "semantic_output" and r.get("schema") == "ConversationOutput")
            output = ConversationOutput.model_validate(output_row["output"])
            output.validate_request(start["input"])
            candidate = start["input"]["capture_candidates"][0]
            update = output.capture_update.model_dump()
            assert len(start["input"]["capture_candidates"]) == 1 and candidate["version"] == update["version"] == 2
            assert all(quote_matches(q, output.message) for q in update["evidence_quotes"])
            offer = next(iter(data["capture_offers"].values()))
            assert offer["version"] == 3 and offer["status"] == "offered" and "preview" not in offer
            texts = [fragment["text"] for fragment in offer["fragments"]]
            items = [*update["preview"]["points"], update["preview"]["summary"]]
            grounding = [dict(item="summary" if i == len(items) - 1 else f"point_{i + 1}",
                text=item["text"], quotes=[dict(quote=q, in_selected_fragments=any(q in t for t in texts))
                    for q in item["evidence_quotes"]]) for i, item in enumerate(items)]
            invalid = [item for item in grounding if any(not q["in_selected_fragments"] for q in item["quotes"])]
            assert len(invalid) == 1 and invalid[0]["item"] == "point_2"
            assert len(invalid[0]["quotes"]) == 2 and all(not q["in_selected_fragments"] for q in invalid[0]["quotes"])
            assert grounded_fields(update["preview"], offer["fragments"]) == {}
            counterfactual = copy.deepcopy(update["preview"])
            # Diagnostic only: identify the culprit without keeping or publishing
            # a pruned preview or proposing silent pruning as product behavior.
            del counterfactual["points"][1]
            remaining = grounded_fields(counterfactual, offer["fragments"])
            assert len(remaining["preview_points"]) == 3 and remaining["preview_summary"]
            assert (directory / "request-count.json").read_bytes() == counter_before
    result = dict(outcome="REPRODUCED_STRUCTURED_PREVIEW_FALLBACK", actual_new_requests=3,
        original_total_requests=23, original_limit=30, diagnostic_new_model_requests=0,
        candidate_count=1, candidate_version=2, published_offer_version=3,
        new_answer_quotes_valid=True, update_request_validation_passed=True,
        generated_preview_points=4, unsupported_items=invalid,
        final_public_preview_fields={}, published_scope_summary=offer["scope_summary"],
        selected_fragment_count=len(texts), grounding=grounding,
        in_memory_counterfactual_without_unsupported_point=remaining,
        persisted_state_modified=False, production_modified=False,
        cause="Two quotes in generated point 2 are from earlier full lecture text, not the selected old fragments or new quotations. Optional preview grounding drops the entire preview after request validation, so the completed update publishes only scope_summary and never reaches the existing repair for this issue.",
        next_scope_proposal="Only for an explicitly returned structured update preview with invalid selected-source references, report the concrete issue through the existing single repair before publication. Preserve source checks, optional/legacy compatibility, explicit save consent and existing repair cap; not yet implemented.")
    (EVIDENCE / "preview-diagnosis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("grounding", "in_memory_counterfactual_without_unsupported_point")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
