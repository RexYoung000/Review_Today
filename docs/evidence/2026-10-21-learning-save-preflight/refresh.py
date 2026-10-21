"""Refresh existing HOLD preparation without importing production or daily DBs."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

from quota import Quota, QuotaBlocked

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    previous = read(ROOT / 'docs/evidence/2026-10-18-learning-save-continuation/readiness.json')
    directory = Path(previous['isolated_checkpoint_prepared']['directory'])
    prepared = {str(p.relative_to(directory)): digest(p) for p in directory.rglob('*') if p.is_file()}
    approval = read(directory / 'authorization.json')
    assert approval['status'] == 'pending' and approval['actual_model_request_limit'] is None
    assert approval['provider_web_operation_limit'] is None and (directory / 'HOLD').is_file()
    try:
        Quota(directory)
    except QuotaBlocked:
        pass
    else:
        raise AssertionError('Actual pending preparation was not blocked')
    assert not (directory / 'quota.json').exists() and not (directory / 'quota.lock').exists()
    source = ROOT / previous['checkpoint']['evidence']
    assert digest(source) == previous['checkpoint']['sha256'] == digest(directory / 'source-checkpoint.json')
    original = read(source)
    task_id = original['active_task_id']
    assert len(original['tasks'][task_id]['context']['sources']) == 1
    offer = next(iter(original['capture_offers'].values()))
    assert offer['version'] == 3 and len(offer['preview_points']) == 4 and offer['preview_summary']

    # Open only expendable copies, including matching WAL/SHM if present.
    scratch = Path(tempfile.mkdtemp(prefix='review-today-learning-save-refresh-', dir='/tmp'))
    checks = {}
    for name in ('app.store', 'checkpoint.sqlite3'):
        for suffix in ('', '-wal', '-shm'):
            item = directory / (name + suffix)
            if item.exists():
                shutil.copy2(item, scratch / item.name)
        with sqlite3.connect(scratch / name) as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            if name == 'app.store':
                expected = dict(ZKNOWLEDGE=0, ZSOURCE=0, ZAGENTMESSAGE=10, ZAGENTRUN=5, ZFSRSSTATE=0)
                counts = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in expected}
                assert counts == expected
                checks[name] = dict(quick_check='ok', counts=counts)
            else:
                payload = json.loads(db.execute('SELECT payload FROM agent_sessions_v2 WHERE session_id=?',
                    (original['session_id'],)).fetchone()[0])
                task = json.loads(db.execute('SELECT payload FROM harness_tasks WHERE task_id=?', (task_id,)).fetchone()[0])
                assert len(payload['messages']) == 9 and len(payload['runs']) == 5
                assert payload['capture_offers'] == original['capture_offers']
                assert task['context']['sources'] == original['tasks'][task_id]['context']['sources']
                checks[name] = dict(quick_check='ok', messages=9, runs=5, sources=1, invitation_unchanged=True)

    actual_setup = read(ROOT / 'docs/evidence/2026-10-17-separate-topic-real/setup.json')
    runtime = Path(actual_setup['directory'])
    assert read(runtime / 'request-count.json') == dict(actual_requests=30, limit=30)
    for name in ('request-count.json', 'STOP'):
        assert digest(runtime / name) == digest(ROOT / 'docs/evidence/2026-10-17-separate-topic-real' / name)
    parent = actual_setup['parent_runtimes']['original_26']
    parent_files = {}
    for name, expected in parent['sha256'].items():
        item = Path(parent['directory']) / name
        parent_files[name] = 'missing' if not item.exists() else 'same' if digest(item) == expected else 'changed'
    assert 'changed' not in parent_files.values(), 'Existing historical runtime file changed'
    # /tmp is not the durable evidence store. Report missing historical helpers
    # instead of recreating them or claiming the old 19-file check still passes.
    # This continuation uses the separately prepared, fully checked copy above.
    assert prepared == {str(p.relative_to(directory)): digest(p) for p in directory.rglob('*') if p.is_file()}
    current = {name: digest(ROOT / name) for name in previous['protected_file_sha256']}
    changed = [name for name, value in current.items() if value != previous['protected_file_sha256'][name]]
    expected_changes = ['agent-service/agent_service/conversation.py', 'agent-service/agent_service/conversation_prompts.py',
        'agent-service/agent_service/source_projection.py', 'agent-service/agent_service/schemas.py']
    assert sorted(changed) == sorted(expected_changes)
    added = []
    for folder, pattern in (('agent-service/agent_service', '*.py'), ('Review_Today', '*.swift')):
        for item in (ROOT / folder).rglob(pattern):
            name = str(item.relative_to(ROOT))
            if name not in current:
                added.append(name)
                current[name] = digest(item)
    assert added == ['agent-service/agent_service/article_coverage.py']
    assert all(current[name] == value for name, value in previous['protected_file_sha256'].items() if name.startswith('Review_Today/'))
    assert subprocess.check_output(['git', 'diff', '--name-only', '--', 'agent-service/agent_service', 'Review_Today'],
        cwd=ROOT, text=True) == ''
    selftest = read(OUT / 'preflight-result.json')
    assert selftest['outcome'] == 'PASS' and len(selftest['cases']) == 11
    result = dict(status='READY_FOR_SCOPE_AND_ALLOWANCE_CONFIRMATION', date='2026-10-21',
        baseline_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        proposed_model_requests=24, proposed_provider_web_operations=16, confirmed=False,
        actual_new_model_requests=0, actual_new_web_operations=0, guard_cases_passed=11,
        prepared_directory=str(directory), prepared_files_unchanged=len(prepared), pending_and_hold_unchanged=True,
        real_pending_guard_blocked_without_writes=True, shadow_database_checks=checks,
        source_checkpoint_sha256=digest(source), old_EVAL03_directory=str(runtime), old_EVAL03_requests=30,
        old_EVAL03_stop_and_counter_match_archive=True, original_26_runtime_files=parent_files,
        original_26_missing_files_recreated=False,
        changed_since_preparation=changed, added_since_preparation=added, current_fingerprints=current,
        current_swift_matches_preparation=106,
        existing_qa_bundle_available=Path('/tmp/review-today-startup-diagnosis-1ux5ch6l/ContinuousResumeQA.app').is_dir(),
        user_project_diff_sha256=hashlib.sha256(subprocess.check_output(['git', 'diff', '--',
            'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest(),
        daily_database_opened=False, production_modified=False, app_or_service_started=False,
        remaining_before_live=['Human confirmation of the new 24/16 allowance',
            'Install this tested guard in a new isolated native service bootstrap before main/probes import',
            'Recheck current source/config fingerprints immediately before startup'],
        caveat='Offline fixtures and shadow checks do not prove native startup, real model quality, or actual save.')
    (OUT / 'readiness-refresh.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'current_fingerprints'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
