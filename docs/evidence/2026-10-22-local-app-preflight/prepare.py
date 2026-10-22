"""Read-only daily-store inspection and private recoverable backup. No App launch."""
import base64
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'output/local-app-preflight-2026-10-22'
SUPPORT = Path.home() / 'Library/Application Support/Review Today'
DAILY = Path.home() / 'Library/Developer/Xcode/DerivedData/Review_Today-gkeqhkrlvxqhunchqjqzselqoapv/Build/Products/Debug/Review_Today.app'
DATABASES = ['Data/ReviewToday.store', 'agent-harness.sqlite3', 'agent-harness.review.sqlite3']
PROJECT_DIFF = '8b31e8d2938a6ff21062e1a8be6de940784ea729763136d4b54573fa52c63502'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def command(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True)


def stopped():
    for args in (['pgrep', '-x', 'Review_Today'], ['lsof', '-nP', '-iTCP:8742', '-sTCP:LISTEN', '-t']):
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 1 and not result.stdout.strip(), 'Daily App/service is active'


def connect(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.execute('pragma query_only=on')
    return db


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def summary(path):
    # Stream all rows, including SwiftData history, without retaining private text.
    with connect(path) as db:
        integrity = [r[0] for r in db.execute('pragma integrity_check')]
        assert integrity == ['ok'], str(path)
        tables = {}
        for name, in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
            info = db.execute('pragma table_info(' + quote(name) + ')').fetchall()
            keys = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]] or [r[1] for r in info]
            count, checksum = 0, hashlib.sha256()
            for row in db.execute('select * from ' + quote(name) + ' order by ' + ','.join(map(quote, keys))):
                values = [{'blob': base64.b64encode(v).decode()} if isinstance(v, bytes) else v for v in row]
                checksum.update(json.dumps(values, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n')
                count += 1
            tables[name] = dict(count=count, sha256=checksum.hexdigest(), columns=[r[1] for r in info])
        return dict(integrity=integrity, tables=tables)


def files(directory):
    return {str(p.relative_to(directory)): digest(p.read_bytes()) for p in directory.rglob('*') if p.is_file()}


def signature(app):
    command(['codesign', '--verify', '--deep', '--strict', str(app)])
    details = command(['codesign', '-dv', '--verbose=4', str(app)]).stderr
    assert 'Identifier=Rex.Review-Today\n' in details
    assert 'TeamIdentifier=7NDKLL3UJK\n' in details
    assert 'Authority=Apple Development:' in details
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    return dict(bundle_id=info['CFBundleIdentifier'], team='7NDKLL3UJK', strict_verified=True,
                binaries={p.name:digest(p.read_bytes()) for p in (app/'Contents/MacOS').iterdir() if p.is_file()})


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    assert not (OUT/'backup.json').exists(), 'Never overwrite an existing preparation'
    stopped()
    assert digest(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'], cwd=ROOT)) == PROJECT_DIFF
    backup = PRIVATE/'backup'
    assert not backup.exists()
    backup.mkdir(parents=True, mode=0o700)
    size = sum(p.stat().st_size for p in SUPPORT.rglob('*') if p.is_file())
    assert shutil.disk_usage(PRIVATE).free > size * 2 + 500_000_000
    before = {name:summary(SUPPORT/name) for name in DATABASES}
    print('Three active databases passed integrity; backing up App and complete support directory.', flush=True)
    shutil.copytree(DAILY, backup/'Review_Today.app', symlinks=True)
    shutil.copytree(SUPPORT, backup/'ApplicationSupport-ReviewToday', symlinks=True)
    for name in DATABASES:
        target = backup/'ApplicationSupport-ReviewToday'/name
        temporary = target.with_name(target.name+'.consistent-backup')
        with connect(SUPPORT/name) as source, sqlite3.connect(temporary) as destination:
            source.backup(destination)
            destination.execute('pragma journal_mode=delete')
        temporary.replace(target)
        for suffix in ['-wal','-shm']:
            target.with_name(target.name+suffix).unlink(missing_ok=True)
        assert summary(target) == before[name], name
    config_files = [ROOT/'agent-service/.env', ROOT/'agent-service/providers/deepseek/.env']
    config_digests = {}
    for config in config_files:
        if config.exists():
            target = backup/'private-config'/config.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config, target)
            target.chmod(0o600)
            config_digests[str(config.relative_to(ROOT))] = digest(config.read_bytes())
    stopped()
    assert {name:summary(SUPPORT/name) for name in DATABASES} == before, 'Source changed while backing up'
    old_signature = signature(DAILY)
    assert files(DAILY) == files(backup/'Review_Today.app')
    assert signature(backup/'Review_Today.app') == old_signature
    prior = json.loads((ROOT/'docs/evidence/2026-10-18-web-app/activation.json').read_text())
    write(PRIVATE/'before.json', before)
    report = dict(status='BACKUP_READY_NO_LAUNCH', backup=str(backup), support_bytes=size,
        daily_app=str(DAILY), daily_signature=old_signature,
        matches_oct18_all_three_binaries=old_signature['binaries'] == prior['build']['binaries'],
        backup_all_three_database_rows_match=True, source_databases_unchanged=True,
        native_counts={k:before[DATABASES[0]]['tables'][k]['count'] for k in ['ZKNOWLEDGE','ZAGENTMESSAGE','ZAGENTSESSION','ZFSRSSTATE']},
        private_config_sha256=config_digests, project_diff_sha256=PROJECT_DIFF,
        actual_model_requests=0, actual_web_operations=0, daily_app_launched=False,
        baseline_commit=command(['git','rev-parse','HEAD']).stdout.strip())
    write(OUT/'backup.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
