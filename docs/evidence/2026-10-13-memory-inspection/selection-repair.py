"""Compare the real native identities at the service gate; no model request."""
import json
import os
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory(prefix="review-today-memory-selection-repair-") as directory:
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "isolated.sqlite3")
    from agent_service.learning_memory import select_references
    here = Path(__file__).resolve().parent
    native = json.loads((here / "native-fixed.json").read_text())
    baseline = json.loads((here / "native-baseline.json").read_text())
    results = []
    for case in ("different_titles_two_selected_cards", "same_title_two_selected_cards"):
        row = next(r for r in native["cases"] if r["case"] == case)
        old = next(r for r in baseline["cases"] if r["case"] == case)
        assert row["selected_ids"] == old["selected_ids"]
        candidates = [dict(id=value, knowledge_id=value, kind="knowledge_card", content_version=1)
                      for value in row["candidate_ids"]]
        requested = [dict(id=value, relation="contrast") for value in row["selected_ids"]]
        selected = select_references(candidates, requested)
        assert len(selected) == 2 and {value["id"] for value in selected} == set(row["selected_ids"])
        results.append(dict(case=case, baseline_candidate_count=len(old["candidate_ids"]),
                            native_candidate_ids=row["candidate_ids"], requested_ids=row["selected_ids"],
                            accepted_ids=[value["id"] for value in selected]))
    print(json.dumps(dict(kind="offline_selection_repair", real_supplier_requests=0, results=results),
                     ensure_ascii=False, indent=2))
