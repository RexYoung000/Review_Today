"""Pinned eight-request SDK admission checks; new logs, zero real transport."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OLD=ROOT/'docs/evidence/2026-10-22-local-app-preflight'
sys.path.insert(0,str(OLD))
source=OLD/'run_checks.py'
exec(compile(source.read_text(),str(source),'exec'),globals())
