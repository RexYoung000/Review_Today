"""Materialize approved independent batch; build paused native entry, no launch."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
def files(directory):
    return {str(p.relative_to(directory)): digest(p) for p in Path(directory).rglob('*') if p.is_file()}


def main():
    assert not (OUT / 'setup.json').exists(), 'Do not reset a batch'
    readiness = read(ROOT / 'docs/evidence/2026-10-21-learning-save-preflight/readiness-refresh.json')
    for name, value in readiness['current_fingerprints'].items(): assert digest(ROOT / name) == value, name
    pending = Path(readiness['prepared_directory'])
    assert (pending / 'HOLD').exists() and read(pending / 'authorization.json')['status'] == 'pending'
    old = Path(readiness['old_EVAL03_directory'])
    assert read(old / 'request-count.json') == dict(actual_requests=30, limit=30) and (old / 'STOP').exists()
    app = Path('/tmp/review-today-startup-diagnosis-1ux5ch6l/ContinuousResumeQA.app')
    assert not subprocess.run(['pgrep', '-fl', '/ContinuousResumeQA.app/Contents/MacOS/'], capture_output=True, text=True).stdout.strip()
    support = Path('/tmp/review-today-shared-contracts.z4pohx24')
    assert digest(support / 'libReviewTodayContractSupport.dylib') == '6c53af1e33a3567ffd4fba801f93b0e27b583cf301b50842b88c8ba3de43fa21'
    directory = Path(tempfile.mkdtemp(prefix='review-today-learning-save-real-', dir='/tmp'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    assert port != 8742
    original_files = files(pending)
    for item in pending.iterdir():
        if item.is_file() and (item.name.startswith(('app.store', 'checkpoint.sqlite3')) or item.name == 'source-checkpoint.json'):
            shutil.copy2(item, directory / item.name)
    shutil.copytree(pending / 'ReviewBackups', directory / 'ReviewBackups')
    source = read(directory / 'source-checkpoint.json')
    sid = source['session_id']
    write(directory / 'qa-config.json', dict(session_id=sid))
    write(directory / 'authorization.json', dict(status='approved', batch_id=str(uuid.uuid4()), decision=249,
        actual_model_request_limit=24, provider_web_operation_limit=16,
        user_confirmation='按 24／16 新上限执行（推荐）', new_batch=True,
        counting='all startup probes, retries, fallback, background and timeouts; conservative pretransport admission',
        scope='separate question, return RAG, native save, detail/status/progress; stop on final gate failure or either cap'))
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
    shutil.copytree(app, directory / 'prior-resume-app')
    prior = read(ROOT / 'docs/evidence/2026-10-17-separate-topic-real/setup.json')
    entry = (ROOT / 'docs/evidence/2026-10-17-separate-topic-real/NativeSeparateTopicQA.swift').read_text()
    entry = entry.replace(prior['directory'], str(directory)).replace(f'"{prior["port"]}"', f'"{port}"')
    entry = entry.replace('独立插问真实复验', '学习保存真实续验').replace('原累计 26／30', '新批 0／24；网页 0／16')
    entry = entry.replace('record("separate_topic_held")', 'record("learning_save_held")')
    target = OUT / 'NativeLearningSaveQA.swift'
    target.write_text(entry)
    binary = app / 'Contents/MacOS/ContinuousResumeQA'
    setup = dict(directory=str(directory), port=port, session_id=sid, decision=249,
        baseline_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        model_limit=24, web_limit=16, new_batch=True, prior_ready_state_reused=False,
        protected_fingerprints=readiness['current_fingerprints'],
        pending_directory=str(pending), pending_files_before=original_files,
        old_EVAL03_directory=str(old), old_EVAL03_sha256={n:digest(old/n) for n in ('STOP','request-count.json')},
        prior_app_files=files(app), native_app=str(app), support_dir=str(support),
        support_library_sha256=digest(support / 'libReviewTodayContractSupport.dylib'),
        project_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest(),
        protected_archives={str(p.relative_to(ROOT)):digest(p) for folder in ('2026-10-17-separate-topic-real','2026-10-21-learning-save-preflight','2026-10-16-preview-repair-real')
                           for p in (ROOT/'docs/evidence'/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts},
        daily_app_process_before=subprocess.run(['pgrep','-fl','/Review_Today.app/Contents/MacOS/Review_Today'],capture_output=True,text=True).stdout,
        native_entry_sha256=digest(target), guard_sha256=digest(ROOT/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'),
        bootstrap_sha256=digest(OUT/'bootstrap.py'))
    write(OUT / 'setup.json', setup)
    cmd = ['xcrun','swiftc','-parse-as-library','-D','DEBUG','-swift-version','5','-default-isolation','MainActor',
        '-enable-upcoming-feature','MemberImportVisibility','-I',str(support),'-L',str(support),
        '-lReviewTodayContractSupport','-lFSRS','-Xlinker','-rpath','-Xlinker',str(support),str(target),'-o',str(binary)]
    with (OUT/'native-build.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['codesign','--force','--sign','-',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['codesign','--verify','--strict',str(app)],stdout=log,stderr=subprocess.STDOUT,check=True)
    setup['native_binary_sha256'] = digest(binary)
    write(OUT/'setup.json',setup)
    assert files(pending)==original_files
    assert not (directory/'quota.json').exists() and not (directory/'live-events.jsonl').exists()
    print(json.dumps({k:setup[k] for k in ('directory','port','session_id','model_limit','web_limit','native_app')},ensure_ascii=False))


if __name__ == '__main__': main()
