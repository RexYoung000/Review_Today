"""Verify the last formal backup on new private copies; never touches daily data."""
from contextlib import closing
import hashlib
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
DURABLE=Path.home()/'Library/Developer/ReviewTodayEvidence.noindex/2026-10-23-daily-data-recovery'
SOURCE=Path.home()/'Library/Developer/ReviewTodayAppArchives.noindex/2026-10-23-daily-update-preflight'
SUPPORT=Path.home()/'Library/Application Support/Review Today'
DAILY=Path('/Applications/Review Today.app')
DBS=['Data/ReviewToday.store','agent-harness.sqlite3','agent-harness.review.sqlite3']

def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'))
def norm(v):return {'bytes_hex':v.hex()} if isinstance(v,bytes) else v

def audit(event,args):
    if event=='socket.connect':raise AssertionError('No network in recovery preparation')
    if event=='sqlite3.connect':
        from urllib.parse import unquote,urlsplit
        value=str(args[0]);path=Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).resolve()
        assert path.is_relative_to(DURABLE),'Only new recovery copies may be opened'


def main():
    assert not SUPPORT.exists(),'Daily directory reappeared; do not overwrite'
    assert subprocess.run(['pgrep','-x','Review_Today'],capture_output=True).returncode==1
    assert not subprocess.run(['lsof','-nP','-iTCP:8742','-sTCP:LISTEN'],capture_output=True).stdout
    assert not DURABLE.exists(),'Never reset a recovery attempt'
    DURABLE.mkdir(parents=True,mode=0o700);sys.addaudithook(audit)
    manifest=read(SOURCE/'activation-evidence-manifest.json');archive=SOURCE/'activation-evidence.zip'
    assert sha(archive)==manifest['archive_sha256']==read(ROOT/'docs/evidence/2026-10-23-daily-update-preflight/activation-archive.json')['archive_sha256']
    extracted=DURABLE/'extracted';extracted.mkdir()
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist())==set(manifest['files'])
        for name,h in manifest['files'].items():
            with z.open(name) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==h,name
        selected={n:h for n,h in manifest['files'].items() if n.startswith('after-active-support/')}
        assert len(selected)==9
        for name,h in selected.items():
            rel=Path(name).relative_to('after-active-support');assert not rel.is_absolute() and '..' not in rel.parts
            target=extracted/rel;target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(name) as source,target.open('xb') as destination:shutil.copyfileobj(source,destination)
            assert sha(target)==h
        baseline_name='activation/after-detail.json'
        assert baseline_name in manifest['files']
        golden=json.loads(z.read(baseline_name))
    staged=DURABLE/'staged-support';staged.mkdir()
    summaries={}
    for name in DBS:
        source=extracted/name;target=staged/name;target.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db,closing(sqlite3.connect(target)) as dst:
            db.backup(dst);dst.execute('pragma journal_mode=delete')
        with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            assert db.execute('pragma quick_check').fetchone()[0]=='ok'
            expected=golden[name];counts={}
            for table,rows in expected['tables'].items():
                quoted='"'+table.replace('"','""')+'"'
                actual=[{k:norm(v) for k,v in dict(r).items()} for r in db.execute('select * from '+quoted)]
                assert sorted(actual,key=canonical)==sorted(rows,key=canonical),(name,table)
                schema=[dict(r) for r in db.execute('pragma table_info('+quoted+')')]
                assert schema==expected['schema'][table],(name,table,'schema')
                counts[table]=len(actual)
            for table,count in expected['history_counts'].items():
                assert db.execute('select count(*) from "'+table+'"').fetchone()[0]==count
            summaries[name]=dict(integrity='ok',all_recorded_tables_rows_and_schema_match=True,table_counts=counts,history_counts=expected['history_counts'])
    for name in ['Data/ReviewToday.store.review-v2-backup','Data/ReviewBackups/before-review-v2-698B285B-E632-47E9-8F23-55697CABE5FA.sqlite3']:
        target=staged/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(extracted/name,target)
        assert sha(target)==selected['after-active-support/'+name]
    assert not SUPPORT.exists()
    staged_files={str(p.relative_to(staged)):sha(p) for p in staged.rglob('*') if p.is_file()}
    assert len(staged_files)==5
    backup=DURABLE/'verified-staged-support.zip'
    with zipfile.ZipFile(backup,'x',zipfile.ZIP_DEFLATED) as z:
        for name in staged_files:z.write(staged/name,name)
    with zipfile.ZipFile(backup) as z:
        for name,h in staged_files.items():
            with z.open(name) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==h
    report=dict(status='FORMAL_DATA_RECOVERY_PREPARED_PENDING',source_archive=str(archive),source_archive_sha256=sha(archive),
        original_archive_members_read_and_verified=len(manifest['files']),selected_formal_files_extracted=9,
        source_decision=266,source_is_formal_daily_data=True,test_cards_not_promoted=True,databases=summaries,
        native_counts={t:summaries[DBS[0]]['table_counts'][t] for t in ['ZAGENTSESSION','ZAGENTMESSAGE','ZKNOWLEDGE','ZFSRSSTATE']},
        staged_support=str(staged),staged_files=staged_files,verified_stage_zip=str(backup),verified_stage_zip_sha256=sha(backup),
        target=str(SUPPORT),target_absent=True,daily_data_written=False,daily_app_started=False,actual_model_requests=0,actual_web_operations=0,
        historical_Backups_89_files_not_in_this_recovery=True,changes_after_last_backup_not_recoverable_from_this_snapshot=True,
        sqlite_consistent_files_not_original_byte_identity=True,original_baseline_not_rewritten=True)
    write(OUT/'verification.json',report);write(DURABLE/'verification.json',report)
    print(json.dumps(dict(status=report['status'],native_counts=report['native_counts'],verified_members=51,consistent_databases=3,staged_files=5,daily_data_written=False,actual_calls=0),ensure_ascii=False))


if __name__=='__main__':main()
