"""Reuse the external audit of the exact owned interpreter entry."""
from pathlib import Path
_source = Path(__file__).resolve().parents[1] / '2026-10-23-fullflow-preflight/pending_source_audit.py'
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
