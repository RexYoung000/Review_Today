"""Copy stopped daily inputs first. SQLite is allowed only on new owned copies."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from common import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, SUPPORT, DBS, read, write, sha, files, inventory, stopped, prior_helpers, unchanged


def main():
    assert not ARCHIVE.exists() and not (OUT / 'backup.json').exists()
    stopped()
    original = files(SUPPORT)
    daily_inventory = inventory(DAILY)
    previous_candidate = read(ROOT / 'docs/evidence/2026-10-22-daily-sync-preflight/candidate.json')
    assert daily_inventory == previous_candidate['inventory']
    project_diff = hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)).hexdigest()
    assert project_diff == '8b31e8d2938a6ff21062e1a8be6de940784ea729763136d4b54573fa52c63502'
    baseline = read(ROOT / 'docs/evidence/2026-10-22-navigation-save-preflight/setup.json')
    pins = {p: sha(ROOT / p) for p in baseline['protected_fingerprints']}
    write(PRIVATE / 'source-protection.json', dict(daily_files=original, daily_app_inventory=daily_inventory,
        project_diff_sha256=project_diff, source_config_pins=pins, baseline_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()))
    ARCHIVE.mkdir(parents=True, mode=0o700)
    os.chmod(ARCHIVE, 0o700)
    def audit(event, args):
        if event == 'socket.connect': raise AssertionError('Preparation must remain offline')
        if event == 'sqlite3.connect':
            path = str(args[0]); path = path[5:].split('?', 1)[0] if path.startswith('file:') else path
            if not Path(path).resolve().is_relative_to(ARCHIVE):
                raise AssertionError('Only the new private backup databases may be opened')
    sys.addaudithook(audit)
    raw = ARCHIVE / 'raw-active-support'; raw.mkdir()
    active = {p: h for p, h in original.items() if not Path(p).is_relative_to(SUPPORT / 'Backups')}
    for name, h in active.items():
        target = raw / Path(name).relative_to(SUPPORT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
        assert sha(target) == h
    helpers = prior_helpers()
    summaries = {}
    consistent = ARCHIVE / 'consistent-databases'; consistent.mkdir()
    for relative, name in DBS.items():
        source = raw / relative
        before = helpers.summary(source)
        target = consistent / name
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst); dst.execute('pragma journal_mode=delete')
        assert helpers.summary(target) == before
        summaries[relative] = before
    write(PRIVATE / 'before-tables.json', summaries)
    config_pins = {}
    for source in [ROOT / 'agent-service/.env', *sorted((ROOT / 'agent-service/providers').glob('*/.env'))]:
        if source.is_file():
            target = ARCHIVE / 'private-config' / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target); target.chmod(0o600)
            assert sha(target) == sha(source)
            config_pins[str(source.relative_to(ROOT))] = sha(source)
    old_zip = ARCHIVE / 'ReviewToday-before.zip'
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(DAILY), str(old_zip)], check=True)
    check = ARCHIVE / 'before-check.noindex'; check.mkdir()
    subprocess.run(['ditto', '-x', '-k', str(old_zip), str(check)], check=True)
    restored = check / DAILY.name
    assert inventory(restored) == daily_inventory
    signature = helpers.signature(restored)
    assert signature == helpers.signature(DAILY)
    shutil.rmtree(check)
    activation = PRIVATE / 'activation'; activation.mkdir(mode=0o700)
    authorization = dict(status='pending', batch_id=str(uuid.uuid4()), actual_model_request_limit=8,
        provider_web_operation_limit=0, database_path=str(SUPPORT / 'agent-harness.sqlite3'),
        daily_app=str(DAILY), scope='same daily entry update; one startup probe batch; inspect existing data only; no messages/save/cleanup')
    write(activation / 'authorization.json', authorization)
    (activation / 'HOLD').write_text('Preparation only. Daily update/startup and a new 8/0 allowance require separate confirmation.\n')
    unchanged()
    write(PRIVATE / 'backup-pins.json', files(ARCHIVE))
    report = dict(status='RECOVERABLE_BACKUP_READY_PENDING_UPDATE', archive=str(ARCHIVE),
        active_files_copied=len(active), all_daily_files_protected=len(original),
        historical_backup_files_not_recopied=len(original)-len(active),
        consistent_database_count=3, sqlite_opened_only_on_new_owned_copies=True,
        daily_app_archive=str(old_zip), daily_app_archive_sha256=sha(old_zip), original_signature=signature,
        actual_extract_permissions_and_signature_verified=True, private_config_files=len(config_pins),
        native_counts={t: summaries['Data/ReviewToday.store']['tables'][t]['count'] for t in ['ZAGENTSESSION', 'ZAGENTMESSAGE', 'ZKNOWLEDGE', 'ZFSRSSTATE']},
        actual_new_model_requests=0, actual_new_web_operations=0, daily_app_updated=False, daily_app_started=False,
        historical_cleanup_included=False, authorization_pending=True, hold_preserved=True)
    write(OUT / 'backup.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
