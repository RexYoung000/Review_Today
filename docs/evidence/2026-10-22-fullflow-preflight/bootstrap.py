"""New batch only: reject pending/HOLD before imports, sockets or SQLite."""
import hashlib
import json
import os
from pathlib import Path
import sys
import types


def check_approved(directory,root):
    directory,root=Path(directory).resolve(),Path(root).resolve()
    out=Path(__file__).resolve().parent
    setup=json.loads((out/'setup.json').read_text())
    assert directory==Path(setup['directory']).resolve()
    authorization=json.loads((directory/'authorization.json').read_text())
    if authorization.get('status')!='approved' or (directory/'HOLD').exists() or (directory/'STOP').exists():
        raise PermissionError('pending/HOLD/STOP: new full-flow allowance is not active')
    assert (authorization.get('actual_model_request_limit'),authorization.get('provider_web_operation_limit'))==(40,16)
    assert not (directory/'verified-roles.json').exists()
    for name,value in setup['protected_fingerprints'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==value,name
    import quota_40
    quota_40.Quota(directory)  # still no runtime import or ledger before admission
    assert quota_40.SOURCE_SHA256==setup['prior_guard_sha256']
    return setup


def install(directory,root):
    directory,root=Path(directory).resolve(),Path(root).resolve()
    setup=check_approved(directory,root)
    assert Path(os.environ['REVIEW_TODAY_HARNESS_DB']).resolve()==directory/'checkpoint.sqlite3'
    out=Path(__file__).resolve().parent
    import quota_40
    sys.modules['quota']=quota_40
    observer=root/'docs/evidence/2026-10-21-learning-save-real/bootstrap.py'
    source=observer.read_text()
    for old,new in [("evidence = root / 'docs/evidence/2026-10-21-learning-save-real'",'evidence = Path(__file__).resolve().parent'),
                    ('decision=249',"decision='fresh-fullflow-2026-10-22'"),('limits=dict(model=24, web=16)','limits=dict(model=40, web=16)')]:
        assert source.count(old)==1;source=source.replace(old,new)
    module=types.ModuleType('fresh_fullflow_observer');module.__file__=str(out/'bootstrap.py')
    exec(compile(source,str(observer),'exec'),module.__dict__)
    module.install(directory,root)
