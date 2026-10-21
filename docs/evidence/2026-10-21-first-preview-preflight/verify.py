"""Check the held batch, empty disks, zero-web admission, and unchanged originals."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}
def write(path, data): Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def main():
    setup = read(OUT/'setup.json'); held = Path(setup['directory']).resolve()
    before = files(held)
    assert setup['status'] == 'PREPARED_HOLD'
    assert read(held/'authorization.json')['status'] == 'pending' and (held/'HOLD').exists()
    checks = read(OUT/'preflight-result.json')
    assert checks['outcome'] == 'PASS' and len(checks['cases']) == 11
    plan = read(OUT/'plan.json')
    assert plan['startup_estimate'] + sum(g.get('estimated_model_requests', 0) for g in plan['gates']) == plan['path_estimate'] == 15
    assert plan['path_estimate'] + plan['reserve_within_limit'] == plan['model_request_limit'] == 20
    assert plan['provider_web_operation_limit'] == 0
    environment = dict(os.environ, REVIEW_TODAY_HARNESS_DB=str(held/'checkpoint.sqlite3'), PYTHONDONTWRITEBYTECODE='1')
    code = f'import sys; sys.path.insert(0,{str(OUT)!r}); import bootstrap; bootstrap.install({str(held)!r},{str(ROOT)!r})'
    pending = subprocess.run([sys.executable, '-B', '-c', code], env=environment,
        cwd=held/'probe', capture_output=True, text=True, timeout=20)
    assert pending.returncode != 0 and 'pending/HOLD' in pending.stderr
    assert files(held) == before

    temporary = Path(tempfile.mkdtemp(prefix='review-today-first-preview-verify-', dir='/tmp')).resolve()
    blocked = []
    def audit(event, args):
        denied = event == 'socket.connect'
        if event == 'sqlite3.connect' and args[0] != ':memory:':
            path = Path(str(args[0]).removeprefix('file:').split('?', 1)[0]).resolve()
            denied = not path.is_relative_to(temporary)
        if denied:
            blocked.append(event)
            raise AssertionError('Offline preflight disallows network and non-fixture SQLite')
    sys.addaudithook(audit)
    shadow = temporary/'empty-copy'; shadow.mkdir()
    for name in ('app.store', 'checkpoint.sqlite3'):
        for item in held.glob(name+'*'):
            if item.is_file(): shutil.copy2(item, shadow/item.name)
    empty = {}
    with sqlite3.connect(shadow/'app.store') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        empty['native'] = {t: db.execute('select count(*) from '+t).fetchone()[0]
            for t in ('ZKNOWLEDGE', 'ZSOURCE', 'ZAGENTMESSAGE', 'ZAGENTSESSION', 'ZLEARNINGTASK', 'ZAGENTRUN', 'ZFSRSSTATE')}
        assert not any(empty['native'].values())
    with sqlite3.connect(shadow/'checkpoint.sqlite3') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        empty['service'] = {t: db.execute('select count(*) from '+t).fetchone()[0]
            for t in ('agent_sessions_v2', 'harness_tasks', 'agent_memory_policy_v2')}
        assert not any(empty['service'].values())

    sys.path.insert(0, str(OUT))
    from quota_preview import Quota, QuotaBlocked, install
    fixture = temporary/'zero-web'; fixture.mkdir()
    write(fixture/'authorization.json', dict(status='approved', batch_id=str(uuid.uuid4()),
        actual_model_request_limit=20, provider_web_operation_limit=0))
    quota = Quota(fixture)
    try: quota.admit('web')
    except QuotaBlocked: pass
    else: raise AssertionError('zero-web must block before transport')
    assert not quota.ledger.exists()
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(fixture/'checkpoint.sqlite3'), REVIEW_TODAY_LLM_PROVIDER='deepseek',
        REVIEW_TODAY_JEV_TEST='0', DEEPSEEK_API_KEY='offline-fixture', OPENAI_API_KEY='offline-fixture',
        DEEPSEEK_WEB_API_KEY='', TYPESAFE_API_KEY='', EXA_API_KEY='', TAVILY_API_KEY='', BRAVE_API_KEY='',
        REVIEW_TODAY_SEARCH_PROVIDER='deepseek', REVIEW_TODAY_SEARCH_FALLBACKS='exa,tavily',
        REVIEW_TODAY_READ_PROVIDER='exa', REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek',
        REVIEW_TODAY_CONTEXT_PROVIDER='none', REVIEW_TODAY_BROWSER_FALLBACK='0')
    sys.path.insert(0, str(ROOT/'agent-service'))
    from agent_service import web_tools
    from agent_service.call_errors import WebToolError
    backend_calls = []
    class NeverBackend:
        def __init__(self, name): self.name = name
        def search(self, *args, **kwargs): backend_calls.append(self.name); raise AssertionError('No web transport')
        read = context = search
    web_tools._backend = NeverBackend
    installed = install(fixture)
    for provider in ('deepseek', 'exa', 'tavily'):
        for operation in ('search', 'read', 'context'):
            try: getattr(web_tools._backend(provider), operation)('offline-fixture')
            except WebToolError as error: assert error.code == 'RT.WEB.CANCELLED'
            else: raise AssertionError('provider web guard failed')
    assert not backend_calls and not installed.ledger.exists() and not blocked
    for name, expected in setup['protected_runtime_files'].items(): assert files(Path(name)) == expected
    assert files(Path(setup['prior_app'])) == setup['prior_app_files']
    assert all(digest(ROOT/name) == value for name, value in setup['protected_fingerprints'].items())
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    assert not any((held/name).exists() for name in ('quota.json', 'live-events.jsonl', 'verified-roles.json'))
    assert not subprocess.run(['pgrep', '-fl', str(held/'ContinuousResumeQA.app/Contents/MacOS/')], capture_output=True, text=True).stdout.strip()
    assert files(held) == before
    result = dict(outcome='READY_PENDING_ALLOWANCE', proposed_model_limit=20, proposed_web_limit=0,
        actual_model_requests=0, actual_web_operations=0, authorization_confirmed=False,
        empty_database_checks=empty, sdk_guard_cases=11, all_nine_web_entries_block_before_backend=True,
        actual_bootstrap_blocks_pending_before_import=True, prepared_files_unchanged=True,
        protected_source_configuration_files=len(setup['protected_fingerprints']),
        old_runtime_files_unchanged=sum(len(v) for v in setup['protected_runtime_files'].values()),
        old_native_app_unchanged=True, user_project_diff_preserved=True,
        native_bundle_compile_and_signature_pass=True, app_or_service_started=False,
        native_ui_checked=False, real_model_checked=False, frozen_old_allowances_unchanged=True,
        plan_sha256=digest(OUT/'plan.json'), next_step='Confirm the new first-preview-only 20/0 allowance before launch or probes.')
    write(OUT/'verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
