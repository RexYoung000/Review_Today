"""Reuse signed archive restoration only after this batch's explicit approval."""
from pathlib import Path
_source = Path(__file__).resolve().parents[1] / '2026-10-23-fullflow-preflight/restore_after_approval.py'
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
