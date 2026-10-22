"""Prepare a full, closed real-history clone; never run an App/service/model."""
from contextlib import closing
import hashlib,json,os,plistlib,shutil,socket,sqlite3,subprocess,sys,tempfile,uuid
from pathlib import Path
from urllib.parse import unquote,urlsplit
from common import *

def main():
    assert not (OUT/'setup.json').exists() and not ARCHIVE.exists(),'Never reset a prepared batch'
    stopped();prior=read(PRIOR/'setup.json');old=Path(prior['directory'])
    assert (old/'STOP').exists() and read(old/'quota.json')['model_requests']==25
    assert read(old/'quota.json')['web_operations']==0
    assert not subprocess.run(['lsof','-nP','-iTCP:'+str(prior['port']),'-sTCP:LISTEN'],capture_output=True).stdout
    repair=read(ROOT/'output/learning-recap-repair-2026-10-22/protection-before.json')
    assert all(sha(Path(p))==h for p,h in repair['old_frozen_files'].items())
    assert all(sha(Path(p))==h for p,h in repair['previous_batch_files'].items())
    assert set(files(REAL))<=set(repair['previous_batch_files'])
    fixed=read(ROOT/'docs/evidence/2026-10-22-learning-recap-repair/source-final-pins.json')
    assert all(sha(ROOT/p)==h for p,h in fixed.items())
    changed={p for p,h in prior['protected_fingerprints'].items() if sha(ROOT/p)!=h}
    assert changed=={f'agent-service/agent_service/{n}.py' for n in ['conversation','conversation_prompts','dialogue_routing','goal_continuation','schemas']},changed
    PRIVATE.mkdir(parents=True,mode=0o700);runtime=Path(tempfile.mkdtemp(prefix='review-today-navigation-save-',suffix='.noindex',dir='/tmp')).resolve()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port!=8742 and port!=prior['port']
    def audit(event,args):
        if event=='socket.connect':raise AssertionError('No network in preparation')
        if event=='sqlite3.connect' and args[0]!=':memory:':
            raw=str(args[0]);p=Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).expanduser().resolve()
            assert p.is_relative_to(runtime),'SQLite outside isolated runtime'
    sys.addaudithook(audit)
    batch_id=str(uuid.uuid4());(runtime/'HOLD').write_text('Preparation only; new 32/16 allowance awaits explicit confirmation.\n')
    write(runtime/'authorization.json',dict(status='pending',batch_id=batch_id,actual_model_request_limit=32,provider_web_operation_limit=16,
        scope='Retained decision262 final paired history; new independent question/return review, native save/details/status/progress, explicit next and disk; stop on failure or either cap',
        counting='all startup probes, actual SDK sends, retries, background, fallbacks and timeouts; no old allowance reuse'))
    source=REAL/'disk-final'
    for item in source.iterdir():
        if item.is_file() and item.name.startswith(('app.store','checkpoint.sqlite3')):shutil.copy2(item,runtime/item.name)
    for name in ['.app_SUPPORT','ReviewBackups']:
        if (old/name).is_dir():shutil.copytree(old/name,runtime/name)
    copied_files={str(p.relative_to(source)):sha(p) for p in source.iterdir() if p.is_file()}
    assert all(sha(runtime/p)==h for p,h in copied_files.items())
    with closing(sqlite3.connect(runtime/'checkpoint.sqlite3')) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        row=db.execute('select payload from agent_sessions_v2 where session_id=?',(prior['session_id'],)).fetchone();data=json.loads(row[0])
        data['tasks']={v['task_id']:v for r in db.execute('select payload from harness_tasks') if (v:=json.loads(r[0]))['session_id']==prior['session_id']}
        tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        old_batches=[r[0] for r in db.execute('select batch_id from agent_capability_batches')] if 'agent_capability_batches' in tables else []
    assert len(data['messages'])==12 and len(data['runs'])==6 and len(data['tasks'])==1
    assert all(r['status']=='completed' for r in data['runs'].values()) and data['pending'] is None and data['draft'] is None
    task=data['tasks'][data['active_task_id']];plan=task['context']['learning_plan'];step=plan['steps'][1]
    assert plan['current_step_id']==step['id'] and step['state']=='explained' and len(plan['steps'])>=3
    offer=next(iter(data['capture_offers'].values()));assert offer['version']==3 and offer['status']=='offered' and not offer['knowledge_ids']
    with closing(sqlite3.connect(runtime/'app.store')) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['ZKNOWLEDGE','ZSOURCE','ZAGENTMESSAGE','ZLEARNINGTASK','ZAGENTRUN','ZAGENTSESSION','ZFSRSSTATE']}
        assert counts==dict(ZKNOWLEDGE=0,ZSOURCE=0,ZAGENTMESSAGE=12,ZLEARNINGTASK=1,ZAGENTRUN=6,ZAGENTSESSION=1,ZFSRSSTATE=0)
        cursor,raw=db.execute('select ZLASTSESSIONEVENTSEQ,ZCAPTUREOFFERSJSON from ZAGENTSESSION').fetchone();native_offer=json.loads(raw)[0]
    for key in ['id','version','status','title','preview_points','preview_summary','scope_summary']:
        assert native_offer[key]==offer[key],key
    write(PRIVATE/'starting-state.json',data)
    write(runtime/'qa-config.json',dict(session_id=prior['session_id']))
    real=ROOT/'agent-service';service=runtime/'owned-project/agent-service';(service/'.venv/bin').mkdir(parents=True)
    (service/'.venv/bin/python').symlink_to(real/'.venv/bin/python');shutil.copy2(real/'.venv/pyvenv.cfg',service/'.venv/pyvenv.cfg')
    (service/'.venv/lib').symlink_to(real/'.venv/lib',target_is_directory=True)
    (service/'sitecustomize.py').write_text('import os,sys\ntry:\n'+
        f'    os.environ["REVIEW_TODAY_HARNESS_DB"]={str(runtime/"checkpoint.sqlite3")!r}\n'+
        f'    os.environ["REVIEW_TODAY_REVIEW_DB"]={str(runtime/"review.sqlite3")!r}\n'+
        f'    sys.path.insert(0,{str(real)!r})\n    sys.path.insert(0,{str(OUT)!r})\n    import bootstrap\n    bootstrap.install({str(runtime)!r},{str(ROOT)!r})\n'+
        "except BaseException as e:\n    print('QA_BOOTSTRAP_FAILED:'+type(e).__name__,flush=True)\n    os._exit(74)\n")
    (runtime/'probe').mkdir();support=runtime/'support';support.mkdir()
    for name,value in prior['owned_support_files'].items():
        assert sha(Path(name))==value;shutil.copy2(name,support/Path(name).name)
    entry=(PRIOR/'NativeFreshFullflowQA.swift').read_text().replace(prior['directory'],str(runtime)).replace('"'+str(prior['port'])+'"','"'+str(port)+'"')
    start=entry.index('        precondition(try! context.fetch(FetchDescriptor<Knowledge>())');end=entry.index('\n    }\n    var body:',start)
    initialization=''.join(f'        precondition(try! context.fetch(FetchDescriptor<{model}>()).count == {count})\n' for model,count in [('Knowledge',0),('Source',0),('AgentMessage',12),('LearningTask',1),('AgentRun',6),('FsrsState',0)])
    initialization+=f'''        let sid = UUID(uuidString: "{prior['session_id']}")!
        let existing = try! context.fetch(FetchDescriptor<AgentSession>())
        precondition(existing.count == 1 && existing[0].id == sid)
        session = existing[0]
        precondition(session.lastSessionEventSeq == {cursor} && session.captureOffersJSON != "[]")'''
    entry=entry[:start]+initialization+entry[end:]
    entry=entry.replace('全新连续学习验收','回顾与保存定向续验').replace('待确认新批 0／40','待确认新批 0／32').replace('fresh_fullflow_held','navigation_save_held')
    target=OUT/'NativeNavigationSaveQA.swift';target.write_text(entry)
    app=runtime/'NavigationSaveQA.app';(app/'Contents/MacOS').mkdir(parents=True)
    info=dict(CFBundleExecutable='NavigationSaveQA',CFBundleIdentifier='Rex.Review-Today.ContinuousResume.NativeQA',CFBundleName='Review Today 隔离验收',CFBundlePackageType='APPL',NSPrincipalClass='NSApplication',NSHighResolutionCapable=True,NSAppTransportSecurity=dict(NSAllowsLocalNetworking=True))
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info));shutil.copytree(DAILY/'Contents/Resources',app/'Contents/Resources')
    fingerprints={p:sha(ROOT/p) for p in prior['protected_fingerprints']}
    fingerprints['agent-service/agent_service/learning_navigation.py']=sha(ROOT/'agent-service/agent_service/learning_navigation.py')
    for p in OUT.glob('*.py'):fingerprints[str(p.relative_to(ROOT))]=sha(p)
    for p in [OUT/'plan.json',target,ROOT/'docs/evidence/2026-10-21-learning-save-preflight/preflight.py',ROOT/'docs/evidence/2026-10-21-learning-save-real/bootstrap.py',ROOT/'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift']:
        fingerprints[str(p.relative_to(ROOT))]=sha(p)
    frozen=dict(repair['old_frozen_files']);frozen.update(files(old));frozen.update(files(ROOT/'docs/evidence/2026-10-22-learning-recap-repair'))
    state=dict(status='PREPARING_HOLD',directory=str(runtime),batch_id=batch_id,port=port,session_id=prior['session_id'],native_app=str(app),support_dir=str(support),model_limit=32,web_limit=16,
        baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),protected_fingerprints=fingerprints,
        old_frozen_files=frozen,previous_batch_files=repair['previous_batch_files'],daily_files=files(SUPPORT),daily_app_inventory=app_files(DAILY),
        original_module_files=prior['original_module_files'],original_support_files=prior['owned_support_files'],owned_support_files=files(support),
        project_file_sha256=sha(ROOT/'Review_Today.xcodeproj/project.pbxproj'),prior_guard_sha256=sha(ROOT/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),native_entry_sha256=sha(target),
        original_paired_files=copied_files,starting_counts=counts,starting_cursor=cursor,starting_step_id=step['id'],next_step_id=plan['steps'][2]['id'],offer_id=offer['id'],offer_version=3,
        old_capability_batch_ids=old_batches,copied_real_final_history=True,copied_prior_failure=True,copied_old_probe_history=True,reused_ready_state=False,
        actual_new_model_requests=0,actual_new_web_operations=0,native_app_launched=False,service_started=False,authorization_confirmed=False,uninterrupted_empty_start_acceptance=False)
    write(OUT/'setup.json',state)
    flags=['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility','-I',str(support),'-L',str(support),'-lReviewTodayContractSupport','-lFSRS','-Xlinker','-rpath','-Xlinker',str(support)]
    with (OUT/'native-build.log').open('w') as log:
        subprocess.run(flags+[str(target),'-o',str(app/'Contents/MacOS/NavigationSaveQA')],stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['codesign','--force','--sign','-',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
        reader=ROOT/'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
        subprocess.run(flags+[str(reader),'-o',str(runtime/'native-disk-reader')],stdout=log,stderr=subprocess.STDOUT,check=True)
    home=runtime/'native-home';home.mkdir()
    subprocess.run([str(runtime/'native-disk-reader'),str(runtime)],env=dict(os.environ,CFFIXED_USER_HOME=str(home)),check=True)
    native=read(runtime/'native-disk-read.json');assert len(native['messages'])==12 and len(native['runs'])==6 and len(native['sessions'])==1
    assert native['knowledge_count']==native['source_count']==native['fsrs_count']==0
    assert {m['id']:m['text'] for m in native['messages']}=={m['message_id']:m['content'] for m in data['messages']}
    write(OUT/'native-starting-check.json',dict(messages=12,runs=6,sessions=1,knowledge=0,sources=0,fsrs=0,real_history_content_matched=True,cursor=cursor,offer_id=offer['id'],version=3,points=len(offer['preview_points']),current_step_index=2,paired_original_copied=True))
    ARCHIVE.mkdir(parents=True,mode=0o700);archive=ARCHIVE/'NavigationSaveQA.zip';inventory=app_files(app)
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
    extracted=runtime/'archive-check.noindex';extracted.mkdir();subprocess.run(['ditto','-x','-k',str(archive),str(extracted)],check=True)
    assert app_files(extracted/app.name)==inventory;subprocess.run(['codesign','--verify','--deep','--strict',str(extracted/app.name)],check=True)
    for path in [app,extracted/app.name]:subprocess.run([LS,'-u',str(path)],capture_output=True)
    shutil.rmtree(extracted);shutil.rmtree(app)
    state.update(status='PREPARED_HOLD_ARCHIVED',native_zip=str(archive),native_zip_sha256=sha(archive),native_bundle_inventory=inventory,qa_raw_app_removed=True,archive_extract_and_signature_verified=True)
    write(OUT/'setup.json',state);check_protection(state)
    assert not any((runtime/n).exists() for n in ['quota.json','live-events.jsonl','verified-roles.json','STOP'])
    print(json.dumps({k:state[k] for k in ['status','directory','port','session_id','model_limit','web_limit','starting_counts','starting_step_id','offer_version']},ensure_ascii=False))
if __name__=='__main__':main()
