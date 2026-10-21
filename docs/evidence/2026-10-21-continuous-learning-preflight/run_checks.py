"""Run the prior real-SDK fake-transport cases against the forty/sixteen guard."""
from pathlib import Path
import re

_source = Path(__file__).resolve().parents[1] / '2026-10-21-learning-save-preflight/preflight.py'
_text = _source.read_text()
assert _text.count('from quota import Quota, QuotaBlocked, install') == 1
_text = _text.replace('from quota import Quota, QuotaBlocked, install', 'from quota_40 import Quota, QuotaBlocked, install')
# Only boundary numbers change: last two, last one, limit and first rejected call.
_numbers = {'22': '38', '23': '39', '24': '40', '25': '41'}
_text = re.sub(r'\b(22|23|24|25)\b', lambda match: _numbers[match[0]], _text)
exec(compile(_text, str(_source), 'exec'), globals())
