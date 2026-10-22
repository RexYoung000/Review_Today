"""Pinned probe-only and zero-web tests; no sockets or daily database access."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OLD=ROOT/'docs/evidence/2026-10-22-local-app-preflight'
sys.path.insert(0,str(OLD))
source=OLD/'probe_checks.py'
exec(compile(source.read_text(),str(source),'exec'),globals())
