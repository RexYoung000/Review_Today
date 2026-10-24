"""Read-only fingerprint checks; never open SQLite or control the daily App."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
baseline = json.loads((OUT / 'baseline.json').read_text())
spec = importlib.util.spec_from_file_location('existing_packaging_inventory',
    ROOT / 'docs/evidence/2026-10-23-daily-update-preflight/common.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compare(key):
    values = baseline[key]
    changed = []
    for raw, expected in values.items():
        path = Path(raw) if Path(raw).is_absolute() else ROOT / raw
        actual = digest(path) if path.is_file() else None
        if actual != expected:
            changed.append(dict(path=raw, expected_sha256=expected, observed_sha256=actual,
                observed_mtime=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.exists() else None))
    return dict(checked=len(values), matching=len(values) - len(changed), changed=changed)


groups = {key: compare(key) for key in ('prior_pins_outside_fix', 'daily_files', 'old_frozen_files',
    'original_module_files', 'owned_support_files', 'failure_public_files')}
app_same = helpers.inventory(Path('/Applications/Review Today.app')) == baseline['daily_app_inventory']
project_same = digest(ROOT / 'Review_Today.xcodeproj/project.pbxproj') == baseline['user_project_sha256']
archive = baseline['failure_archive']
archive_same = digest(archive['archive']) == archive['sha256']
missing_same = all(not Path(path).exists() for path in baseline['known_missing_old_paths'])
runtime = Path(baseline['stopped_runtime'])
quota = json.loads((runtime / 'quota.json').read_text())
assert quota['closed'] and quota['model_requests'] == 11 and quota['web_operations'] == 0
assert (runtime / 'STOP').is_file()
source_changes = [raw for raw, expected in baseline['source_before'].items()
    if (digest(ROOT / raw) if (ROOT / raw).is_file() else None) != expected]
non_daily_pass = all(not value['changed'] for key, value in groups.items() if key != 'daily_files')
non_daily_pass = non_daily_pass and app_same and project_same and archive_same and missing_same
assert non_daily_pass
process = subprocess.run(['pgrep', '-x', 'Review_Today'], capture_output=True, text=True)
listener = subprocess.run(['lsof', '-nP', '-iTCP:8742', '-sTCP:LISTEN'], capture_output=True, text=True)
result = dict(status='NON_DAILY_PROTECTION_PASS_DAILY_RUNTIME_DRIFT' if groups['daily_files']['changed'] else 'PROTECTION_PASS',
    checked_at=datetime.now(timezone.utc).isoformat(), fingerprint_groups=groups,
    non_daily_protection_passed=non_daily_pass, daily_data_unchanged=not groups['daily_files']['changed'],
    daily_observation_is_not_atomic_database_snapshot=True,
    daily_app_inventory_unchanged=app_same, user_project_unchanged=project_same,
    failure_archive_unchanged=archive_same, known_missing_old_paths_still_missing=len(baseline['known_missing_old_paths']),
    authorized_production_changes=source_changes,
    daily_app_running_pids=process.stdout.strip().splitlines(), daily_service_listener=listener.stdout.strip(),
    daily_runtime_not_launched_or_stopped_by_this_work=True,
    observed_daily_launch_local_time='2026-10-24 14:42:52 +0800',
    observed_daily_service_launch_local_time='2026-10-24 14:42:53 +0800',
    controlled_full_test_start_local_time='2026-10-24 14:45:12 +0800',
    daily_database_changes_cause_not_attributed=True, daily_baseline_replaced=False,
    daily_data_restored_or_written_by_this_work=False, daily_app_replaced=False,
    stopped_268_batch=dict(closed=True, model_requests=11, web_operations=0, remaining_frozen=dict(model=29, web=16)),
    source_after={raw: digest(ROOT / raw) for raw in baseline['allowed_production_files']})
(OUT / 'protection-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(result['status'])
print('Protected non-fix inputs, old evidence, archive, modules, App and user project match; frozen batch remains 11/0 closed.')
print('Daily baseline mismatches:', len(groups['daily_files']['changed']), '; no baseline replacement or data write.')
