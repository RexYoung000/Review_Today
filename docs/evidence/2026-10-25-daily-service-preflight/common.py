"""Service-only preparation; reuse the established protection and backup helpers."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / "output/daily-service-preflight-2026-10-25"
ARCHIVE = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex/2026-10-25-daily-service"
PREVIOUS = ROOT / "docs/evidence/2026-10-24-teaching-scope-fullflow-preflight"
_spec = importlib.util.spec_from_file_location("prior_271_protection", PREVIOUS / "common.py")
_old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_old)
read, write, sha, files, inventory, stopped = _old.read, _old.write, _old.sha, _old.files, _old.inventory, _old.stopped
DAILY, SUPPORT, LS = _old.DAILY, _old.SUPPORT, _old.LS
DBS = {"Data/ReviewToday.store": "app.store", "agent-harness.sqlite3": "checkpoint.sqlite3",
       "agent-harness.review.sqlite3": "review.sqlite3"}


def unchanged():
    before = read(PREVIOUS / "setup.json")
    _old.check_protection(before)
    assert all(sha(Path(p)) == h for p, h in before["owned_support_files"].items())
    if (OUT / "setup.json").exists():
        state = read(OUT / "setup.json")
        assert all(Path(p).is_file() and sha(Path(p)) == h for p, h in state["prior_evidence_pins"].items())
        assert all(sha(ROOT / p) == h for p, h in state["source_config_pins"].items())


def backup_helpers():
    return _old.helpers.prior_helpers()
