"""Build a fresh empty, held native acceptance instance. No App or model starts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PREVIOUS = ROOT / 'docs/evidence/2026-10-21-save-query-native-preflight'
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}
def write(path, data): Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    assert not (OUT / 'setup.json').exists(), 'Never reset a prepared batch'
    prior = read(PREVIOUS / 'setup.json')
    assert prior['status'] == 'COMPLETED_PASS_STOP'
    current = {name: digest(ROOT / name) for name in prior['protected_fingerprints']}
    assert current == prior['protected_fingerprints']
    assert not subprocess.run(['pgrep', '-fl', '/ContinuousResumeQA.app/Contents/MacOS/'], capture_output=True, text=True).stdout.strip()
    support = Path(prior['support_dir'])
    earlier = read(ROOT / 'docs/evidence/2026-10-21-learning-save-real/setup.json')
    assert digest(support / 'libReviewTodayContractSupport.dylib') == earlier['support_library_sha256']
    protected = {prior['directory']: files(Path(prior['directory'])),
        earlier['directory']: files(Path(earlier['directory'])),
        earlier['pending_directory']: files(Path(earlier['pending_directory']))}
    for runtime, number in [(Path(prior['directory']), 9), (Path(earlier['directory']), 22)]:
        assert read(runtime / 'quota.json')['model_requests'] == number and (runtime / 'STOP').is_file()
    original_app = Path(prior['native_app'])
    app_before = files(original_app)
    directory = Path(tempfile.mkdtemp(prefix='review-today-continuous-learning-pending-', dir='/tmp'))
    (directory / 'HOLD').write_text('Fresh full-flow allowance awaits explicit confirmation.\n')
    sid = str(uuid.uuid4())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    assert port != 8742
    write(directory / 'qa-config.json', dict(session_id=sid))
    write(directory / 'authorization.json', dict(status='pending', batch_id=str(uuid.uuid4()),
        actual_model_request_limit=40, provider_web_operation_limit=16,
        scope='fresh empty same-session lesson, partial/full answer, same-topic correction, independent question and return, native save, details/status/progress; stop on failed gate or either cap',
        counting='all probes, retries, fallbacks, background and timeouts; no old allowance reuse'))
    real, service = ROOT / 'agent-service', directory / 'owned-project/agent-service'
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
    old = read(ROOT / 'docs/evidence/2026-10-21-learning-save-real/setup.json')
    source = (ROOT / 'docs/evidence/2026-10-21-learning-save-real/NativeLearningSaveQA.swift').read_text()
    source = source.replace(old['directory'], str(directory)).replace(f'"{old["port"]}"', f'"{port}"')
    start = source.index('        precondition(try! context.fetch(FetchDescriptor<Knowledge>())')
    end = source.index('\n    }\n    var body:', start)
    initialization = ''.join(f'        precondition(try! context.fetch(FetchDescriptor<{model}>()).isEmpty)\n'
        for model in ['Knowledge', 'Source', 'AgentMessage', 'LearningTask', 'AgentRun', 'FsrsState', 'AgentSession'])
    initialization += f'''        let sid = UUID(uuidString: "{sid}")!
        session = AgentSession(id: sid, title: "RAG · 全新连续验收", modePreset: "source_learning")
        session.learningChecklistExpanded = true
        context.insert(session)
        try! context.save()'''
    source = source[:start] + initialization + source[end:]
    source = source.replace('学习保存真实续验', '全新连续学习验收').replace('新批 0／24；网页 0／16', '待确认新批 0／40；网页 0／16')
    source = source.replace('record("learning_save_held")', 'record("continuous_fresh_held")')
    entry = OUT / 'NativeFreshContinuousQA.swift'
    entry.write_text(source)
    setup = dict(status='PREPARING_HOLD', directory=str(directory), port=port, session_id=sid,
        native_app=str(app), support_dir=str(support), model_limit=40, web_limit=16,
        baseline_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        protected_fingerprints=current, protected_runtime_files=protected,
        prior_app=str(original_app), prior_app_files=app_before,
        prior_guard_sha256=digest(ROOT / 'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),
        project_diff_sha256=hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest(),
        native_entry_sha256=digest(entry), imported_history=False, imported_cards_or_sources=False,
        imported_model_outputs=False, reused_ready_state=False,
        actual_new_model_requests=0, actual_new_web_operations=0,
        native_app_launched=False, service_started=False, authorization_confirmed=False)
    write(OUT / 'setup.json', setup)
    flags = ['xcrun', 'swiftc', '-parse-as-library', '-D', 'DEBUG', '-swift-version', '5',
        '-default-isolation', 'MainActor', '-enable-upcoming-feature', 'MemberImportVisibility',
        '-I', str(support), '-L', str(support), '-lReviewTodayContractSupport', '-lFSRS',
        '-Xlinker', '-rpath', '-Xlinker', str(support)]
    with (OUT / 'native-build.log').open('w') as log:
        subprocess.run(flags + [str(entry), '-o', str(app / 'Contents/MacOS/ContinuousResumeQA')], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(app)], stdout=log, stderr=subprocess.STDOUT, check=True)
    reader_source = ROOT / 'docs/evidence/2026-10-16-status-native-input/NativeDiskRead.swift'
    with (OUT / 'empty-native.log').open('w') as log:
        subprocess.run(flags + [str(reader_source), '-o', str(directory / 'empty-native-reader')], stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run([str(directory / 'empty-native-reader'), str(directory)], stdout=log, stderr=subprocess.STDOUT, check=True)
    empty = read(directory / 'native-disk-read.json')
    assert all(empty[key] == 0 for key in ('knowledge_count', 'source_count', 'fsrs_count'))
    assert empty['messages'] == empty['runs'] == empty['sessions'] == []
    shutil.copy2(directory / 'native-disk-read.json', OUT / 'empty-native.json')
    # Import storage only, with isolation set before any production imports.
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / 'checkpoint.sqlite3'), REVIEW_TODAY_JEV_TEST='0')
    def audit(event, args):
        if event == 'socket.connect': raise AssertionError('No network during preparation')
        if event == 'sqlite3.connect' and args[0] != ':memory:':
            assert Path(args[0]).resolve().is_relative_to(directory.resolve())
    sys.addaudithook(audit)
    sys.path.insert(0, str(real))
    from agent_service.conversation_store import ConversationStore
    ConversationStore()
    with sqlite3.connect(directory / 'checkpoint.sqlite3') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        counts = {t: db.execute('select count(*) from ' + t).fetchone()[0]
            for t in ('agent_sessions_v2', 'harness_tasks', 'agent_memory_policy_v2')}
        assert not any(counts.values())
    setup.update(status='PREPARED_HOLD', service_starting_counts=counts,
        native_binary_sha256=digest(app / 'Contents/MacOS/ContinuousResumeQA'))
    for name, expected in protected.items(): assert files(Path(name)) == expected
    assert files(original_app) == app_before
    assert (directory / 'HOLD').exists() and not (directory / 'quota.json').exists()
    assert not (directory / 'live-events.jsonl').exists() and not (directory / 'verified-roles.json').exists()
    write(OUT / 'setup.json', setup)
    print(json.dumps({k: setup[k] for k in ('status', 'directory', 'session_id', 'port', 'model_limit', 'web_limit', 'service_starting_counts')}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
