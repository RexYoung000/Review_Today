"""Reuse held-entry, empty-store, archive and protection verification."""
from pathlib import Path
_source = Path(__file__).resolve().parents[1] / '2026-10-23-fullflow-preflight/verify.py'
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
