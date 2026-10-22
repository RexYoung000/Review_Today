"""Fresh private backups and held authorization; never opens a daily SQLite file."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
PRIVATE = ROOT/'output/daily-sync-preflight-2026-10-22'
ARCHIVE = Path.home()/'Library/Developer/ReviewTodayAppArchives.noindex/2026-10-22-daily-sync-preflight'
SUPPORT = Path.home()/'Library/Application Support/Review Today'
DAILY = Path('/Applications/Review Today.app')
DBS = {'Data/ReviewToday.store':'app.store','agent-harness.sqlite3':'checkpoint.sqlite3','agent-harness.review.sqlite3':'review.sqlite3'}


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def stopped():
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode == 1
    assert not subprocess.run(['lsof','-nP','-iTCP:8742','-sTCP:LISTEN'],capture_output=True).stdout


def app_files(base):
    result = {}
    for parent,dirs,files in os.walk(base):
        for name in dirs+files:
            p = Path(parent)/name;s = p.lstat()
            row = dict(mode=stat.S_IMODE(s.st_mode),type='link' if p.is_symlink() else 'dir' if p.is_dir() else 'file')
            if p.is_symlink():row['target'] = os.readlink(p)
            elif p.is_file():row.update(size=s.st_size,sha256=sha(p))
            result[str(p.relative_to(base))] = row
    return result


def main():
    assert not (OUT/'backup.json').exists() and not ARCHIVE.exists()
    stopped();ARCHIVE.mkdir(parents=True,mode=0o700);PRIVATE.chmod(0o700)
    all_files = {str(p):sha(p) for p in SUPPORT.rglob('*') if p.is_file()}
    assert not any(p.suffix == '.app' for p in SUPPORT.rglob('*'))
    original_app = app_files(DAILY)
    original_project_diff = hashlib.sha256(subprocess.check_output(['git','diff','--','Review_Today.xcodeproj/project.pbxproj'],cwd=ROOT)).hexdigest()
    assert original_project_diff == '8b31e8d2938a6ff21062e1a8be6de940784ea729763136d4b54573fa52c63502'
    active_files = {p:h for p,h in all_files.items() if not Path(p).is_relative_to(SUPPORT/'Backups')}
    print('Backing up active data; existing historical Backups are preserved without recursive duplication.',flush=True)
    shutil.copytree(SUPPORT,ARCHIVE/'support',ignore=lambda directory,names:['Backups'] if Path(directory)==SUPPORT else [])
    assert all(sha(ARCHIVE/'support'/Path(p).relative_to(SUPPORT))==h for p,h in active_files.items())
    spec = importlib.util.spec_from_file_location('prior_preflight',ROOT/'docs/evidence/2026-10-22-local-app-preflight/prepare.py')
    previous = importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
    fresh = PRIVATE/'fresh-input';fresh.mkdir()
    summaries = {}
    for relative,name in DBS.items():
        source = ARCHIVE/'support'/relative
        before = previous.summary(source)
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(fresh/name)) as dst:
            src.backup(dst);dst.execute('pragma journal_mode=delete')
        assert previous.summary(fresh/name)==before
        summaries[relative]=before
        shutil.copy2(fresh/name,source)
        for suffix in ('-wal','-shm'):Path(str(source)+suffix).unlink(missing_ok=True)
        assert previous.summary(source)==before
    proof = SUPPORT/'Backups/20260906-harness-library/current.store'
    scope = json.loads((ROOT/'tools/legacy-deletion-lifecycle-scope.json').read_text())
    assert sha(proof)==scope['archive_proof_sha256']
    shutil.copy2(proof,fresh/'pre-sept7-archive-proof.store')
    configs = [ROOT/'agent-service/.env',*sorted((ROOT/'agent-service/providers').glob('*/.env'))]
    config_pins = {}
    for source in configs:
        if source.is_file():
            target = ARCHIVE/'private-config'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target);target.chmod(0o600)
            assert sha(target)==sha(source);config_pins[str(source.relative_to(ROOT))]=sha(source)
    before_zip = ARCHIVE/'ReviewToday-before.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(DAILY),str(before_zip)],check=True)
    check = ARCHIVE/'restore-check.noindex';check.mkdir()
    subprocess.run(['ditto','-x','-k',str(before_zip),str(check)],check=True)
    restored = check/'Review Today.app'
    assert app_files(restored)==original_app
    signature = previous.signature(restored);assert signature==previous.signature(DAILY)
    shutil.rmtree(check)
    stopped();assert app_files(DAILY)==original_app
    assert all(sha(Path(p))==h for p,h in all_files.items())
    assert {str(p) for p in SUPPORT.rglob('*') if p.is_file()}==set(all_files)
    write(PRIVATE/'source-protection.json',dict(daily_files=all_files,app_files=original_app,project_diff=original_project_diff,configs=config_pins))
    write(PRIVATE/'before-tables.json',summaries)
    activation = PRIVATE/'activation';activation.mkdir()
    authorization = dict(status='pending',batch_id='daily-sync-2026-10-22',actual_model_request_limit=8,provider_web_operation_limit=0,
                         database_path=str(SUPPORT/'agent-harness.sqlite3'),scope='single startup probe batch only; no messages, save or non-probe model calls')
    write(activation/'authorization.json',authorization)
    (activation/'HOLD').write_text('Preparation only; await explicit daily update, cleanup and new 8/0 authorization.\n')
    setup = json.loads((ROOT/'docs/evidence/2026-10-22-deletion-sync-repair/setup.json').read_text())
    pins = {p:sha(ROOT/p) for p in setup['protected_sources']}
    for path in configs:
        if path.is_file():pins[str(path.relative_to(ROOT))]=sha(path)
    write(OUT/'source-pins.json',pins)
    report = dict(status='BACKUP_READY_HELD_NO_DAILY_CHANGE',archive=str(ARCHIVE),fresh_input=str(fresh),active_data_files=len(active_files),
                  all_daily_files_protected=len(all_files),existing_backup_files_not_recopied=len(all_files)-len(active_files),
                  databases_consistent=True,private_config_files=len(config_pins),old_app_zip=str(before_zip),old_app_zip_sha256=sha(before_zip),
                  old_app_extracted_and_verified=True,old_signature=signature,
                  native_counts={t:summaries['Data/ReviewToday.store']['tables'][t]['count'] for t in ['ZAGENTSESSION','ZAGENTMESSAGE','ZKNOWLEDGE','ZFSRSSTATE']},
                  candidate_application_diff='Only SessionDeletion.swift differs from a29c6f1',actual_model_requests=0,actual_web_operations=0,
                  daily_app_updated=False,daily_cleanup=False,activation_status='pending',activation_hold=True)
    write(OUT/'backup.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
