"""Reuse the actual SDK fake-transport fixtures; only new result paths differ."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "docs/evidence/2026-10-22-local-app-preflight"
sys.path.insert(0, str(OLD))
source = OLD / "probe_checks.py"
exec(compile(source.read_text(), str(source), "exec"), globals())
