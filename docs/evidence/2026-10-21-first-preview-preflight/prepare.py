"""Reuse the pinned empty native preparer for a held first-preview-only batch."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
source = ROOT / 'docs/evidence/2026-10-21-continuous-learning-preflight/prepare.py'
pins = json.loads((OUT/'source-pins.json').read_text())
for name, digest in pins.items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, name
text = source.read_text()


def replace(old, new):
    global text
    assert text.count(old) == 1, old
    text = text.replace(old, new)


replace("assert current == prior['protected_fingerprints']", """assert {name for name, value in current.items() if value != prior['protected_fingerprints'][name]} == {
        'agent-service/agent_service/capture_preview.py',
        'agent-service/agent_service/conversation_model_call.py',
        'agent-service/agent_service/judgment_grading.py',
        'agent-service/agent_service/schemas.py'}""")
replace("    original_app = Path(prior['native_app'])", """    last = read(ROOT / 'docs/evidence/2026-10-21-continuous-learning-real/setup.json')
    protected[last['directory']] = files(Path(last['directory']))
    ledger = read(Path(last['directory']) / 'quota.json')
    assert ledger['model_requests'] == 15 and ledger['web_operations'] == 0
    assert (Path(last['directory']) / 'STOP').is_file()
    original_app = Path(prior['native_app'])""")
replace("prefix='review-today-continuous-learning-pending-'", "prefix='review-today-first-preview-pending-'")
replace('Fresh full-flow allowance awaits explicit confirmation.', 'First-preview-only allowance awaits explicit confirmation.')
replace('actual_model_request_limit=40, provider_web_operation_limit=16',
        'actual_model_request_limit=20, provider_web_operation_limit=0')
replace('model_limit=40, web_limit=16', 'model_limit=20, web_limit=0')
replace('fresh empty same-session lesson, partial/full answer, same-topic correction, independent question and return, native save, details/status/progress; stop on failed gate or either cap',
        'fresh empty native lesson, partial/full answer, first structured preview and durable readback; no save or web; stop on failed gate or cap')
replace('待确认新批 0／40；网页 0／16', '待确认新批 0／20；网页禁用')
replace('NativeFreshContinuousQA.swift', 'NativeFirstPreviewQA.swift')
text = text.replace('全新连续学习验收', '首次知识预览复验').replace('全新连续验收', '首次预览复验')
text = text.replace('continuous_fresh_held', 'first_preview_fresh_held')
exec(compile(text, str(source), 'exec'), globals())
