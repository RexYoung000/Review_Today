"""Reuse the prior QA guard, with a single bounded zero-web allowance change."""
import hashlib
from pathlib import Path

_source = Path(__file__).resolve().parents[1] / '2026-10-21-learning-save-preflight/quota.py'
_text = _source.read_text()
_old = "not 0 < spec['provider_web_operation_limit'] <= 16"
_new = "not 0 <= spec['provider_web_operation_limit'] <= 16"
assert _text.count(_old) == 1
SOURCE_SHA256 = hashlib.sha256(_source.read_bytes()).hexdigest()
exec(compile(_text.replace(_old, _new), str(_source), 'exec'), globals())
