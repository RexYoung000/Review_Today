"""Check retained test results and prove daily App/data and frozen batches unchanged."""
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT/'output/deletion-sync-repair-2026-10-22'
def read(path): return json.loads(path.read_text())
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    setup = read(OUT/'setup.json')
    for category in ['protected_sources','daily_files','app_files','frozen_files','source_backup_files']:
        for name,value in setup[category].items():
            path = Path(name) if Path(name).is_absolute() else ROOT/name
            assert digest(path)==value,(category,name)
    assert hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()==setup['project_diff_sha256']
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode==1
    assert subprocess.run(['lsof','-nP','-iTCP:8742','-sTCP:LISTEN'],capture_output=True).returncode==1
    native,service,http = [read(OUT/name) for name in ['native-result.json','service-result.json','http-result.json']]
    assert all(r['outcome']=='PASS' for r in [native,service,http])
    assert len(native['contracts'])==4 and native['deletion_sync_scenarios']==8
    assert digest(Path(native['module'])/'libReviewTodayContractSupport.dylib')==native['shared_module_sha256']
    assert len(http['scenarios'])==6 and all(r['outcome']=='PASS' for r in http['scenarios'])
    real = next(r for r in http['scenarios'] if r['scenario']=='real')
    assert (real['pending_before'],real['pending_after'])==(37,36) and real['unrelated_marker_requests_blocked']>0
    directory = Path(setup['directory'])
    replay = Path(http['directory'])/'real'
    with sqlite3.connect(directory/'app.store') as db:
        original = json.loads(db.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchone()[0])
    with sqlite3.connect(replay/'app.store') as db:
        current = json.loads(db.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchone()[0])
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        counts = {t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['ZKNOWLEDGE','ZAGENTMESSAGE','ZAGENTSESSION','ZFSRSSTATE']}
    assert current[0]['cleaned'] and not original[0]['cleaned'] and current[1:]==original[1:]
    assert {k:v for k,v in current[0].items() if k!='cleaned'}=={k:v for k,v in original[0].items() if k!='cleaned'}
    with sqlite3.connect(replay/'checkpoint.sqlite3') as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert db.execute('select count(*) from agent_session_deletions').fetchone()[0]==1
    assert counts==dict(ZKNOWLEDGE=11,ZAGENTMESSAGE=37,ZAGENTSESSION=8,ZFSRSSTATE=11)
    assert '5 passed' in (PRIVATE/'service-checks.log').read_text()
    assert all('PASS current contract: '+name in (PRIVATE/'native-final.log').read_text() for name in native['contracts'])
    for path in OUT.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
    source = ROOT/'Review_Today/SessionDeletion.swift'
    report = dict(status='IMPLEMENTED_ISOLATED_VERIFIED_DAILY_NOT_UPDATED',decision=258,
        changed_production_files=['Review_Today/SessionDeletion.swift'],production_sha256=digest(source),
        native_contract_groups=4,new_deletion_sync_scenarios=8,service_tests=5,production_http_native_scenarios=6,
        retained_backup_replay=dict(pending_before=37,pending_after=36,only_first_marker_cleared=True,remaining_markers_unchanged=36,
            native_counts=counts,durable_sqlite_readback=True,whole_queue_cleanup_tested=False),
        protected_unchanged={name:len(setup[name]) for name in ['protected_sources','daily_files','app_files','frozen_files','source_backup_files']},
        actual_model_requests=0,actual_web_operations=0,daily_app_started=False,daily_app_updated=False,daily_cleanup=False,
        daily_pending_deletions_untouched=True,old_allowances_reused=False,project_diff_sha256=setup['project_diff_sha256'],
        remaining=['daily loading and actual cleanup not authorized','whole retained queue not accepted','Rex experience and M1 open'])
    (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':main()
