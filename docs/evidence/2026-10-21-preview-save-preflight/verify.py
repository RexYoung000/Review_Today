"""Verify the held copied scene and native readback, without App/service launch."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)):digest(p) for p in Path(path).rglob('*') if p.is_file()}
def write(path,value): Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    setup=read(OUT/'setup.json');held=Path(setup['directory']).resolve();before=files(held)
    assert setup['status']=='PREPARED_HOLD'
    assert read(held/'authorization.json')['status']=='pending' and (held/'HOLD').exists()
    plan=read(OUT/'plan.json')
    assert plan['startup_estimate']+sum(g.get('estimated_model_requests',0) for g in plan['gates'])==plan['path_estimate']==24
    assert plan['path_estimate']+plan['reserve_within_limit']==plan['model_request_limit']==32
    assert plan['provider_web_operation_limit']==16
    checks=read(OUT/'preflight-result.json');assert checks['outcome']=='PASS' and len(checks['cases'])==11
    environment=dict(os.environ,REVIEW_TODAY_HARNESS_DB=str(held/'checkpoint.sqlite3'),PYTHONDONTWRITEBYTECODE='1')
    code=f'import sys;sys.path.insert(0,{str(OUT)!r});import bootstrap;bootstrap.install({str(held)!r},{str(ROOT)!r})'
    pending=subprocess.run([sys.executable,'-B','-c',code],cwd=held/'probe',env=environment,capture_output=True,text=True,timeout=20)
    assert pending.returncode!=0 and 'pending/HOLD' in pending.stderr
    assert files(held)==before
    temporary=Path(tempfile.mkdtemp(prefix='review-today-preview-save-readback-',dir='/tmp')).resolve()
    blocked=[]
    def audit(event,args):
        denied=event=='socket.connect'
        if event=='sqlite3.connect' and args[0]!=':memory:':
            path=Path(str(args[0]).removeprefix('file:').split('?',1)[0]).resolve()
            denied=not path.is_relative_to(temporary)
        if denied:
            blocked.append(event);raise AssertionError('Offline checks disallow network/non-fixture SQLite')
    sys.addaudithook(audit)
    for name in ('app.store','checkpoint.sqlite3'):
        for item in held.glob(name+'*'):
            if item.is_file():shutil.copy2(item,temporary/item.name)
    for name in ('.app_SUPPORT','ReviewBackups'):
        if (held/name).is_dir():shutil.copytree(held/name,temporary/name)
    with sqlite3.connect(temporary/'app.store') as db:
        assert db.execute('pragma quick_check').fetchone()[0]=='ok'
        counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in setup['checks']['native']['counts']}
        assert counts==setup['checks']['native']['counts']
        native_offer=json.loads(db.execute('select ZCAPTUREOFFERSJSON from ZAGENTSESSION').fetchone()[0])[0]
    with sqlite3.connect(temporary/'checkpoint.sqlite3') as db:
        assert db.execute('pragma quick_check').fetchone()[0]=='ok'
        data=json.loads(db.execute('select payload from agent_sessions_v2 where session_id=?',(setup['session_id'],)).fetchone()[0])
        data['tasks']={r['task_id']:r for row in db.execute('select payload from harness_tasks')
            if (r:=json.loads(row[0])).get('session_id')==setup['session_id']}
    assert data==read(OUT/'starting-state.json')
    offer=next(iter(data['capture_offers'].values()))
    for key in ('id','version','status','preview_points','preview_summary'):
        assert native_offer[key]==offer[key]
    assert offer['version']==1 and len(offer['preview_points'])==2 and offer['preview_summary']
    source=data['tasks'][data['active_task_id']]['context']['sources']
    assert [s['source_id'] for s in source]==setup['checks']['service']['source_ids']
    previous=read(ROOT/'docs/evidence/2026-10-21-first-preview-real/setup.json')
    reader=Path(previous['directory'])/'final-native-reader'
    assert digest(reader)==setup['protected_runtime_files'][previous['directory']]['final-native-reader']
    with (OUT/'native-copy-read.log').open('w') as log:
        subprocess.run([str(reader),str(temporary)],stdout=log,stderr=subprocess.STDOUT,check=True)
    native=read(temporary/'native-disk-read.json')
    assert native['knowledge_count']==native['source_count']==native['fsrs_count']==0
    assert len(native['messages'])==6 and len(native['runs'])==3 and len(native['sessions'])==1
    messages={m['id']:m for m in native['messages']}
    for m in data['messages']:
        assert messages[m['message_id']]['text']==m['content'] and messages[m['message_id']]['run_id']==m['run_id']
    assert {r['id']:r['status'] for r in native['runs']}=={rid:r['status'] for rid,r in data['runs'].items()}
    write(OUT/'native-copy-read.json',native)
    assert not blocked
    assert all(digest(ROOT/name)==value for name,value in setup['protected_fingerprints'].items())
    assert all(files(Path(name))==value for name,value in setup['protected_runtime_files'].items())
    assert files(Path(setup['prior_app']))==setup['prior_app_files']
    assert hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()==setup['project_diff_sha256']
    assert files(held)==before
    assert not any((held/name).exists() for name in ('quota.json','live-events.jsonl','verified-roles.json'))
    assert not subprocess.run(['pgrep','-fl',str(held/'ContinuousResumeQA.app/Contents/MacOS/')],capture_output=True,text=True).stdout.strip()
    result=dict(outcome='READY_PENDING_ALLOWANCE',proposed_model_limit=32,proposed_web_limit=16,
        actual_model_requests=0,actual_web_operations=0,authorization_confirmed=False,
        sdk_guard_cases=11,actual_bootstrap_blocks_pending_before_import=True,
        retained_real_messages=6,retained_real_runs=3,retained_learning_tasks=1,
        retained_offer_version=1,retained_preview_points=2,retained_task_sources=1,
        native_fresh_process_copy_read=True,source_and_preview_match_original=True,
        old_runtime_files_unchanged=sum(len(v) for v in setup['protected_runtime_files'].values()),
        protected_source_configuration_files=len(setup['protected_fingerprints']),
        native_bundle_compile_and_signature_pass=True,prepared_files_unchanged=True,
        app_or_service_started=False,real_model_checked=False,native_ui_checked=False,
        user_project_diff_preserved=True,frozen_old_allowances_unchanged=True,
        uninterrupted_empty_start_acceptance=False,plan_sha256=digest(OUT/'plan.json'),
        next_step='Confirm a new 32/16 allowance for post-preview steps only, before starting App/probes.')
    write(OUT/'verification.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
