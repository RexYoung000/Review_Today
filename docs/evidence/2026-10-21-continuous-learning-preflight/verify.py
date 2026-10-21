"""Verify held bootstrap and frozen plan without model, web, App or service startup."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(path): return {str(p.relative_to(path)): digest(p) for p in Path(path).rglob('*') if p.is_file()}


def main():
    setup = read(OUT / 'setup.json')
    directory = Path(setup['directory']).resolve()
    before = files(directory)
    assert read(directory / 'authorization.json')['status'] == 'pending' and (directory / 'HOLD').exists()
    assert read(OUT / 'preflight-result.json')['outcome'] == 'PASS'
    assert len(read(OUT / 'preflight-result.json')['cases']) == 11
    plan = read(OUT / 'plan.json')
    estimate = plan['startup_estimate'] + sum(g.get('estimated_model_requests', 0) for g in plan['gates'])
    assert estimate == plan['path_estimate'] == 31
    assert estimate + plan['reserve_within_limit'] == plan['model_request_limit'] == 40
    environment = dict(os.environ, REVIEW_TODAY_HARNESS_DB=str(directory / 'checkpoint.sqlite3'), PYTHONDONTWRITEBYTECODE='1')
    code = f'import sys; sys.path.insert(0,{str(OUT)!r}); import bootstrap; bootstrap.install({str(directory)!r},{str(ROOT)!r})'
    result = subprocess.run([sys.executable, '-B', '-c', code], env=environment,
        cwd=directory / 'probe', capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and 'pending/HOLD' in result.stderr
    assert files(directory) == before
    shadow = Path(tempfile.mkdtemp(prefix='review-today-fresh-empty-check-', dir='/tmp'))
    for name in ('app.store', 'checkpoint.sqlite3'):
        for item in directory.glob(name + '*'):
            if item.is_file(): shutil.copy2(item, shadow / item.name)
    checks = {}
    with sqlite3.connect(shadow / 'app.store') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        checks['native'] = {table: db.execute('select count(*) from ' + table).fetchone()[0]
            for table in ('ZKNOWLEDGE', 'ZSOURCE', 'ZAGENTMESSAGE', 'ZAGENTSESSION', 'ZLEARNINGTASK', 'ZAGENTRUN', 'ZFSRSSTATE')}
        assert not any(checks['native'].values())
    with sqlite3.connect(shadow / 'checkpoint.sqlite3') as db:
        assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
        checks['service'] = {table: db.execute('select count(*) from ' + table).fetchone()[0]
            for table in ('agent_sessions_v2', 'harness_tasks', 'agent_memory_policy_v2')}
        assert not any(checks['service'].values())
    for name, expected in setup['protected_runtime_files'].items(): assert files(Path(name)) == expected
    assert files(Path(setup['prior_app'])) == setup['prior_app_files']
    assert all(digest(ROOT / name) == value for name, value in setup['protected_fingerprints'].items())
    assert hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest() == setup['project_diff_sha256']
    assert not any((directory / name).exists() for name in ('quota.json', 'live-events.jsonl', 'verified-roles.json'))
    assert not subprocess.run(['pgrep', '-fl', str(directory / 'ContinuousResumeQA.app/Contents/MacOS/')], capture_output=True, text=True).stdout.strip()
    result = dict(outcome='READY_PENDING_ALLOWANCE', actual_model_requests=0, actual_web_operations=0,
        proposed_model_limit=40, proposed_web_limit=16, authorization_confirmed=False,
        actual_bootstrap_blocks_pending_before_import=True, prepared_files_unchanged=True,
        empty_database_checks=checks, sdk_guard_cases=11, native_bundle_compile_and_signature_pass=True,
        native_ui_checked=False, real_model_checked=False, app_or_service_started=False,
        old_runtime_files_unchanged=sum(len(v) for v in setup['protected_runtime_files'].values()),
        protected_source_configuration_files=len(setup['protected_fingerprints']), user_project_diff_preserved=True,
        plan_sha256=digest(OUT / 'plan.json'), frozen_old_allowances_unchanged=True,
        next_step='Explicit new 40/16 allowance before starting native App or fresh probes; recheck fingerprints first.')
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
