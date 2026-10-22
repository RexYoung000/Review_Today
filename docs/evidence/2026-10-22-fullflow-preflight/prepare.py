"""Build and archive an empty held QA instance, with daily/old-batch protection."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/fullflow-preflight-2026-10-22'
DAILY=Path('/Applications/Review Today.app')
SUPPORT=Path.home()/'Library/Application Support/Review Today'
ORIGINAL_MODULE=Path('/tmp/review-today-shared-contracts.j3r_7v6g')
ARCHIVE=Path.home()/'Library/Developer/ReviewTodayAppArchives.noindex/2026-10-22-fullflow'
LS='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def read(path):return json.loads(path.read_text())
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def files(path):return {str(p.resolve()):sha(p) for p in path.rglob('*') if p.is_file()}
def stopped():
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode==1
    assert not subprocess.run(['lsof','-nP','-iTCP:8742','-sTCP:LISTEN'],capture_output=True).stdout
def app_files(path):
    spec=importlib.util.spec_from_file_location('package_inventory',ROOT/'docs/evidence/2026-10-22-daily-sync-preflight/prepare.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.app_files(path)


def empty_service_counts(runtime):
    with closing(sqlite3.connect((runtime/'checkpoint.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('pragma quick_check').fetchall()==[('ok',)]
        tables={t for t, in db.execute("select name from sqlite_master where type='table'")}
        required=['agent_sessions_v2','harness_tasks','agent_memory_policy_v2','agent_session_deletions']
        assert set(required).issubset(tables)
        counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in required}
        counts['agent_capability_batches']=db.execute('select count(*) from agent_capability_batches').fetchone()[0] if 'agent_capability_batches' in tables else 0
        assert not any(counts.values())
        return counts,'agent_capability_batches' not in tables


def complete_held_archive(state):
    """Finish an already built empty preparation; never reset or start a batch."""
    assert state['status']=='PREPARING_HOLD' and not ARCHIVE.exists()
    runtime=Path(state['directory']);app_path=Path(state['native_app']);support=Path(state['support_dir'])
    assert read(runtime/'authorization.json')['status']=='pending' and (runtime/'HOLD').is_file()
    assert not any((runtime/name).exists() for name in ['quota.json','live-events.jsonl','verified-roles.json'])
    assert sha(OUT/'NativeFreshFullflowQA.swift')==state['native_entry_sha256']
    assert all(sha(ROOT/p)==h for p,h in state['protected_fingerprints'].items())
    assert files(SUPPORT)==state['daily_files'] and app_files(DAILY)==state['daily_app_inventory']
    assert all(sha(Path(p))==h for p,h in state['old_frozen_files'].items())
    counts,absent=empty_service_counts(runtime)
    empty=read(runtime/'native-disk-read.json')
    assert all(empty[k]==0 for k in ['knowledge_count','source_count','fsrs_count']) and empty['messages']==empty['runs']==empty['sessions']==[]
    subprocess.run(['codesign','--verify','--deep','--strict',str(app_path)],check=True)
    ARCHIVE.mkdir(parents=True,mode=0o700);archive=ARCHIVE/'FreshFullflowQA.zip';inventory=app_files(app_path)
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app_path),str(archive)],check=True)
    check=runtime/'archive-check.noindex';check.mkdir()
    subprocess.run(['ditto','-x','-k',str(archive),str(check)],check=True)
    assert app_files(check/app_path.name)==inventory
    subprocess.run(['codesign','--verify','--deep','--strict',str(check/app_path.name)],check=True)
    subprocess.run([LS,'-u',str(app_path)],capture_output=True)
    subprocess.run([LS,'-u',str(check/app_path.name)],capture_output=True)
    shutil.rmtree(check);shutil.rmtree(app_path)
    state.update(status='PREPARED_HOLD_ARCHIVED',service_starting_counts=counts,capability_batch_table_not_created=absent,
        native_zip=str(archive),native_zip_sha256=sha(archive),native_bundle_inventory=inventory,
        owned_support_files={str(p):sha(p) for p in support.iterdir() if p.is_file()},raw_qa_app_removed=True,native_extracted_and_verified=True)
    write(OUT/'setup.json',state)
    assert files(SUPPORT)==state['daily_files'] and app_files(DAILY)==state['daily_app_inventory']
    assert all(sha(Path(p))==h for p,h in state['old_frozen_files'].items())
    assert all(sha(Path(p))==h for p,h in state['original_module_files'].items())
    stopped();print('Prepared empty held runtime, signed/re-extracted QA archive; no App/service/model started.',flush=True)


def main():
    assert not (OUT/'setup.json').exists() and not ARCHIVE.exists(),'Never reset an existing batch'
    stopped();PRIVATE.mkdir(parents=True,exist_ok=True);PRIVATE.chmod(0o700)
    previous=read(ROOT/'docs/evidence/2026-10-22-daily-sync-preflight/source-pins.json')
    assert all(sha(ROOT/p)==h for p,h in previous.items())
    assert app_files(DAILY)==read(ROOT/'docs/evidence/2026-10-22-daily-sync-preflight/candidate.json')['inventory']
    assert sha(ORIGINAL_MODULE/'libReviewTodayContractSupport.dylib')=='db4a0a68cdf01bd9582d9ad2ef9f54911d251953bc4fb076506d3b75830aedcd'
    daily=files(SUPPORT);app=app_files(DAILY)
    legacy=read(ROOT/'docs/evidence/2026-10-22-deletion-sync-repair/setup.json')
    frozen={p:sha(Path(p)) for p in legacy['frozen_files'] if not any(x.endswith('.app') for x in Path(p).parts)}
    assert all(frozen[p]==h for p,h in legacy['frozen_files'].items() if p in frozen)
    controls=subprocess.check_output(['rg','--files','--hidden','--no-ignore','output','-g','quota.json','-g','STOP','-g','authorization.json','-g','HOLD'],cwd=ROOT,text=True).splitlines()
    for name in controls:
        path=ROOT/name
        if not path.is_relative_to(PRIVATE):frozen[str(path.resolve())]=sha(path)
    last=ROOT/'output/daily-sync-preflight-2026-10-22/activation'
    assert read(last/'quota.json')['model_requests']==8 and (last/'STOP').is_file()
    frozen.update(files(last))
    runtime=Path(tempfile.mkdtemp(prefix='review-today-fullflow-',suffix='.noindex',dir='/tmp')).resolve()
    (runtime/'HOLD').write_text('Preparation only; new 40/16 allowance awaits explicit confirmation.\n')
    sid=str(uuid.uuid4())
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port!=8742
    write(runtime/'authorization.json',dict(status='pending',batch_id=str(uuid.uuid4()),actual_model_request_limit=40,provider_web_operation_limit=16,
        scope='fresh empty same-session lesson, partial/full answer, preview/update, independent question/return, native save/details/status/progress/disk; stop on failed gate or either cap',
        counting='all startup probes, actual SDK sends, retries, background, fallbacks and timeouts; no old allowance reuse'))
    write(runtime/'qa-config.json',dict(session_id=sid))
    real=ROOT/'agent-service';service=runtime/'owned-project/agent-service'
    (service/'.venv/bin').mkdir(parents=True)
    (service/'.venv/bin/python').symlink_to(real/'.venv/bin/python')
    shutil.copy2(real/'.venv/pyvenv.cfg',service/'.venv/pyvenv.cfg')
    (service/'.venv/lib').symlink_to(real/'.venv/lib',target_is_directory=True)
    (service/'sitecustomize.py').write_text('import os,sys\ntry:\n'+f'    sys.path.insert(0,{str(real)!r})\n    sys.path.insert(0,{str(OUT)!r})\n    import bootstrap\n    bootstrap.install({str(runtime)!r},{str(ROOT)!r})\n'+"except BaseException as e:\n    print('QA_BOOTSTRAP_FAILED:'+type(e).__name__,flush=True)\n    os._exit(74)\n")
    (runtime/'probe').mkdir();support=runtime/'support';support.mkdir()
    module_inputs={str(p):sha(p) for p in ORIGINAL_MODULE.iterdir() if p.is_file() and (p.suffix in {'.dylib','.swiftmodule','.swiftdoc','.swiftsourceinfo'})}
    for path in module_inputs:shutil.copy2(path,support/Path(path).name)
    # Relocate only copied Mach-O load paths; original module bytes stay pinned.
    for library in ['libFSRS.dylib','libReviewTodayContractSupport.dylib']:
        target=support/library
        subprocess.run(['install_name_tool','-id','@rpath/'+library,str(target)],check=True)
        if library.startswith('libReview'):
            subprocess.run(['install_name_tool','-change',str(ORIGINAL_MODULE/'libFSRS.dylib'),'@rpath/libFSRS.dylib',str(target)],check=True)
        subprocess.run(['codesign','--force','--sign','-',str(target)],check=True)
    old=read(ROOT/'docs/evidence/2026-10-21-learning-save-real/setup.json')
    source=(ROOT/'docs/evidence/2026-10-21-learning-save-real/NativeLearningSaveQA.swift').read_text()
    source=source.replace(old['directory'],str(runtime)).replace('"'+str(old['port'])+'"','"'+str(port)+'"')
    start=source.index('        precondition(try! context.fetch(FetchDescriptor<Knowledge>())')
    end=source.index('\n    }\n    var body:',start)
    initialization=''.join(f'        precondition(try! context.fetch(FetchDescriptor<{model}>()).isEmpty)\n' for model in ['Knowledge','Source','AgentMessage','LearningTask','AgentRun','FsrsState','AgentSession'])
    initialization+=f'''        let sid = UUID(uuidString: "{sid}")!
        session = AgentSession(id: sid, title: "RAG · 全新连续验收", modePreset: "source_learning")
        session.learningChecklistExpanded = true
        context.insert(session)
        try! context.save()'''
    source=source[:start]+initialization+source[end:]
    source=source.replace('学习保存真实续验','全新连续学习验收').replace('新批 0／24；网页 0／16','待确认新批 0／40；网页 0／16').replace('record("learning_save_held")','record("fresh_fullflow_held")')
    entry=OUT/'NativeFreshFullflowQA.swift';entry.write_text(source)
    app_path=runtime/'FreshFullflowQA.app';(app_path/'Contents/MacOS').mkdir(parents=True)
    plist=dict(CFBundleExecutable='FreshFullflowQA',CFBundleIdentifier='Rex.Review-Today.ContinuousResume.NativeQA',CFBundleName='Review Today 隔离验收',CFBundlePackageType='APPL',NSPrincipalClass='NSApplication',NSHighResolutionCapable=True,NSAppTransportSecurity=dict(NSAllowsLocalNetworking=True))
    (app_path/'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    if (DAILY/'Contents/Resources').is_dir():shutil.copytree(DAILY/'Contents/Resources',app_path/'Contents/Resources')
    flags=['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility','-I',str(support),'-L',str(support),'-lReviewTodayContractSupport','-lFSRS','-Xlinker','-rpath','-Xlinker',str(support)]
    state=dict(status='PREPARING_HOLD',directory=str(runtime),port=port,session_id=sid,native_app=str(app_path),support_dir=str(support),model_limit=40,web_limit=16,
        baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),protected_fingerprints=previous,
        old_frozen_files=frozen,daily_files=daily,daily_app_inventory=app,original_module_files=module_inputs,
        project_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest(),
        prior_guard_sha256=sha(ROOT/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),native_entry_sha256=sha(entry),
        imported_history=False,imported_cards_or_sources=False,imported_model_outputs=False,reused_ready_state=False,
        actual_new_model_requests=0,actual_new_web_operations=0,native_app_launched=False,service_started=False,authorization_confirmed=False)
    write(OUT/'setup.json',state)
    subprocess.run(flags+[str(entry),'-o',str(app_path/'Contents/MacOS/FreshFullflowQA')],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(app_path)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app_path)],check=True)
    reader=ROOT/'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
    subprocess.run(flags+[str(reader),'-o',str(runtime/'native-disk-reader')],check=True)
    home=runtime/'native-home';home.mkdir()
    subprocess.run([str(runtime/'native-disk-reader'),str(runtime)],env=dict(os.environ,CFFIXED_USER_HOME=str(home)),check=True)
    empty=read(runtime/'native-disk-read.json')
    assert all(empty[k]==0 for k in ['knowledge_count','source_count','fsrs_count']) and empty['messages']==empty['runs']==empty['sessions']==[]
    write(OUT/'empty-native.json',empty)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(runtime/'checkpoint.sqlite3'),REVIEW_TODAY_JEV_TEST='0')
    def audit(event,values):
        if event=='socket.connect':raise RuntimeError('No network in preparation')
        if event=='sqlite3.connect' and values[0]!=':memory:':
            from urllib.parse import urlsplit,unquote
            raw=str(values[0]);path=Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).resolve()
            assert path.is_relative_to(runtime),'Database outside the new isolated runtime'
    sys.addaudithook(audit);sys.path.insert(0,str(real))
    from agent_service.conversation_store import ConversationStore
    ConversationStore()
    complete_held_archive(state)


if __name__=='__main__':main()
