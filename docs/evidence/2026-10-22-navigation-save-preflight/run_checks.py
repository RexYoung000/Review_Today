"""Reuse eleven SDK/fake-transport admission cases; no external requests."""
import re
from pathlib import Path
_source=Path(__file__).resolve().parents[1]/'2026-10-21-learning-save-preflight/preflight.py'
_text=_source.read_text();assert _text.count('from quota import Quota, QuotaBlocked, install')==1
_text=_text.replace('from quota import Quota, QuotaBlocked, install','from quota_chain import Quota, QuotaBlocked, install')
_numbers={'22':'30','23':'31','24':'32','25':'33'}
_text=re.sub(r'\b(22|23|24|25)\b',lambda m:_numbers[m[0]],_text)
exec(compile(_text,str(_source),'exec'),globals())
