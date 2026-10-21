"""Clone the closed real v1 preview into a new held native batch. No launch."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT/'docs/evidence/2026-10-21-first-preview-real'
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def main():
    assert not (OUT/'setup.json').exists(), 'Never reset a prepared batch'
    prior = read(PRIOR/'setup.json'); original = Path(prior['directory'])
    assert prior['status'] == 'COMPLETED_FIRST_PREVIEW_PASS_STOP'
    assert (original/'STOP').exists()
    assert read(original/'quota.json')['model_requests'] == 15
    assert read(original/'quota.json')['web_operations'] == 0
    assert not subprocess.run(['pgrep', '-fl', '/ContinuousResumeQA.app/Contents/MacOS/'], capture_output=True, text=True).stdout.strip()
    assert subprocess.run(['lsof', '-nP', f'-iTCP:{prior["port"]}', '-sTCP:LISTEN'], capture_output=True).returncode == 1
    assert all(digest(ROOT/name) == value for name, value in prior['protected_fingerprints'].items())
    pins = read(OUT/'source-pins.json')
    assert all(digest(ROOT/name) == value for name, value in pins.items())
    protection = {name: files(Path(name)) for name in [*prior['protected_runtime_files'], str(original)]}
    prior_app = Path(prior['native_app']); app_before = files(prior_app)
    support = Path(prior['support_dir'])
    assert digest(support/'libReviewTodayContractSupport.dylib') == '6c53af1e33a3567ffd4fba801f93b0e27b583cf301b50842b88c8ba3de43fa21'
    directory = Path(tempfile.mkdtemp(prefix='review-today-preview-save-pending-', dir='/tmp'))
    (directory/'HOLD').write_text('Post-preview save-chain allowance awaits explicit confirmation.\n')
    write(directory/'authorization.json', dict(status='pending', batch_id=str(uuid.uuid4()),
        actual_model_request_limit=32, provider_web_operation_limit=16,
        scope='same-topic update, independent question and return, native save, details/status/progress, durable readback; stop on failed gate or either cap',
        counting='all probes, retries, fallbacks, background and timeouts; no frozen allowance reuse'))
    for item in original.iterdir():
        if item.is_file() and item.name.startswith(('app.store', 'checkpoint.sqlite3')):
            shutil.copy2(item, directory/item.name)
    for name in ('.app_SUPPORT', 'ReviewBackups'):
        if (original/name).is_dir(): shutil.copytree(original/name, directory/name)
    checks = {}
    with sqlite3.connect(directory/'app.store') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        counts = {t: db.execute('select count(*) from '+t).fetchone()[0]
            for t in ('ZKNOWLEDGE', 'ZSOURCE', 'ZAGENTMESSAGE', 'ZLEARNINGTASK', 'ZAGENTRUN', 'ZFSRSSTATE', 'ZAGENTSESSION')}
        assert counts == dict(ZKNOWLEDGE=0, ZSOURCE=0, ZAGENTMESSAGE=6, ZLEARNINGTASK=1, ZAGENTRUN=3, ZFSRSSTATE=0, ZAGENTSESSION=1)
        cursor, raw = db.execute('select ZLASTSESSIONEVENTSEQ,ZCAPTUREOFFERSJSON from ZAGENTSESSION').fetchone()
        native_offer = json.loads(raw)[0]
        checks['native'] = dict(quick_check='ok', counts=counts, cursor=cursor)
    with sqlite3.connect(directory/'checkpoint.sqlite3') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        data = json.loads(db.execute('select payload from agent_sessions_v2 where session_id=?', (prior['session_id'],)).fetchone()[0])
        data['tasks'] = {r['task_id']: r for row in db.execute('select payload from harness_tasks')
            if (r := json.loads(row[0])).get('session_id') == prior['session_id']}
    assert len(data['messages']) == 6 and len(data['runs']) == 3 and len(data['tasks']) == 1
    assert all(r['status'] == 'completed' for r in data['runs'].values())
    assert data['pending'] is None and data['draft'] is None
    offer = next(iter(data['capture_offers'].values()))
    assert offer['version'] == 1 and offer['status'] == 'offered' and not offer['knowledge_ids']
    assert native_offer['id'] == offer['id'] and native_offer['version'] == 1
    assert native_offer['preview_points'] == offer['preview_points'] and len(offer['preview_points']) == 2
    assert native_offer['preview_summary'] == offer['preview_summary']
    task = data['tasks'][data['active_task_id']]
    assert len(task['context']['sources']) == 1
    checks['service'] = dict(messages=6, runs=3, tasks=1, active_task=data['active_task_id'],
        offer_id=offer['id'], version=1, points=2, summary=offer['preview_summary'],
        source_ids=[s['source_id'] for s in task['context']['sources']])
    write(OUT/'starting-state.json', data)
    write(directory/'qa-config.json', dict(session_id=prior['session_id']))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    assert port != 8742
    real, service = ROOT/'agent-service', directory/'owned-project/agent-service'
    (service/'.venv/bin').mkdir(parents=True)
    (service/'.venv/bin/python').symlink_to(real/'.venv/bin/python')
    shutil.copy2(real/'.venv/pyvenv.cfg', service/'.venv/pyvenv.cfg')
    (service/'.venv/lib').symlink_to(real/'.venv/lib', target_is_directory=True)
    (service/'sitecustomize.py').write_text('import os,sys\ntry:\n'+
        f'    sys.path.insert(0, {str(real)!r})\n    sys.path.insert(0, {str(OUT)!r})\n'+
        f'    import bootstrap\n    bootstrap.install({str(directory)!r}, {str(ROOT)!r})\n'+
        "except BaseException as e:\n    print('QA_BOOTSTRAP_FAILED:'+type(e).__name__,flush=True)\n    os._exit(74)\n")
    (directory/'probe').mkdir()
    app = directory/'ContinuousResumeQA.app'; shutil.copytree(prior_app, app)
    entry = (ROOT/'docs/evidence/2026-10-21-first-preview-preflight/NativeFirstPreviewQA.swift').read_text()
    entry = entry.replace(prior['directory'], str(directory)).replace(f'"{prior["port"]}"', f'"{port}"')
    start = entry.index('        precondition(try! context.fetch(FetchDescriptor<Knowledge>())')
    end = entry.index('\n    }\n    var body:', start)
    initialization = ''.join(f'        precondition(try! context.fetch(FetchDescriptor<{model}>()).count == {count})\n'
        for model, count in [('Knowledge',0),('Source',0),('AgentMessage',6),('LearningTask',1),('AgentRun',3),('FsrsState',0)])
    initialization += f'''        let sid = UUID(uuidString: "{prior['session_id']}")!
        let existing = try! context.fetch(FetchDescriptor<AgentSession>())
        precondition(existing.count == 1 && existing[0].id == sid)
        session = existing[0]
        precondition(session.lastSessionEventSeq == {cursor} && session.captureOffersJSON != "[]")'''
    entry = entry[:start]+initialization+entry[end:]
    entry = entry.replace('首次知识预览复验','预览后知识保存链续验').replace('首次预览复验','预览后保存链续验')
    entry = entry.replace('待确认新批 0／20；网页禁用','待确认新批 0／32；网页 0／16').replace('first_preview_fresh_held','preview_save_chain_held')
    target = OUT/'NativePreviewSaveQA.swift'; target.write_text(entry)
    setup = dict(status='PREPARING_HOLD', directory=str(directory), port=port, session_id=prior['session_id'],
        native_app=str(app), support_dir=str(support), model_limit=32, web_limit=16,
        baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        protected_fingerprints=prior['protected_fingerprints'], protected_runtime_files=protection,
        prior_app=str(prior_app), prior_app_files=app_before,
        prior_guard_sha256=digest(ROOT/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),
        project_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest(),
        native_entry_sha256=digest(target), checks=checks,
        copied_real_history=True, copied_old_probe_history=True, reused_ready_state=False,
        actual_new_model_requests=0, actual_new_web_operations=0, native_app_launched=False, service_started=False,
        authorization_confirmed=False, uninterrupted_empty_start_acceptance=False)
    write(OUT/'setup.json', setup)
    flags=['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor',
        '-enable-upcoming-feature','MemberImportVisibility','-I',str(support),'-L',str(support),
        '-lReviewTodayContractSupport','-lFSRS','-Xlinker','-rpath','-Xlinker',str(support)]
    with (OUT/'native-build.log').open('w') as log:
        subprocess.run(flags+[str(target),'-o',str(app/'Contents/MacOS/ContinuousResumeQA')],stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['codesign','--force','--sign','-',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['codesign','--verify','--strict',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
    setup.update(status='PREPARED_HOLD',native_binary_sha256=digest(app/'Contents/MacOS/ContinuousResumeQA'))
    assert all(files(Path(name)) == value for name,value in protection.items())
    assert files(prior_app) == app_before
    assert not any((directory/name).exists() for name in ('quota.json','live-events.jsonl','verified-roles.json'))
    write(OUT/'setup.json',setup)
    print(json.dumps({k:setup[k] for k in ('status','directory','port','session_id','model_limit','web_limit','checks')},ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
