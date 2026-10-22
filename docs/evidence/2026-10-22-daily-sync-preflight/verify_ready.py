"""Final read-only protection check and rejected-entry proof; no daily SQLite."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from prepare import ROOT, OUT, PRIVATE, ARCHIVE, SUPPORT, DAILY, app_files, sha, stopped, write


def main():
    stopped()
    protection=json.loads((PRIVATE/'source-protection.json').read_text())
    assert {str(p) for p in SUPPORT.rglob('*') if p.is_file()}==set(protection['daily_files'])
    assert all(sha(Path(p))==h for p,h in protection['daily_files'].items())
    assert app_files(DAILY)==protection['app_files']
    assert all(sha(ROOT/p)==h for p,h in protection['configs'].items())
    project_diff=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()
    assert project_diff==protection['project_diff']
    setup=json.loads((ROOT/'docs/evidence/2026-10-22-deletion-sync-repair/setup.json').read_text())
    assert all(sha(ROOT/p)==h for p,h in setup['protected_sources'].items())
    frozen={p:h for p,h in setup['frozen_files'].items() if not any(part.endswith('.app') for part in Path(p).parts)}
    assert all(sha(Path(p))==h for p,h in frozen.items())
    pins=json.loads((OUT/'source-pins.json').read_text())
    assert all(sha(ROOT/p)==h for p,h in pins.items())
    backup_pins=json.loads((PRIVATE/'backup-file-pins.json').read_text())
    assert all(sha(Path(p))==h for p,h in backup_pins.items())
    assert {str(p) for p in ARCHIVE.rglob('*') if p.is_file()}==set(backup_pins)
    authorization_files=[PRIVATE/'operation-authorization.json',PRIVATE/'OPERATION_HOLD',PRIVATE/'activation/authorization.json',PRIVATE/'activation/HOLD']
    authorizations={str(p):sha(p) for p in authorization_files}
    assert json.loads(authorization_files[0].read_text())['status']=='pending'
    assert json.loads(authorization_files[2].read_text())['status']=='pending'
    assert not (PRIVATE/'execution.json').exists()
    assert set(p.name for p in (PRIVATE/'activation').iterdir())=={'authorization.json','HOLD'}
    # Exercise both real entry points with a child audit hook that forbids DB/network.
    program='''import json,runpy,sys
from pathlib import Path
entry=Path(sys.argv[1]);sys.path.insert(0,str(entry.parent));sys.argv=[str(entry),*sys.argv[2:]]
def audit(event,args):
    if event in {'sqlite3.connect','socket.connect'}:raise AssertionError('Unexpected database/network before approval')
sys.addaudithook(audit)
try:runpy.run_path(str(entry),run_name='__main__')
except PermissionError as error:
    assert 'pending explicit approval' in str(error)
    assert 'agent_service.main' not in sys.modules
    print(json.dumps(dict(entry=entry.name,pending_rejected=True,runtime_imported=False)))
else:raise AssertionError('Pending execution was admitted')
'''
    guards=[]
    for name,args in [('apply_prepared.py',['--apply-approved']),('start_service.py',[])]:
        result=subprocess.run([sys.executable,'-c',program,str(OUT/name),*args],capture_output=True,text=True,timeout=20)
        (PRIVATE/(name+'.pending-check.log')).write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stderr
        guards.append(json.loads(result.stdout))
    assert all(sha(Path(p))==h for p,h in authorizations.items())
    assert not (PRIVATE/'execution.json').exists()
    assert set(p.name for p in (PRIVATE/'activation').iterdir())=={'authorization.json','HOLD'}
    ls='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
    dump=subprocess.check_output([ls,'-dump'],text=True)
    identifiers=re.findall(r'^identifier:\s*(.*)$',dump,re.M)
    count=sum(bool(re.search(r'review[-_]?today',i,re.I)) for i in identifiers)
    assert count==1
    stopped()
    assert all(sha(Path(p))==h for p,h in protection['daily_files'].items())
    assert app_files(DAILY)==protection['app_files']
    write(OUT/'ready-result.json',dict(outcome='PASS_PREPARED_NOT_APPLIED',daily_files_unchanged=len(protection['daily_files']),
        other_original_sources_unchanged=len(setup['protected_sources']),existing_frozen_non_app_files_unchanged=len(frozen),
        current_pinned_sources_and_evidence=len(pins),backup_files_verified=len(backup_pins),private_config_files_unchanged=len(protection['configs']),
        daily_app_unchanged=True,project_diff_unchanged=True,registered_app_entries=count,app_and_daily_service_stopped=True,
        actual_entry_guards=guards,both_authorizations_pending=True,both_holds_preserved=True,no_execution_or_quota_created=True,
        actual_model_requests=0,actual_web_operations=0))
    print('PASS: prepared only; daily data/App, old frozen allowances, configurations and project diff unchanged')


if __name__=='__main__':main()
