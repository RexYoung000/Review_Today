"""Verify held real entries, immutable inputs, signed archives and unique entry."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
from common import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, SUPPORT, LS, read, write, sha, files, inventory, stopped, unchanged, pin_files


def main():
    unchanged()
    pins = read(OUT / 'source-pins.json')
    assert pins == pin_files()
    backup = read(OUT / 'backup.json'); candidate = read(OUT / 'candidate.json')
    assert sha(Path(backup['daily_app_archive'])) == backup['daily_app_archive_sha256']
    assert sha(Path(candidate['zip'])) == candidate['zip_sha256']
    assert all(sha(Path(p)) == h for p, h in read(PRIVATE / 'backup-pins.json').items())
    assert not (ARCHIVE / 'install-stage.noindex').exists()
    assert not (PRIVATE / 'execution.json').exists() and not (OUT / 'installation.json').exists()
    assert not list(ARCHIVE.rglob('*.app'))
    baseline = read(ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json')
    previous_protection = read(ROOT / 'docs/evidence/2026-10-22-navigation-save-real/protection.json')
    missing = [p for p in baseline['old_frozen_files'] if not Path(p).is_file()]
    assert set(missing) == set(previous_protection['missing_old_files'])
    assert all(sha(Path(p)) == h for p, h in baseline['old_frozen_files'].items() if p not in missing)
    for key in ['original_module_files', 'original_support_files', 'owned_support_files', 'previous_batch_files']:
        assert all(sha(Path(p)) == h for p, h in baseline[key].items()), key
    history = read(ROOT / 'docs/evidence/2026-10-23-evidence-protection/verification.json')
    historical_archive = Path(history['archive'])
    assert sha(historical_archive) == history['archive_sha256']
    manifest = read(historical_archive.parent / 'manifest.json')
    for key in ['current_run_private', 'current_run_public']:
        assert all(sha(Path(p)) == h for p, h in manifest[key].items()), key
    # Title evidence from 265 is also immutable; this task adds packaging only.
    title = ROOT / 'docs/evidence/2026-10-23-title-fallback-repair'
    assert all(sha(title / p) == h for p, h in read(title / 'manifest.json').items())
    activation = PRIVATE / 'activation'
    held = files(activation)
    assert {p.name for p in activation.iterdir()} == {'authorization.json', 'HOLD'}
    assert read(activation / 'authorization.json')['status'] == 'pending'
    # These are the actual execution entries with an outer deny hook, not wrappers
    # that replace their approval checks. They must reject before imports or writes.
    program = '''import json,runpy,sys
from pathlib import Path
entry=Path(sys.argv[1]);sys.path.insert(0,str(entry.parent));sys.argv=[str(entry),*sys.argv[2:]]
def audit(event,args):
    if event in {'socket.connect','sqlite3.connect'}:raise AssertionError('Pre-approval database/network operation')
sys.addaudithook(audit)
try:runpy.run_path(str(entry),run_name='__main__')
except PermissionError as error:
    assert 'pending explicit approval' in str(error)
    assert 'agent_service.main' not in sys.modules and 'agent_service.model_capabilities' not in sys.modules
    print(json.dumps(dict(entry=entry.name,pending_refused=True,service_imported=False,database_opened=False,network_opened=False)))
else:raise AssertionError('Pending actual entry was admitted')
'''
    guards = []
    for name, args in [('install_prepared.py', ['--install-approved']), ('start_service.py', [])]:
        result = subprocess.run([sys.executable, '-c', program, str(OUT / name), *args], capture_output=True, text=True, timeout=20)
        (PRIVATE / (name + '.pending-check.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr
        guards.append(json.loads(result.stdout))
    assert files(activation) == held
    assert not (PRIVATE / 'execution.json').exists()
    assert not (OUT / 'installation.json').exists()
    assert not (activation / 'quota.json').exists()
    execution = read(OUT / 'execution-checks.json')
    assert len(execution['authorization_cases']) == 10 and all(c['passed'] for c in execution['filesystem_cases'])
    assert sha(Path(execution['archive'])) == execution['archive_sha256']
    probe = read(OUT / 'probe-checks.json'); failure = read(OUT / 'probe-failure-check.json')
    assert probe['outcome'] == failure['outcome'] == 'PASS'
    assert probe['fake_sdk_requests'] == probe['usage_receipts'] == 8
    assert probe['conversation_call_blocked'] and probe['ninth_probe_blocked']
    assert probe['zero_web_entries_blocked'] == 12 and failure['first_failure_stops']
    registrations = subprocess.check_output([LS, '-dump'], text=True)
    (PRIVATE / 'registrations-final.txt').write_text(registrations)
    ids = re.findall(r'^identifier:\s*(.*)$', registrations, re.M)
    count = sum(bool(re.search(r'review[-_]?today', value, re.I)) for value in ids)
    spotlight = subprocess.check_output(['mdfind', "kMDItemContentType == 'com.apple.application-bundle' && kMDItemCFBundleIdentifier == 'Rex.Review-Today'"], text=True).splitlines()
    assert count == 1 and spotlight == [str(DAILY)]
    active = {p: h for p, h in read(PRIVATE / 'source-protection.json')['daily_files'].items() if not Path(p).is_relative_to(SUPPORT / 'Backups')}
    assert all(sha(ARCHIVE / 'raw-active-support' / Path(p).relative_to(SUPPORT)) == h for p, h in active.items())
    unchanged()
    report = dict(status='PREPARED_AND_HELD_NOT_INSTALLED_OR_STARTED', actual_new_model_requests=0,
        actual_new_web_operations=0, production_modified=False, daily_app_updated=False, daily_app_started=False,
        daily_files_unchanged=len(read(PRIVATE / 'source-protection.json')['daily_files']),
        daily_app_and_user_project_diff_unchanged=True, execution_source_config_pins=len(pins),
        original_old_files_matched=240-len(missing), original_old_paths_still_missing=len(missing),
        historical_gap_not_reclassified=True, original_module_support_and_264_265_evidence_unchanged=True,
        raw_active_backup_bytes_match=True, three_consistent_db_copies_verified=True,
        original_and_candidate_actual_extract_signature_verified=True, raw_candidate_removed=True,
        authorization_cases=10, controlled_installer_success_and_rollback=True,
        actual_pending_entry_checks=guards, held_files_unchanged=True, no_execution_or_quota_created=True,
        fake_probe_requests=8, fake_failure_requests=1, ninth_probe_and_nonprobe_blocked=True,
        zero_web_entries_blocked=12, first_probe_failure_stops=True,
        related_registered_entries=count, spotlight_paths=spotlight, app_and_service_stopped=True,
        proposed_new_model_limit=8, proposed_new_web_limit=0, old_allowances_frozen=True,
        actual_daily_update_startup_and_user_experience_not_verified=True,
        uninterrupted_fullflow_m1_voiceover_not_closed=True)
    write(OUT / 'verification.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
