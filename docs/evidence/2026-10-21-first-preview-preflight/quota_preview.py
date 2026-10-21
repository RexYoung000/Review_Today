"""Pinned QA guard, narrowed to twenty model requests with zero-web allowed."""
import hashlib
import json
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
_source = _root / 'docs/evidence/2026-10-21-learning-save-preflight/quota.py'
SOURCE_SHA256 = hashlib.sha256(_source.read_bytes()).hexdigest()
assert SOURCE_SHA256 == json.loads((Path(__file__).parent/'source-pins.json').read_text())[str(_source.relative_to(_root))]
_text = _source.read_text()
for _old, _new in (
        ("not 0 < spec['actual_model_request_limit'] <= 24", "not 0 < spec['actual_model_request_limit'] <= 20"),
        ("not 0 < spec['provider_web_operation_limit'] <= 16", "not 0 <= spec['provider_web_operation_limit'] <= 16")):
    assert _text.count(_old) == 1
    _text = _text.replace(_old, _new)
exec(compile(_text, str(_source), 'exec'), globals())
