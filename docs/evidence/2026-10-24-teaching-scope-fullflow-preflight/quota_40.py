"""Reuse the tested forty/sixteen SDK and web admission adapter."""
from pathlib import Path
_source = Path(__file__).resolve().parents[1] / '2026-10-23-fullflow-preflight/quota_40.py'
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
