"""Reuse the established isolated-QA helpers; no service import or data open."""
from pathlib import Path

_source = Path(__file__).resolve().parents[1] / '2026-10-23-fullflow-preflight/common.py'
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
PRIVATE = ROOT / 'output/teaching-scope-fullflow-preflight-2026-10-24'
DURABLE = Path.home() / 'Library/Developer/ReviewTodayEvidence.noindex/2026-10-24-teaching-scope-fullflow'
PRIOR = ROOT / 'docs/evidence/2026-10-24-fullflow-preflight'
