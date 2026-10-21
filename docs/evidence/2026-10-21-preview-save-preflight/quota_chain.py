"""Pinned QA guard with a proposed model ceiling of thirty-two."""
import hashlib
import json
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
_source = _root/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'
SOURCE_SHA256 = hashlib.sha256(_source.read_bytes()).hexdigest()
assert SOURCE_SHA256 == json.loads((Path(__file__).parent/'source-pins.json').read_text())[str(_source.relative_to(_root))]
_text = _source.read_text()
_old = "not 0 < spec['actual_model_request_limit'] <= 24"
assert _text.count(_old) == 1
exec(compile(_text.replace(_old, "not 0 < spec['actual_model_request_limit'] <= 32"), str(_source), 'exec'), globals())
