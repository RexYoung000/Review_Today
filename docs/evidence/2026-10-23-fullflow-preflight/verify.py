"""Verify the actual held entries, isolated empty stores and durable archives."""
from contextlib import closing
import os
import re
import shutil
import sqlite3
import sys
import zipfile
from common import *
from prepare import empty_service_counts


def main():
    state=read(OUT/'setup.json');runtime=Path(state['directory']);check_protection(state)
    assert state['status']=='PREPARED_HOLD_ARCHIVED'
    assert read(runtime/'authorization.json')['status']=='pending' and (runtime/'HOLD').is_file()
    assert not Path(state['native_app']).exists() and sha(Path(state['native_zip']))==state['native_zip_sha256']
    assert read(OUT/'preflight-result.json')['outcome']=='PASS' and len(read(OUT/'preflight-result.json')['cases'])==11
    protected=files(runtime)
    program='''import os,runpy,sys
from pathlib import Path
out,runtime,root=map(Path,sys.argv[1:4]);mode=sys.argv[4]
sys.path.insert(0,str(out));os.environ['REVIEW_TODAY_HARNESS_DB']=str(runtime/'checkpoint.sqlite3')
os.environ['REVIEW_TODAY_REVIEW_DB']=str(runtime/'review.sqlite3')
def audit(event,args):
    if event in {'sqlite3.connect','socket.connect'}:raise AssertionError('Runtime before authorization')
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
        (OUT/(mode+'-pending-check.log')).write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stderr
    service=runtime/'owned-project/agent-service'
    result=subprocess.run([str(service/'.venv/bin/python'),'-B','-c',"raise AssertionError('QA main must not run while pending')"],
        cwd=service,env=dict(os.environ,PYTHONPATH=str(service),PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=20)
    (OUT/'owned-interpreter-pending-check.log').write_text(result.stdout+result.stderr)
    assert result.returncode==74 and result.stdout.strip()=='QA_BOOTSTRAP_FAILED:PermissionError'
    assert files(runtime)==protected
    # Consistent read-only inspection of the empty store created by the native CLI.
    with closing(sqlite3.connect((runtime/'app.store').as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['ZKNOWLEDGE','ZSOURCE','ZAGENTMESSAGE','ZLEARNINGTASK','ZAGENTRUN','ZAGENTSESSION','ZFSRSSTATE']}
        assert not any(counts.values())
    service_counts,absent=empty_service_counts(runtime)
    assert absent and service_counts==state['service_starting_counts']
    forbidden=['quota.json','live-events.jsonl','verified-roles.json','native-recheck-events.jsonl']
    assert not any((runtime/n).exists() for n in forbidden)
    assert not subprocess.run(['lsof','-nP','-iTCP:'+str(state['port']),'-sTCP:LISTEN'],capture_output=True).stdout
    # A real separate capture process audits its own DB reads and owned backup writes.
    subprocess.run([sys.executable,'-B',str(OUT/'capture_evidence.py'),'prepared'],check=True)
    capture=read(PRIVATE/'capture-prepared.json');assert capture['actual_members_read']>0
    held_inventory=inventory(runtime);members={p:row['sha256'] for p,row in held_inventory.items() if row['type']=='file'}
    package=DURABLE/'runtime-held.zip'
    assert not package.exists(),'Never overwrite the prepared runtime archive'
    with zipfile.ZipFile(package,'x',zipfile.ZIP_DEFLATED) as z:
        for name in members:z.write(runtime/name,name)
    with zipfile.ZipFile(package) as z:
        assert set(z.namelist())==set(members)
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in members.items())
    write(DURABLE/'runtime-held-manifest.json',dict(runtime=str(runtime),inventory=held_inventory,archive=str(package),
        archive_sha256=sha(package),actual_members_read=len(members),symlinks_recorded_without_dereference=True))
    for name in ['setup.json','plan.json','module-relocation.json','empty-native.json']:shutil.copy2(OUT/name,DURABLE/name)
    write(PRIVATE/'held-file-pins.json',files(runtime))
    identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([LS,'-dump'],text=True),re.M)
    registered=sum(bool(re.search(r'review[-_]?today',v,re.I)) for v in identifiers);assert registered==1
    spotlight=subprocess.check_output(['mdfind',"kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"],text=True).splitlines()
    assert spotlight==[str(DAILY)]
    plan=read(OUT/'plan.json');estimate=plan['startup_estimate']+sum(g.get('estimated_model_requests',0) for g in plan['gates'])
    assert estimate==plan['path_estimate']==31 and estimate+plan['reserve_within_limit']==40
    check_protection(state)
    assert all(sha(Path(p))==h for p,h in state['owned_support_files'].items())
    result=dict(status='READY_PENDING_NEW_40_16',authorization_confirmed=False,actual_model_requests=0,actual_web_operations=0,
        native_empty_counts=counts,service_empty_counts=service_counts,capability_batch_table_not_created=absent,
        pending_actual_bootstrap_restore_owned_interpreter_rejected=True,pending_entries_do_not_import_service_or_open_sqlite_or_connect=True,
        sdk_fake_transport_cases=11,native_compile_sign_and_actual_extract_verified=True,raw_qa_app_removed=True,
        original_module_files_match_verified_durable_265_archive=True,owned_dylib_text_preserved=True,
        durable_runtime_archive=str(package),durable_runtime_sha256=sha(package),actual_durable_members_read=len(members),
        prepared_capture_sha256=capture['sha256'],per_gate_capture_tool_checked_on_actual_empty_runtime=True,
        daily_files_unchanged=len(state['daily_files']),daily_app_unchanged=True,source_config_qa_pins=len(state['protected_fingerprints']),
        frozen_existing_files_unchanged=len(state['frozen_existing_files']),known_missing_old_paths_still_missing=len(state['known_missing_old_paths']),
        historical_gap_not_restored=True,old_allowances_unchanged=True,user_project_diff_unchanged=True,
        registered_entries=registered,spotlight_paths=spotlight,app_and_service_not_started=True,native_window_not_checked=True,
        proposed_limits=dict(model=40,web=16),path_estimate=31,reserve=9,plan_sha256=sha(OUT/'plan.json'))
    write(OUT/'verification.json',result)
    print('READY pending 40/16; 11 offline SDK cases, 3 actual entry rejections, empty stores, durable archive and one entry verified; real requests 0/0.')


if __name__=='__main__':main()
