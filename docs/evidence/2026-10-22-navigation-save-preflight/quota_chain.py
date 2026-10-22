"""Reuse the existing QA adapter with a ceiling of thirty-two; no product edit."""
import hashlib
from pathlib import Path
_source=Path(__file__).resolve().parents[1]/'2026-10-21-learning-save-preflight/quota.py'
SOURCE_SHA256=hashlib.sha256(_source.read_bytes()).hexdigest()
_old="not 0 < spec['actual_model_request_limit'] <= 24"
_text=_source.read_text();assert _text.count(_old)==1
exec(compile(_text.replace(_old,"not 0 < spec['actual_model_request_limit'] <= 32"),str(_source),'exec'),globals())
