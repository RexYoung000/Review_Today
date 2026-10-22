"""Reuse eleven actual-SDK/fake-transport checks; zero external requests."""
from pathlib import Path

_checks=Path(__file__).resolve().parents[1]/'2026-10-21-continuous-learning-preflight/run_checks.py'
exec(compile(_checks.read_text(),str(_checks),'exec'),globals())
