"""Verify prepared artifacts and that daily/previous state remains untouched."""
import ast
import hashlib
import json
from pathlib import Path
import stat
import subprocess

from prepare import DATABASES, DAILY, OUT, PRIVATE, ROOT, SUPPORT, PROJECT_DIFF, digest, signature, stopped, summary, write


def main():
    stopped()
    pins = json.loads((OUT/'source-pins.json').read_text())
    assert all(digest((ROOT/name).read_bytes()) == value for name,value in pins.items())
    assert digest(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)) == PROJECT_DIFF
    for path in OUT.glob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
    backup = json.loads((OUT/'backup.json').read_text())
    before = json.loads((PRIVATE/'before.json').read_text())
    current = {name:summary(SUPPORT/name) for name in DATABASES}
    assert current == before
    assert {name:summary(Path(backup['backup'])/'ApplicationSupport-ReviewToday'/name) for name in DATABASES} == before
    assert signature(DAILY) == backup['daily_signature']
    assert signature(Path(backup['backup'])/'Review_Today.app') == backup['daily_signature']
    candidate = json.loads((OUT/'candidate.json').read_text())
    assert signature(Path(candidate['app'])) == candidate['signature']
    configs = [name for name in pins if name.endswith('/.env')]
    for name in configs:
        path = Path(backup['backup'])/'private-config'/name
        assert digest(path.read_bytes()) == pins[name]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    prior = json.loads((ROOT/'docs/evidence/2026-10-21-status-presentation/setup.json').read_text())
    old_count = 0
    for dirname, items in prior['protected_runtime_files'].items():
        for rel, checksum in items.items():
            assert digest((Path(dirname)/rel).read_bytes()) == checksum
            old_count += 1
    guard = json.loads((OUT/'preflight-result.json').read_text())
    assert guard['outcome'] == 'PASS' and len(guard['cases']) == 11
    assert json.loads((OUT/'probe-checks.json').read_text())['outcome'] == 'PASS'
    assert json.loads((OUT/'probe-failure-check.json').read_text())['first_failure_stops']
    for case in [
            ['agent-service/.venv/bin/python','-B',str(OUT/'start_service.py')],
            ['agent-service/.venv/bin/python','-B',str(OUT/'install_candidate.py'),'--install-approved']]:
        result = subprocess.run(case,cwd=ROOT,capture_output=True,text=True)
        assert result.returncode != 0
    activation = PRIVATE/'activation'
    assert json.loads((activation/'authorization.json').read_text())['status'] == 'pending'
    assert (activation/'HOLD').exists()
    assert not (activation/'quota.json').exists() and not (activation/'bootstrap-ready.json').exists()
    assert not (OUT/'installation.json').exists()
    assert '** BUILD SUCCEEDED **' in (PRIVATE/'build.log').read_text()
    stopped()
    report = dict(status='READY_PENDING_NEW_ACTIVATION_ALLOWANCE',
        native_counts=backup['native_counts'], full_support_backup_bytes=backup['support_bytes'],
        active_database_integrity='all_three_ok', backup_all_table_rows_match=True, source_all_table_rows_unchanged=True,
        old_app_all_three_binaries_match_oct18=backup['matches_oct18_all_three_binaries'],
        current_signed_candidate_verified=True, old_signed_app_and_backup_verified=True,
        private_configs_backed_up_0600=len(configs), source_pins_checked=len(pins), old_runtime_files_unchanged=old_count,
        sdk_fake_transport_cases=11, extra_probe_checks=['zero-web','probe-only','ninth-transport-blocked','first-failure-stop'],
        actual_pending_start_and_install_both_rejected=True, project_diff_sha256=PROJECT_DIFF,
        actual_model_requests=0, actual_web_operations=0, daily_app_replaced=False, daily_app_launched=False,
        proposed_new_limits=dict(model_requests=8,web_operations=0), authorization='pending/HOLD')
    write(OUT/'result.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
