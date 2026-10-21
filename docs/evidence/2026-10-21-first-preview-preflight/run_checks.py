"""Run the pinned SDK/fake-transport cases with the twenty-request ceiling."""
import hashlib
import json
from pathlib import Path
import re

_root = Path(__file__).resolve().parents[3]
_source = _root/'docs/evidence/2026-10-21-learning-save-preflight/preflight.py'
_pins = json.loads((Path(__file__).parent/'source-pins.json').read_text())
assert hashlib.sha256(_source.read_bytes()).hexdigest() == _pins[str(_source.relative_to(_root))]
_text = _source.read_text()
assert _text.count('from quota import Quota, QuotaBlocked, install') == 1
_text = _text.replace('from quota import Quota, QuotaBlocked, install', 'from quota_preview import Quota, QuotaBlocked, install')
_numbers = {'22': '18', '23': '19', '24': '20', '25': '21'}
_text = re.sub(r'\b(22|23|24|25)\b', lambda match: _numbers[match[0]], _text)
exec(compile(_text, str(_source), 'exec'), globals())
