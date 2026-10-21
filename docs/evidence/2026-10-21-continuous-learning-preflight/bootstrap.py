"""Check fresh held-batch authorization before installing prior observation."""
import hashlib
import json
import os
from pathlib import Path
import sys
import types


def install(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    out = Path(__file__).resolve().parent
    setup = json.loads((out / 'setup.json').read_text())
    assert Path(setup['directory']).resolve() == directory
    assert Path(os.environ['REVIEW_TODAY_HARNESS_DB']).resolve() == directory / 'checkpoint.sqlite3'
    assert not (directory / 'verified-roles.json').exists()
    for name, expected in setup['protected_fingerprints'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    import quota_40
    assert quota_40.SOURCE_SHA256 == setup['prior_guard_sha256']
    quota_40.Quota(directory)
    sys.modules['quota'] = quota_40
    source = root / 'docs/evidence/2026-10-21-learning-save-real/bootstrap.py'
    text = source.read_text()
    text = text.replace("evidence = root / 'docs/evidence/2026-10-21-learning-save-real'", 'evidence = Path(__file__).resolve().parent')
    text = text.replace('decision=249', "decision='new-continuous-learning-check'")
    text = text.replace('limits=dict(model=24, web=16)', 'limits=dict(model=40, web=16)')
    module = types.ModuleType('continuous_learning_observer')
    module.__file__ = str(out / 'bootstrap.py')
    exec(compile(text, str(source), 'exec'), module.__dict__)
    module.install(directory, root)
