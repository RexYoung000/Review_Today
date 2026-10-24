"""Reuse the previously verified isolated-QA component in this new instance."""
from pathlib import Path
_source=Path(__file__).resolve().parents[1]/'2026-10-23-fullflow-preflight/capture_evidence.py'
exec(compile(_source.read_text(),str(_source),'exec'),globals())
