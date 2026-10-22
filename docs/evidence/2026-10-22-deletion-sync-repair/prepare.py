"""Snapshot protection and copy the verified pre-update backup; no daily writes."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT/'output/deletion-sync-repair-2026-10-22'


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    assert not (OUT/'setup.json').exists(), 'Never overwrite retained preparation'
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode == 1
    assert subprocess.run(['lsof','-nP','-iTCP:8742','-sTCP:LISTEN'],capture_output=True).returncode == 1
    prior = json.loads((ROOT/'docs/evidence/2026-10-22-local-app-preflight/source-pins.json').read_text())
    changed = [name for name,value in prior.items() if digest(ROOT/name) != value]
    assert changed == ['Review_Today/SessionDeletion.swift'], changed
    protected = {name:value for name,value in prior.items() if name not in changed}
    support = Path.home()/'Library/Application Support/Review Today'
    daily = {str(p):digest(p) for p in support.rglob('*') if p.is_file() and (p.name.endswith(('.store','.sqlite3','-wal','.review-v2-backup')))}
    candidate = json.loads((ROOT/'docs/evidence/2026-10-22-local-app-preflight/installation.json').read_text())
    app = Path(candidate['installed'])
    app_files = {str(p):digest(p) for p in app.rglob('*') if p.is_file()}
    old = json.loads((ROOT/'docs/evidence/2026-10-21-status-presentation/setup.json').read_text())
    frozen = {str(Path(directory)/name):value for directory,files in old['protected_runtime_files'].items() for name,value in files.items()}
    activation = ROOT/'output/local-app-preflight-2026-10-22/activation'
    frozen.update({str(activation/name):digest(activation/name) for name in ['authorization.json','quota.json','STOP']})
    assert all(digest(Path(name)) == value for name,value in frozen.items())
    directory = Path(tempfile.mkdtemp(prefix='review-today-deletion-sync-',dir='/tmp'))
    source = ROOT/'output/local-app-preflight-2026-10-22/backup/ApplicationSupport-ReviewToday'
    originals = [source/'Data/ReviewToday.store',source/'agent-harness.sqlite3']
    for path,name in zip(originals,['app.store','checkpoint.sqlite3']):
        shutil.copy2(path,directory/name)
        with sqlite3.connect((directory/name).as_uri()+'?mode=ro',uri=True) as db:
            assert db.execute('pragma quick_check').fetchone()[0] == 'ok'
    with sqlite3.connect((directory/'app.store').as_uri()+'?mode=ro',uri=True) as db:
        markers = json.loads(db.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchone()[0])
        marker = next(m for m in markers if not m['cleaned'] and m.get('archive_action_id') and m['lifecycle_revision']==1)
    write(directory/'real-config.json',dict(marker=marker))
    report = dict(directory=str(directory),baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source='verified pre-decision257 backup, not live daily database',source_backup_files={str(p):digest(p) for p in originals},
        protected_sources=protected,expected_changed_production_files=changed,daily_files=daily,app_files=app_files,frozen_files=frozen,
        project_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest(),
        actual_model_requests=0,actual_web_operations=0,daily_app_updated=False,daily_data_cleanup=False)
    write(OUT/'setup.json',report)
    print(json.dumps(dict(directory=str(directory),protected_sources=len(protected),daily_files=len(daily),app_files=len(app_files),frozen_files=len(frozen))))


if __name__ == '__main__':main()
