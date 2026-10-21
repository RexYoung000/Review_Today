"""Reuse the prior read-only real-session sampler for this batch."""
from pathlib import Path
_source=Path(__file__).resolve().parents[1]/"2026-10-21-continuous-learning-real/observe.py"
exec(compile(_source.read_text(),str(_source),"exec"),globals())
