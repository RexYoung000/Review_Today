"""Prepare one fresh, held, archived QA. Never starts an App or model service."""
from contextlib import closing
import os
import plistlib
import shutil
import socket
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from common import *


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


def text_section(path):
    lines=subprocess.check_output(['otool','-s','__TEXT','__text',str(path)],text=True).splitlines()[2:]
    return hashlib.sha256(bytes.fromhex(''.join(''.join(row.split()[1:]) for row in lines))).hexdigest()


def main():
    assert not (OUT/'setup.json').exists() and not DURABLE.exists(),'Never reset an existing QA'
    stopped();PRIVATE.mkdir(mode=0o700);DURABLE.mkdir(parents=True,mode=0o700)
    baseline=read(ROOT/'docs/evidence/2026-10-23-daily-update-preflight/source-pins.json')
    assert all(sha(ROOT/p)==h for p,h in baseline.items())
    assert inventory(DAILY)==read(ROOT/'docs/evidence/2026-10-23-daily-update-preflight/candidate.json')['inventory']
    assert files(SUPPORT)==read(ROOT/'output/daily-update-preflight-2026-10-23/after-source-files.json')
    old=read(ROOT/'docs/evidence/2026-10-22-navigation-save-preflight/setup.json')['old_frozen_files']
    missing=read(ROOT/'docs/evidence/2026-10-22-navigation-save-real/protection.json')['missing_old_files']
    assert {p for p in old if not Path(p).exists()}==set(missing)
    frozen={p:h for p,h in old.items() if p not in missing}
    assert len(frozen)==229 and all(sha(Path(p))==h for p,h in frozen.items())
    for folder in ['2026-10-23-evidence-protection','2026-10-23-title-fallback-repair','2026-10-23-daily-update-preflight']:
        frozen.update(files(ROOT/'docs/evidence'/folder))
    controls=subprocess.check_output(['rg','--files','--hidden','--no-ignore','output','-g','quota.json','-g','STOP','-g','authorization.json','-g','HOLD'],cwd=ROOT,text=True).splitlines()
    frozen.update({str((ROOT/p).resolve()):sha(ROOT/p) for p in controls})
    frozen.update(files(ROOT/'output/daily-update-preflight-2026-10-23/activation'))
    for name in ['2026-10-23-historical-protection/evidence-objects.zip','2026-10-23-historical-protection/manifest.json',
                 '2026-10-23-title-fallback/component-evidence.zip']:
        p=DURABLE.parent/name;frozen[str(p)]=sha(p)
    runtime=Path(tempfile.mkdtemp(prefix='review-today-fresh-fullflow-',suffix='.noindex',dir='/private/tmp')).resolve()
    no_external_runtime(runtime)
    (runtime/'HOLD').write_text('Preparation only; fresh 40/16 allowance is pending explicit confirmation.\n')
    batch,sid=str(uuid.uuid4()),str(uuid.uuid4())
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert port!=8742
    write(runtime/'authorization.json',dict(status='pending',batch_id=batch,actual_model_request_limit=40,provider_web_operation_limit=16,
        scope=read(OUT/'plan.json')['basis'],counting=read(OUT/'plan.json')['counting']))
    write(runtime/'qa-config.json',dict(session_id=sid))
    real=ROOT/'agent-service';service=runtime/'owned-project/agent-service';(service/'.venv/bin').mkdir(parents=True)
    (service/'.venv/bin/python').symlink_to(real/'.venv/bin/python')
    shutil.copy2(real/'.venv/pyvenv.cfg',service/'.venv/pyvenv.cfg');(service/'.venv/lib').symlink_to(real/'.venv/lib',target_is_directory=True)
    (service/'sitecustomize.py').write_text('import os,sys\n_admitted=False\ndef _audit(event,args):\n    if not _admitted and event in {"sqlite3.connect","socket.connect"}:raise PermissionError("QA pending runtime access")\nsys.addaudithook(_audit)\ntry:\n'+
        f'    os.environ["REVIEW_TODAY_HARNESS_DB"]={str(runtime/"checkpoint.sqlite3")!r}\n'+
        f'    os.environ["REVIEW_TODAY_REVIEW_DB"]={str(runtime/"review.sqlite3")!r}\n'+
        f'    sys.path.insert(0,{str(real)!r})\n    sys.path.insert(0,{str(OUT)!r})\n    import bootstrap\n    bootstrap.check_approved({str(runtime)!r},{str(ROOT)!r})\n    _admitted=True\n    bootstrap.install({str(runtime)!r},{str(ROOT)!r})\n'+
        "except BaseException as e:\n    print('QA_BOOTSTRAP_FAILED:'+type(e).__name__,flush=True)\n    os._exit(74)\n")
    (runtime/'probe').mkdir();support=runtime/'support';support.mkdir()
    inputs={str(p):sha(p) for p in MODULE.iterdir() if p.is_file() and p.suffix in {'.dylib','.swiftmodule','.swiftdoc','.swiftsourceinfo'}}
    assert len(inputs)==8
    with zipfile.ZipFile(DURABLE.parent/'2026-10-23-title-fallback/component-evidence.zip') as z:
        for p,h in inputs.items():assert hashlib.sha256(z.read('support/'+Path(p).name)).hexdigest()==h
    for p in inputs:shutil.copy2(p,support/Path(p).name)
    relocation={}
    for name in ['libFSRS.dylib','libReviewTodayContractSupport.dylib']:
        target=support/name;before=text_section(target)
        subprocess.run(['install_name_tool','-id','@rpath/'+name,str(target)],check=True)
        if name.startswith('libReview'):
            subprocess.run(['install_name_tool','-change',str(MODULE/'libFSRS.dylib'),'@rpath/libFSRS.dylib',str(target)],check=True)
        subprocess.run(['codesign','--force','--sign','-',str(target)],check=True)
        assert text_section(target)==before
        loads=subprocess.check_output(['otool','-L',str(target)],text=True)
        assert str(MODULE) not in loads
        relocation[name]=dict(original_sha256=inputs[str(MODULE/name)],owned_sha256=sha(target),text_section_sha256=before,text_section_preserved=True)
    write(OUT/'module-relocation.json',relocation)
    prior=read(PRIOR/'setup.json')
    entry=(PRIOR/'NativeFreshFullflowQA.swift').read_text().replace(prior['directory'],str(runtime)).replace('"'+str(prior['port'])+'"','"'+str(port)+'"').replace(prior['session_id'],sid)
    native=OUT/'NativeFreshFullflowQA.swift';native.write_text(entry)
    assert entry.count(str(runtime))==3 and sid in entry
    app=runtime/'FreshFullflowQA.app';(app/'Contents/MacOS').mkdir(parents=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(CFBundleExecutable='FreshFullflowQA',CFBundleIdentifier='Rex.Review-Today.ContinuousResume.NativeQA',CFBundleName='Review Today 隔离验收',CFBundlePackageType='APPL',NSPrincipalClass='NSApplication',NSHighResolutionCapable=True,NSAppTransportSecurity=dict(NSAllowsLocalNetworking=True))))
    if (DAILY/'Contents/Resources').is_dir():shutil.copytree(DAILY/'Contents/Resources',app/'Contents/Resources')
    pins=dict(baseline)
    for p in list(OUT.glob('*.py'))+[native,OUT/'plan.json']:pins[str(p.relative_to(ROOT))]=sha(p)
    state=dict(status='PREPARING_HOLD',directory=str(runtime),port=port,session_id=sid,batch_id=batch,native_app=str(app),support_dir=str(support),
        model_limit=40,web_limit=16,baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        protected_fingerprints=pins,frozen_existing_files=frozen,known_missing_old_paths=missing,daily_files=files(SUPPORT),daily_app_inventory=inventory(DAILY),
        original_module_files=inputs,project_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest(),
        prior_guard_sha256=sha(ROOT/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),native_entry_sha256=sha(native),
        imported_history=False,imported_cards_or_sources=False,imported_model_outputs=False,reused_ready_state=False,
        actual_new_model_requests=0,actual_new_web_operations=0,native_app_launched=False,service_started=False,authorization_confirmed=False)
    write(OUT/'setup.json',state)
    flags=['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor','-enable-upcoming-feature','MemberImportVisibility','-I',str(support),'-L',str(support),'-lReviewTodayContractSupport','-lFSRS','-Xlinker','-rpath','-Xlinker',str(support)]
    subprocess.run(flags+[str(native),'-o',str(app/'Contents/MacOS/FreshFullflowQA')],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    reader=ROOT/'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
    subprocess.run(flags+[str(reader),'-o',str(runtime/'native-disk-reader')],check=True)
    home=runtime/'native-home';home.mkdir()
    subprocess.run([str(runtime/'native-disk-reader'),str(runtime)],env=dict(os.environ,CFFIXED_USER_HOME=str(home)),check=True)
    empty=read(runtime/'native-disk-read.json')
    assert all(empty[k]==0 for k in ['knowledge_count','source_count','fsrs_count']) and empty['messages']==empty['runs']==empty['sessions']==[]
    write(OUT/'empty-native.json',empty)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(runtime/'checkpoint.sqlite3'),REVIEW_TODAY_REVIEW_DB=str(runtime/'review.sqlite3'),REVIEW_TODAY_JEV_TEST='0')
    sys.path.insert(0,str(real))
    from agent_service.conversation_store import ConversationStore
    ConversationStore()
    counts,absent=empty_service_counts(runtime)
    package=DURABLE/'FreshFullflowQA.zip';app_inventory=inventory(app)
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(package)],check=True)
    check=runtime/'archive-check.noindex';check.mkdir()
    subprocess.run(['ditto','-x','-k',str(package),str(check)],check=True)
    assert inventory(check/app.name)==app_inventory
    subprocess.run(['codesign','--verify','--deep','--strict',str(check/app.name)],check=True)
    subprocess.run([LS,'-u',str(app)],capture_output=True);subprocess.run([LS,'-u',str(check/app.name)],capture_output=True)
    shutil.rmtree(check);shutil.rmtree(app)
    state.update(status='PREPARED_HOLD_ARCHIVED',service_starting_counts=counts,capability_batch_table_not_created=absent,
        native_zip=str(package),native_zip_sha256=sha(package),native_bundle_inventory=app_inventory,
        owned_support_files={str(p):sha(p) for p in support.iterdir() if p.is_file()},raw_qa_app_removed=True,native_extracted_and_verified=True)
    write(OUT/'setup.json',state)
    check_protection(state)
    print('Fresh empty runtime held; current-module QA compiled, signed, extracted/verified and removed; no service/App started.')


if __name__=='__main__':main()
