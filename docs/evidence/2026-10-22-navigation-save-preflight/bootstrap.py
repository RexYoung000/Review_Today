"""Reject this proposed batch before service imports, SQLite, transport or ledger."""
import hashlib,json,os,sys,types
from pathlib import Path
def check_approved(directory,root):
    directory,root=Path(directory).resolve(),Path(root).resolve();out=Path(__file__).resolve().parent
    setup=json.loads((out/'setup.json').read_text());assert directory==Path(setup['directory']).resolve()
    auth=json.loads((directory/'authorization.json').read_text())
    if auth.get('status')!='approved' or (directory/'HOLD').exists() or (directory/'STOP').exists():
        raise PermissionError('pending/HOLD/STOP: proposed navigation/save allowance is not active')
    assert (auth.get('actual_model_request_limit'),auth.get('provider_web_operation_limit'))==(32,16)
    assert auth['batch_id']==setup['batch_id']
    assert not (directory/'verified-roles.json').exists()
    for name,expected in setup['protected_fingerprints'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
    import quota_chain
    assert quota_chain.SOURCE_SHA256==setup['prior_guard_sha256']
    quota_chain.Quota(directory)
    return setup
def install(directory,root):
    directory,root=Path(directory).resolve(),Path(root).resolve();setup=check_approved(directory,root)
    assert Path(os.environ['REVIEW_TODAY_HARNESS_DB']).resolve()==directory/'checkpoint.sqlite3'
    assert Path(os.environ['REVIEW_TODAY_REVIEW_DB']).resolve()==directory/'review.sqlite3'
    import quota_chain
    sys.modules['quota']=quota_chain
    observer=root/'docs/evidence/2026-10-21-learning-save-real/bootstrap.py';text=observer.read_text()
    for old,new in [("evidence = root / 'docs/evidence/2026-10-21-learning-save-real'",'evidence = Path(__file__).resolve().parent'),('decision=249',"decision='navigation-save-after-263'"),('limits=dict(model=24, web=16)','limits=dict(model=32, web=16)')]:
        assert text.count(old)==1;text=text.replace(old,new)
    module=types.ModuleType('navigation_save_observer');module.__file__=str(Path(__file__).resolve())
    exec(compile(text,str(observer),'exec'),module.__dict__);module.install(directory,root)
