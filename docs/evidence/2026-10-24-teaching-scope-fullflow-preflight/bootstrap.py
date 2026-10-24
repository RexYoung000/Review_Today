"""Reuse the pending/HOLD/STOP and 40/16 entry gate for this new batch."""
from pathlib import Path
_source = Path(__file__).resolve().parents[1] / '2026-10-23-fullflow-preflight/bootstrap.py'
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
