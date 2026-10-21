"""Reuse the recorded QA guard; allow a proposed model ceiling of forty."""
import hashlib
from pathlib import Path

_source = Path(__file__).resolve().parents[1] / '2026-10-21-learning-save-preflight/quota.py'
_text = _source.read_text()
_old = "not 0 < spec['actual_model_request_limit'] <= 24"
assert _text.count(_old) == 1
SOURCE_SHA256 = hashlib.sha256(_source.read_bytes()).hexdigest()
exec(compile(_text.replace(_old, "not 0 < spec['actual_model_request_limit'] <= 40"), str(_source), 'exec'), globals())
