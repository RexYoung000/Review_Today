"""Final held-entry, empty-data and unchanged-daily checks. No GUI or transport."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from prepare import ROOT, OUT, PRIVATE, SUPPORT, DAILY, LS, read, sha, files, app_files, stopped, write, empty_service_counts


def main():
    stopped();state=read(OUT/'setup.json');runtime=Path(state['directory'])
    assert state['status']=='PREPARED_HOLD_ARCHIVED'
    assert read(runtime/'authorization.json')['status']=='pending' and (runtime/'HOLD').is_file()
    assert not Path(state['native_app']).exists()
    assert sha(Path(state['native_zip']))==state['native_zip_sha256']
    assert read(OUT/'preflight-result.json')['outcome']=='PASS' and len(read(OUT/'preflight-result.json')['cases'])==11
    protected=files(runtime)
    program='''import os,runpy,sys
from pathlib import Path
out=Path(sys.argv[1]);runtime=Path(sys.argv[2]);root=Path(sys.argv[3]);mode=sys.argv[4]
sys.path.insert(0,str(out));os.environ['REVIEW_TODAY_HARNESS_DB']=str(runtime/'checkpoint.sqlite3')
def audit(event,args):
    if event in {'sqlite3.connect','socket.connect'}:raise AssertionError('Runtime accessed before authorization')
sys.addaudithook(audit)
try:
    if mode=='bootstrap':
        import bootstrap;bootstrap.install(runtime,root)
    else:runpy.run_path(str(out/'restore_after_approval.py'),run_name='__main__')
except PermissionError as e:
    assert 'pending/HOLD/STOP' in str(e)
    assert 'agent_service.main' not in sys.modules and 'agent_service.openai_client' not in sys.modules
    print('PASS '+mode+' rejected before runtime/SQLite/network')
else:raise AssertionError('Pending entry admitted')
'''
    for mode in ['bootstrap','restore']:
        result=subprocess.run([sys.executable,'-B','-c',program,str(OUT),str(runtime),str(ROOT),mode],capture_output=True,text=True,timeout=20)
        (PRIVATE/(mode+'-pending-check.log')).write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stderr
    assert files(runtime)==protected
    shadow=Path(tempfile.mkdtemp(prefix='review-today-fullflow-empty-check-',suffix='.noindex',dir='/tmp'))
    for name in ['app.store','checkpoint.sqlite3']:
        for item in runtime.glob(name+'*'):
            if item.is_file():shutil.copy2(item,shadow/item.name)
    with closing(sqlite3.connect((shadow/'app.store').as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['ZKNOWLEDGE','ZSOURCE','ZAGENTMESSAGE','ZLEARNINGTASK','ZAGENTRUN','ZAGENTSESSION','ZFSRSSTATE']}
        assert not any(counts.values())
    service,absent=empty_service_counts(shadow)
    assert absent and service==state['service_starting_counts']
    assert files(SUPPORT)==state['daily_files'] and app_files(DAILY)==state['daily_app_inventory']
    assert all(sha(Path(p))==h for p,h in state['old_frozen_files'].items())
    assert all(sha(ROOT/p)==h for p,h in state['protected_fingerprints'].items())
    assert all(sha(Path(p))==h for p,h in state['original_module_files'].items())
    assert all(sha(Path(p))==h for p,h in state['owned_support_files'].items())
    diff=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()
    assert diff==state['project_diff_sha256']
    forbidden=['quota.json','live-events.jsonl','verified-roles.json','native-recheck-events.jsonl']
    assert not any((runtime/n).exists() for n in forbidden)
    assert files(runtime)==protected
    assert not subprocess.run(['lsof','-nP','-iTCP:'+str(state['port']),'-sTCP:LISTEN'],capture_output=True).stdout
    identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([LS,'-dump'],text=True),re.M)
    registered=sum(bool(re.search(r'review[-_]?today',v,re.I)) for v in identifiers);assert registered==1
    spotlight=subprocess.check_output(['mdfind',"kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"],text=True).splitlines()
    assert spotlight==[str(DAILY)]
    plan=read(OUT/'plan.json');estimate=plan['startup_estimate']+sum(g.get('estimated_model_requests',0) for g in plan['gates'])
    assert estimate==plan['path_estimate']==31 and estimate+plan['reserve_within_limit']==40
    write(PRIVATE/'held-file-pins.json',protected)
    report=dict(status='READY_PENDING_NEW_40_16',actual_model_requests=0,actual_web_operations=0,authorization_confirmed=False,
        native_empty_counts=counts,service_empty_counts=service,capability_batch_table_not_created=absent,
        actual_bootstrap_and_restore_reject_pending_before_runtime=True,held_files_unchanged=True,sdk_fake_transport_cases=11,
        native_compile_sign_and_actual_archive_restore_verified=True,qa_raw_app_removed=True,registered_entries=registered,spotlight_paths=spotlight,
        source_and_configuration_pins=len(state['protected_fingerprints']),old_frozen_files_unchanged=len(state['old_frozen_files']),daily_files_unchanged=len(state['daily_files']),
        daily_app_unchanged=True,original_module_unchanged=True,owned_module_paths_relocated_only=True,project_diff_unchanged=True,
        app_and_service_not_started=True,real_model_not_run=True,native_window_not_checked=True,model_limit_proposed=40,web_limit_proposed=16,
        model_path_estimate=31,reserve_within_proposed_model_limit=9,plan_sha256=sha(OUT/'plan.json'))
    write(OUT/'verification.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
