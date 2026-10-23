"""Reuse the tested QA-only forty/sixteen admission adapter."""
from pathlib import Path

_adapter=Path(__file__).resolve().parents[1]/'2026-10-21-continuous-learning-preflight/quota_40.py'
exec(compile(_adapter.read_text(),str(_adapter),'exec'),globals())
