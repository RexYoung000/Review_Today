"""Check actual pending entrances and frozen real history; no UI or real calls."""
import ast,json,re,subprocess,sys
from pathlib import Path
from common import *
def main():
    state=read(OUT/'setup.json');runtime=Path(state['directory']);stopped()
    assert state['status']=='PREPARED_HOLD_ARCHIVED' and state['baseline_commit']=='8d1679268e99768e002bb5d8babac41a09dd62cc'
    assert read(runtime/'authorization.json')['status']=='pending' and (runtime/'HOLD').is_file()
    assert not Path(state['native_app']).exists() and sha(Path(state['native_zip']))==state['native_zip_sha256']
    protected=files(runtime)
    script='''import os,runpy,sys
from pathlib import Path
out=Path(sys.argv[1]);runtime=Path(sys.argv[2]);root=Path(sys.argv[3]);mode=sys.argv[4]
sys.path.insert(0,str(out));os.environ['REVIEW_TODAY_HARNESS_DB']=str(runtime/'checkpoint.sqlite3');os.environ['REVIEW_TODAY_REVIEW_DB']=str(runtime/'review.sqlite3')
def audit(event,args):
    if event in {'sqlite3.connect','socket.connect'}:raise AssertionError('Runtime touched before authorization')
sys.addaudithook(audit)
try:
    if mode=='bootstrap':
        import bootstrap;bootstrap.install(runtime,root)
    else:runpy.run_path(str(out/'restore_after_approval.py'),run_name='__main__')
except PermissionError as e:
    assert 'pending/HOLD/STOP' in str(e)
    assert 'agent_service.main' not in sys.modules and 'agent_service.openai_client' not in sys.modules
    print('PASS '+mode+' rejected before service imports/SQLite/network/ledger')
else:raise AssertionError('Pending entry admitted')
'''
    for mode in ['bootstrap','restore']:
        r=subprocess.run([sys.executable,'-B','-c',script,str(OUT),str(runtime),str(ROOT),mode],capture_output=True,text=True,timeout=20)
        (OUT/(mode+'-pending-check.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
    # Also exercise the exact owned interpreter/sitecustomize, not just helpers.
    env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(Path.home()),'PYTHONPATH':str(runtime/'owned-project/agent-service'),'PYTHONDONTWRITEBYTECODE':'1'}
    r=subprocess.run([str(runtime/'owned-project/agent-service/.venv/bin/python'),'-B','-c',"raise AssertionError('User code must not execute')"],cwd=runtime,env=env,capture_output=True,text=True,timeout=20)
    (OUT/'owned-interpreter-pending-check.log').write_text(r.stdout+r.stderr)
    assert r.returncode==74 and 'QA_BOOTSTRAP_FAILED:PermissionError' in r.stdout
    assert files(runtime)==protected,'Pending checks changed held files'
    report=read(OUT/'preflight-result.json');assert report['outcome']=='PASS' and len(report['cases'])==11
    check_protection(state)
    assert all(sha(Path(p))==h for p,h in state['owned_support_files'].items())
    assert not any((runtime/n).exists() for n in ['quota.json','live-events.jsonl','verified-roles.json','STOP'])
    assert not subprocess.run(['pgrep','-x','NavigationSaveQA'],capture_output=True).stdout
    assert not subprocess.run(['lsof','-nP','-iTCP:'+str(state['port']),'-sTCP:LISTEN'],capture_output=True).stdout
    identifiers=re.findall(r'^identifier:\s*(.*)$',subprocess.check_output([LS,'-dump'],text=True),re.M)
    registered=sum(bool(re.search(r'review[-_]?today',v,re.I)) for v in identifiers);assert registered==1
    spotlight=subprocess.check_output(['mdfind',"kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"],text=True).splitlines();assert spotlight==[str(DAILY)]
    plan=read(OUT/'plan.json');assert sum(g['estimated_model_requests'] for g in plan['gates'])==plan['path_estimate']==25
    assert plan['path_estimate']+plan['reserve_within_limit']==32
    for p in OUT.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    assert files(runtime)==protected
    write(PRIVATE/'held-file-pins.json',protected)
    result=dict(status='READY_PENDING_NEW_32_16',actual_model_requests=0,actual_web_operations=0,authorization_confirmed=False,
        copied_real_final_paired_history=True,prior_failure_and_current_step2_retained=True,starting_messages=12,starting_runs=6,starting_tasks=1,starting_offer_version=3,starting_cards=0,
        starting_history_native_and_service_matched=True,copied_probe_history_not_ready_state=True,new_probe_batch_must_be_verified_on_real_start=True,
        actual_bootstrap_restore_and_owned_interpreter_reject_pending=True,pending_checked_before_runtime_sqlite_network_ledger=True,
        sdk_fake_transport_cases=11,native_compile_signature_cli_read_and_archive_extract_verified=True,raw_qa_app_removed=True,
        daily_files_unchanged=len(state['daily_files']),daily_app_unchanged=True,original_module_and_support_unchanged=True,
        old_frozen_files_unchanged=len(state['old_frozen_files']),previous_real_batch_files_unchanged=len(state['previous_batch_files']),
        source_config_and_execution_pins=len(state['protected_fingerprints']),project_user_diff_unchanged=True,held_files_unchanged=True,
        registered_entries=registered,spotlight_paths=spotlight,app_and_service_not_started=True,native_window_not_checked=True,
        proposed_model_limit=32,proposed_web_limit=16,path_estimate=25,reserve=7,
        uninterrupted_empty_start_acceptance=False,real_model_navigation_and_save_not_verified=True,plan_sha256=sha(OUT/'plan.json'))
    write(OUT/'verification.json',result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
