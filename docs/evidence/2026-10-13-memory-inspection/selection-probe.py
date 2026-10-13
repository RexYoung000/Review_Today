"""Replay the native candidate IDs at the service selection gate; no model call."""
import json
import os
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory(prefix="review-today-memory-selection-") as directory:
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "isolated.sqlite3")
    from agent_service.learning_memory import select_references
    native = json.loads(Path(__file__).with_name("native-baseline.json").read_text())
    results = []
    for case in ("different_titles_two_selected_cards", "same_title_two_selected_cards"):
        row = next(r for r in native["cases"] if r["case"] == case)
        # The actual native candidate identities are the relevant gate input.
        # This is not a full captured HTTP payload or a semantic model decision.
        candidates = [dict(id=value, knowledge_id=value, kind="knowledge_card", content_version=1)
                      for value in row["candidate_ids"]]
        requested = [dict(id=value, relation="contrast") for value in row["selected_ids"]]
        selected = select_references(candidates, requested)
        assert len(selected) == (2 if case.startswith("different") else 1)
        results.append(dict(case=case, native_candidate_ids=row["candidate_ids"], requested_ids=row["selected_ids"],
                            accepted_ids=[value["id"] for value in selected]))
    print(json.dumps(dict(kind="offline_selection_gate", real_supplier_requests=0, results=results),
                     ensure_ascii=False, indent=2))
