"""Freeze a new closed-daily observation; inspect copies, not original databases."""
from contextlib import closing
from datetime import datetime, timezone
import os
import platform
import shutil
import sqlite3
import sys
import zipfile
from common import *


def main():
    assert not (OUT / 'entry-baseline.json').exists(), 'Never overwrite a baseline'
    assert not PRIVATE.exists() and not DURABLE.exists(), 'Use a new batch directory'
    stopped()
    repair_dir = ROOT / 'docs/evidence/2026-10-24-teaching-scope-repair'
    repair = read(repair_dir / 'verification.json')
    assert repair['status'] == 'IMPLEMENTED_OFFLINE_PASS_DAILY_DRIFT_RECORDED'
    assert all(sha(ROOT / p) == h for p, h in repair['production_source_sha256'].items())
    before = files(SUPPORT)
    app_inventory = inventory(DAILY)
    legacy = read(repair_dir / 'baseline.json')
    assert app_inventory == legacy['daily_app_inventory']
    assert all(Path(p).is_file() and sha(Path(p)) == h for p, h in legacy['old_frozen_files'].items())
    assert all(not Path(p).exists() for p in legacy['known_missing_old_paths'])
    assert sha(ROOT / 'Review_Today.xcodeproj/project.pbxproj') == legacy['user_project_sha256']
    source_before = read(PRIOR / 'setup.json')['protected_fingerprints']
    pins = dict(source_before)
    pins.update(repair['production_source_sha256'])
    assert all(sha(ROOT / p) == h for p, h in pins.items()), 'Unexpected source/configuration drift'
    PRIVATE.mkdir(mode=0o700)
    DURABLE.mkdir(parents=True, mode=0o700)
    copied = DURABLE / 'daily-closed-copy'
    copied.mkdir(mode=0o700)
    for raw in before:
        source = Path(raw)
        target = copied / source.relative_to(SUPPORT)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(source, target)
        os.chmod(target, 0o600)
        assert sha(target) == before[raw]
    assert files(SUPPORT) == before
    stopped()

    def audit(event, args):
        if event == 'socket.connect':
            raise AssertionError('No network in environment preparation')
        if event == 'sqlite3.connect':
            from urllib.parse import unquote, urlsplit
            raw = str(args[0])
            path = Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).resolve()
            assert path.is_relative_to(copied), 'Only the owned daily copy may be inspected'
    sys.addaudithook(audit)
    archive = DURABLE / 'daily-closed-observation.zip'
    copied_files = files(copied)
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for raw in copied_files:
            z.write(raw, str(Path(raw).relative_to(copied)))
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == len(copied_files)
        assert all(hashlib.sha256(z.read(str(Path(raw).relative_to(copied)))).hexdigest() == h for raw, h in copied_files.items())
    counts = {}
    for name in ('Data/ReviewToday.store', 'agent-harness.sqlite3', 'agent-harness.review.sqlite3'):
        path = copied / name
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('pragma quick_check').fetchall() == [('ok',)]
            tables = [t for t, in db.execute("select name from sqlite_master where type='table'")]
            counts[name] = {t: db.execute('select count(*) from "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}
    # Config import is allowed to load existing settings, never stores or transport.
    sys.path.insert(0, str(ROOT / 'agent-service'))
    from agent_service import config
    environment = dict(platform='macOS', version=platform.mac_ver()[0], architecture=platform.machine(),
        os_build=subprocess.check_output(['sw_vers', '-buildVersion'], text=True).strip(),
        python_version=platform.python_version(), python_executable=sys.executable,
        provider=config.PROVIDER, router=config.ROUTER_MODEL, coach=config.COACH_MODEL, risk=config.RISK_MODEL,
        provider_key_configured=bool(config.openai_key()), existing_config_not_changed=True,
        config_presence_does_not_prove_credentials_or_provider_ready=True,
        expected_native_window=dict(default=[1040, 820], minimum=[760, 620]),
        planned_appearances=['light', 'dark'], native_interaction_not_run=True,
        actual_model_requests=0, actual_web_operations=0)
    assert environment['provider'] == 'deepseek' and environment['provider_key_configured']
    assert files(SUPPORT) == before and inventory(DAILY) == app_inventory
    result = dict(status='CLOSED_DAILY_COPY_AND_CURRENT_SOURCE_VERIFIED', decision=270,
        observed_at=datetime.now(timezone.utc).isoformat(), daily_files=before, daily_app_inventory=app_inventory,
        source_config_pins=pins, repair_source_sha256=repair['production_source_sha256'],
        original_daily_databases_opened=False, copies_quick_check_passed=3, copied_table_counts=counts,
        daily_copy_archive=str(archive), daily_copy_archive_sha256=sha(archive), daily_copy_members=len(copied_files),
        original_269_baseline_preserved=True,
        changed_since_269_original_baseline=[p for p in legacy['daily_files'] if before.get(p) != legacy['daily_files'][p]],
        added_since_269_original_baseline=sorted(set(before) - set(legacy['daily_files'])),
        earlier_daily_changes_cause_not_attributed=True, qa_imports_formal_history=False,
        old_frozen_files=legacy['old_frozen_files'], known_missing_old_paths=legacy['known_missing_old_paths'],
        user_project_sha256=legacy['user_project_sha256'])
    write(OUT / 'environment.json', environment)
    write(OUT / 'entry-baseline.json', result)
    shutil.copy2(OUT / 'entry-baseline.json', DURABLE / 'entry-baseline.json')
    print('Closed daily copy checked: 3 databases, original stores unopened; current repair/config verified; real calls 0/0.')


if __name__ == '__main__':
    main()
