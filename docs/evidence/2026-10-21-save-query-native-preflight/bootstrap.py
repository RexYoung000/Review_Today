"""Install held-batch checks before reusing the existing observing bootstrap."""
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
    import quota_zero_web
    assert quota_zero_web.SOURCE_SHA256 == setup['prior_guard_sha256']
    quota_zero_web.Quota(directory)  # pending/HOLD fails before imports, logs or ledger creation.
    sys.modules['quota'] = quota_zero_web
    source = root / 'docs/evidence/2026-10-21-learning-save-real/bootstrap.py'
    text = source.read_text()
    text = text.replace("evidence = root / 'docs/evidence/2026-10-21-learning-save-real'", 'evidence = Path(__file__).resolve().parent')
    text = text.replace('decision=249', "decision='new-save-query-check'")
    text = text.replace('limits=dict(model=24, web=16)', 'limits=dict(model=12, web=0)')
    module = types.ModuleType('save_query_observer')
    module.__file__ = str(out / 'bootstrap.py')
    exec(compile(text, str(source), 'exec'), module.__dict__)
    module.install(directory, root)
