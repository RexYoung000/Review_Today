"""Reuse the pinned actual SDK fixtures with new output paths and fake transport."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / 'docs/evidence/2026-10-22-local-app-preflight'
sys.path.insert(0, str(OLD))
source = OLD / 'probe_checks.py'
# Its ROOT/OUT are computed from this same-depth new entry, so old evidence is immutable.
exec(compile(source.read_text(), str(source), 'exec'), globals())
