"""Prepare a held, independent native status-query check. Never start a service."""
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
PRIOR = ROOT / 'docs/evidence/2026-10-21-learning-save-real'


def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
def files(path):
    return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}


def main():
    assert not (OUT / 'setup.json').exists(), 'Do not reset a prepared check'
    previous = read(PRIOR / 'setup.json')
    original = Path(previous['directory'])
    original_files = files(original)
    assert (original / 'STOP').exists()
    ledger = read(original / 'quota.json')
    assert (ledger['model_requests'], ledger['web_operations']) == (22, 0)
    expected_changes = {
        'agent-service/agent_service/knowledge_capture_status.py',
        'agent-service/agent_service/conversation.py',
        'agent-service/agent_service/conversation_prompts.py',
        'agent-service/agent_service/schemas.py',
    }
    current = {name: digest(ROOT / name) for name in previous['protected_fingerprints']}
    assert {name for name, value in current.items() if value != previous['protected_fingerprints'][name]} == expected_changes
    assert subprocess.check_output(['git', 'diff', '--name-only', '--', 'agent-service/agent_service', 'Review_Today'], cwd=ROOT, text=True) == ''
    assert not subprocess.run(['pgrep', '-fl', '/ContinuousResumeQA.app/Contents/MacOS/'], capture_output=True, text=True).stdout.strip()
    support = Path(previous['support_dir'])
    assert digest(support / 'libReviewTodayContractSupport.dylib') == previous['support_library_sha256']
    original_app = Path(previous['native_app'])
    original_app_files = files(original_app)
    directory = Path(tempfile.mkdtemp(prefix='review-today-save-query-native-pending-', dir='/tmp'))
    (directory / 'HOLD').write_text('New status-query allowance awaits explicit confirmation.\n')
    write(directory / 'authorization.json', dict(status='pending', batch_id=str(uuid.uuid4()),
        actual_model_request_limit=12, provider_web_operation_limit=0,
        scope='fresh startup probes, one native read-only save-result query, native reply and durable readback; stop on failed gate or cap',
        counting='all probes, retries, fallbacks, background and timeout attempts; do not use frozen old allowance'))
    for item in original.iterdir():
        if item.is_file() and (item.name.startswith(('app.store', 'checkpoint.sqlite3')) or item.name == 'source-checkpoint.json'):
            shutil.copy2(item, directory / item.name)
    checks = {}
    with sqlite3.connect(directory / 'app.store') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        tables = dict(knowledge='ZKNOWLEDGE', source='ZSOURCE', message='ZAGENTMESSAGE',
                      task='ZLEARNINGTASK', run='ZAGENTRUN', fsrs='ZFSRSSTATE')
        counts = {key: db.execute('select count(*) from ' + table).fetchone()[0] for key, table in tables.items()}
        assert counts == dict(knowledge=5, source=1, message=17, task=2, run=9, fsrs=5)
        cursor = db.execute('select ZLASTSESSIONEVENTSEQ from ZAGENTSESSION').fetchone()[0]
        checks['native'] = dict(quick_check='ok', counts=counts, cursor=cursor)
    with sqlite3.connect(directory / 'checkpoint.sqlite3') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        data = json.loads(db.execute('select payload from agent_sessions_v2 where session_id=?', (previous['session_id'],)).fetchone()[0])
        data['tasks'] = {r['task_id']: r for row in db.execute('select payload from harness_tasks')
                         if (r := json.loads(row[0])).get('session_id') == previous['session_id']}
        assert len(data['messages']) == 16 and len(data['runs']) == 9
        assert not any(r['status'] in ('accepted', 'queued', 'running', 'committing') for r in data['runs'].values())
        offer = next(iter(data['capture_offers'].values()))
        assert offer['status'] == 'saved' and offer['version'] == 4 and len(offer['knowledge_ids']) == 5
        expected_cards = data['tasks'][offer['save_task_id']]['memory_package']['knowledge']
        checks['service'] = dict(quick_check='ok', messages=16, runs=9, version=4,
            save_task=offer['save_task_id'], expected_cards=[dict(id=c['id'], title=c['title']) for c in expected_cards])
    write(directory / 'qa-config.json', dict(session_id=previous['session_id']))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    assert port != 8742
    service = directory / 'owned-project/agent-service'
    real = ROOT / 'agent-service'
    (service / '.venv/bin').mkdir(parents=True)
    (service / '.venv/bin/python').symlink_to(real / '.venv/bin/python')
    shutil.copy2(real / '.venv/pyvenv.cfg', service / '.venv/pyvenv.cfg')
    (service / '.venv/lib').symlink_to(real / '.venv/lib', target_is_directory=True)
    (service / 'sitecustomize.py').write_text('import os,sys\ntry:\n' +
        f'    sys.path.insert(0, {str(real)!r})\n    sys.path.insert(0, {str(OUT)!r})\n' +
        f'    import bootstrap\n    bootstrap.install({str(directory)!r}, {str(ROOT)!r})\n' +
        "except BaseException as e:\n    print('QA_BOOTSTRAP_FAILED:'+type(e).__name__,flush=True)\n    os._exit(74)\n")
    (directory / 'probe').mkdir()
    app = directory / 'ContinuousResumeQA.app'
    shutil.copytree(original_app, app)
    entry = (PRIOR / 'NativeLearningSaveQA.swift').read_text()
    entry = entry.replace(previous['directory'], str(directory)).replace(f'"{previous["port"]}"', f'"{port}"')
    start = entry.index('        precondition(try! context.fetch(FetchDescriptor<Knowledge>())')
    end = entry.index('        let sid = ', start)
    assertions = ''.join(f'        precondition(try! context.fetch(FetchDescriptor<{model}>()).count == {counts[key]})\n'
        for model, key in [('Knowledge', 'knowledge'), ('Source', 'source'), ('AgentMessage', 'message'),
                           ('LearningTask', 'task'), ('AgentRun', 'run'), ('FsrsState', 'fsrs')])
    entry = entry[:start] + assertions + entry[end:]
    entry = entry.replace('session.lastSessionEventSeq == 148', f'session.lastSessionEventSeq == {cursor}')
    entry = entry.replace('学习保存真实续验', '保存结果查询复验').replace('新批 0／24；网页 0／16', '待确认新批 0／12；网页禁用')
    entry = entry.replace('record("learning_save_held")', 'record("save_query_held")')
    target = directory / 'NativeSaveQueryQA.swift'
    target.write_text(entry)
    setup = dict(status='PREPARED_HOLD', directory=str(directory), port=port,
        session_id=previous['session_id'], model_limit=12, web_limit=0, checks=checks,
        native_app=str(app), support_dir=str(support), prior_directory=str(original),
        prior_runtime_files=original_files, prior_native_app=str(original_app), prior_app_files=original_app_files,
        baseline_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        protected_fingerprints=current, project_diff_sha256=hashlib.sha256(subprocess.check_output(
            ['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest(),
        prior_guard_sha256=digest(ROOT / 'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),
        frozen_old_model_requests=22, frozen_old_model_remaining=2,
        actual_new_model_requests=0, actual_new_web_operations=0,
        native_entry_sha256=digest(target), native_app_launched=False, service_started=False,
        daily_data_opened=False, authorization_confirmed=False)
    write(OUT / 'setup.json', setup)
    cmd = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
        '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
        '-I', str(support), '-L', str(support), '-lReviewTodayContractSupport', '-lFSRS',
        '-Xlinker', '-rpath', '-Xlinker', str(support), str(target), '-o', str(app / 'Contents/MacOS/ContinuousResumeQA')]
    with (OUT / 'native-build.log').open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(app)], stdout=log, stderr=subprocess.STDOUT, check=True)
    setup['native_binary_sha256'] = digest(app / 'Contents/MacOS/ContinuousResumeQA')
    assert files(original) == original_files and files(original_app) == original_app_files
    assert not (directory / 'quota.json').exists() and not (directory / 'live-events.jsonl').exists()
    write(OUT / 'setup.json', setup)
    print(json.dumps({k: setup[k] for k in ('status', 'directory', 'port', 'model_limit', 'web_limit', 'checks')}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
