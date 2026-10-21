"""Require explicit held-batch approval before production imports or probes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import types


def install(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    out = Path(__file__).resolve().parent
    setup = json.loads((out/'setup.json').read_text())
    assert Path(setup['directory']).resolve() == directory
    assert Path(os.environ['REVIEW_TODAY_HARNESS_DB']).resolve() == directory/'checkpoint.sqlite3'
    assert not (directory/'verified-roles.json').exists()
    for name, expected in setup['protected_fingerprints'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == expected, name
    import quota_preview
    assert quota_preview.SOURCE_SHA256 == setup['prior_guard_sha256']
    quota_preview.Quota(directory)  # HOLD/pending raises before importing service.
    spec = json.loads((directory/'authorization.json').read_text())
    assert (spec['actual_model_request_limit'], spec['provider_web_operation_limit']) == (20, 0)
    sys.modules['quota'] = quota_preview
    source = root/'docs/evidence/2026-10-21-learning-save-real/bootstrap.py'
    pins = json.loads((out/'source-pins.json').read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == pins[str(source.relative_to(root))]
    text = source.read_text()
    for old, new in (
            ("evidence = root / 'docs/evidence/2026-10-21-learning-save-real'", 'evidence = Path(__file__).resolve().parent'),
            ('decision=249', "decision='first-preview-only-pending-check'"),
            ('limits=dict(model=24, web=16)', 'limits=dict(model=20, web=0)')):
        assert text.count(old) == 1
        text = text.replace(old, new)
    module = types.ModuleType('first_preview_observer')
    module.__file__ = str(out/'bootstrap.py')
    exec(compile(text, str(source), 'exec'), module.__dict__)
    module.install(directory, root)
