"""Prepared execution only. Both human approval holds reject before daily access."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid
from approval import require_approved
from prepare import ROOT, OUT, PRIVATE, ARCHIVE, DAILY, SUPPORT, DBS, sha, app_files, stopped, write


def load_tool():
    source=ROOT/'tools/repair-legacy-deletion-lifecycle.py'
    spec=importlib.util.spec_from_file_location('fixed_legacy_scope',source)
    tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    return tool


def publish_metadata(source,target,tool):
    """Publish exactly the three checked changes; never replace an entire daily DB."""
    scope=tool.load_scope()
    with closing(tool.readonly(source)) as src:
        prepared=tool.table_snapshot(src);tool.selected_payloads(src,scope,already_applied=True)
        source_schema=src.execute("select type,name,tbl_name,sql from sqlite_master where name not like 'sqlite_%' order by name").fetchall()
    with closing(sqlite3.connect(target,timeout=1)) as dst:
        try:
            dst.execute('begin immediate')
            before=tool.table_snapshot(dst);selected=tool.selected_payloads(dst,scope)
            if dst.execute("select type,name,tbl_name,sql from sqlite_master where name not like 'sqlite_%' order by name").fetchall()!=source_schema:raise RuntimeError('Service schema changed')
            expected=json.loads(tool.canonical(before));new_payloads=dict(prepared['agent_sessions_v2'])
            for row in expected['agent_sessions_v2']:
                if row[0] in selected:row[1]=new_payloads[row[0]]
            expected['agent_sessions_v2'].sort(key=tool.canonical)
            if expected!=prepared:raise RuntimeError('Prepared copy contains unrelated data changes')
            for sid,(raw,_) in selected.items():
                count=dst.execute('update agent_sessions_v2 set payload=? where session_id=? and payload=?',(new_payloads[sid],sid,raw)).rowcount
                if count!=1:raise RuntimeError('Service record changed')
            if tool.table_snapshot(dst)!=expected:raise RuntimeError('Unexpected data changes; transaction rejected')
            dst.commit()
        except BaseException:dst.rollback();raise


def main():
    if sys.argv[1:]!=['--apply-approved']:raise PermissionError('Explicit approved execution mode required')
    require_approved()  # Before any runtime imports, daily SQLite access or writes.
    stopped()
    if (PRIVATE/'execution.json').exists():raise RuntimeError('Execution already has retained state; inspect it before continuing')
    before=json.loads((PRIVATE/'source-protection.json').read_text())
    if app_files(DAILY)!=before['app_files'] or not all(sha(Path(p))==h for p,h in before['daily_files'].items()):raise RuntimeError('Daily data or App changed; stop and prepare a new snapshot')
    if {str(p) for p in SUPPORT.rglob('*') if p.is_file()}!=set(before['daily_files']):raise RuntimeError('Daily file set changed')
    candidate=json.loads((OUT/'candidate.json').read_text())
    if sha(Path(candidate['zip']))!=candidate['zip_sha256']:raise RuntimeError('Candidate archive changed')
    backup=json.loads((OUT/'backup.json').read_text())
    if sha(Path(backup['old_app_zip']))!=backup['old_app_zip_sha256']:raise RuntimeError('Rollback application archive changed')
    fixed=json.loads((ROOT/'docs/evidence/2026-10-22-legacy-lifecycle-repair/result.json').read_text())
    if sha(PRIVATE/'fresh-input/NativeQueueAudit')!=fixed['native_driver_sha256'] or sha(Path('/tmp/review-today-shared-contracts.j3r_7v6g/libReviewTodayContractSupport.dylib'))!=fixed['shared_native_module_sha256']:
        raise RuntimeError('The reviewed cleanup components are unavailable or changed')
    for p,value in json.loads((PRIVATE/'backup-file-pins.json').read_text()).items():
        if sha(Path(p))!=value:raise RuntimeError('Prepared data backup changed')
    work=ROOT/'output/legacy-lifecycle-repair-2026-10-22'/('approved-'+uuid.uuid4().hex);work.mkdir()
    for name in DBS.values():shutil.copy2(PRIVATE/'fresh-input'/name,work/name)
    shutil.copy2(PRIVATE/'fresh-input/pre-sept7-archive-proof.store',work/'archive-proof.store')
    stage=ARCHIVE/('approved-stage-'+uuid.uuid4().hex+'.noindex');stage.mkdir()
    subprocess.run(['ditto','-x','-k',candidate['zip'],str(stage)],check=True)
    new_app=stage/'Review_Today.app'
    if app_files(new_app)!=candidate['inventory']:raise RuntimeError('Candidate files changed')
    subprocess.run(['codesign','--verify','--deep','--strict',str(new_app)],check=True)
    tool=load_tool();receipt=tool.repair(work,apply=True)
    if receipt['written_records']!=3:raise RuntimeError('Expected the original three-record reconstruction')
    write(PRIVATE/'execution.json',dict(phase='staged_no_daily_write',work=str(work)))
    stopped();publish_metadata(work/'checkpoint.sqlite3',SUPPORT/'agent-harness.sqlite3',tool)
    write(PRIVATE/'execution.json',dict(phase='metadata_published',work=str(work)))
    from cleanup_backend import cleanup
    cleanup(work)
    write(PRIVATE/'execution.json',dict(phase='backend_cleaned_app_not_installed',work=str(work)))
    stopped()
    previous=stage/'previous-daily.app'
    DAILY.rename(previous)
    try:new_app.rename(DAILY)
    except BaseException:
        if not DAILY.exists():previous.rename(DAILY)
        raise
    if app_files(DAILY)!=candidate['inventory']:raise RuntimeError('Installed candidate verification failed')
    ls='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
    subprocess.run([ls,'-f',str(DAILY)],check=True)
    shutil.rmtree(previous);stage.rmdir()  # Both packages remain recoverable from verified ZIP archives.
    write(PRIVATE/'execution.json',dict(phase='backend_cleaned_app_installed',work=str(work),app_started=False,actual_model_requests=0))
    print('Daily backend cleaned; exact candidate installed. App not started; bounded startup check remains.')


if __name__=='__main__':main()
