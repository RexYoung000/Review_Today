"""Persist actual owned-QA observations and consistent DB copies, without transport.

Each capture is immutable. DB backups are separately consistent, not an atomic
cross-store transaction. Captures do not establish a gate pass on their own.
"""
from contextlib import closing
import argparse
import os
import re
import shutil
import sqlite3
import zipfile
from common import *


def capture(phase):
    assert re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',phase)
    state=read(OUT/'setup.json');runtime=Path(state['directory']).resolve()
    assert runtime.parent==Path('/private/tmp') and runtime.name.startswith('review-today-')
    target=DURABLE/'captures'/phase
    assert not target.exists(),'Never overwrite a capture'
    target.mkdir(parents=True,mode=0o700)
    no_external_runtime(runtime,owned_backups=(target,))
    databases={}
    for name in ['app.store','checkpoint.sqlite3','review.sqlite3']:
        source=runtime/name
        if not source.exists():continue
        assert source.is_file() and not source.is_symlink()
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db:
            with closing(sqlite3.connect(target/name)) as backup:
                db.backup(backup)
                assert backup.execute('pragma quick_check').fetchall()==[('ok',)]
                databases[name]={t:backup.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0]
                    for t, in backup.execute("select name from sqlite_master where type='table'")}
    # Do not follow interpreter or library symlinks. Copy observable files only.
    excluded={'.venv','support','native-home','__pycache__'}
    for base,dirs,names in os.walk(runtime,followlinks=False):
        dirs[:]=[n for n in dirs if n not in excluded and not n.endswith('.app') and not (Path(base)/n).is_symlink()]
        for name in names:
            p=Path(base)/name
            if p.is_symlink() or not p.is_file() or p.name.startswith(('app.store','checkpoint.sqlite3','review.sqlite3')):continue
            if p.suffix not in {'.json','.jsonl','.log','.txt','.png','.py'} and name not in {'HOLD','STOP'}:continue
            destination=target/'observations'/p.relative_to(runtime)
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,destination)
    members={str(p.relative_to(target)):sha(p) for p in target.rglob('*') if p.is_file()}
    archive=DURABLE/'captures'/(phase+'.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name in members:z.write(target/name,name)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist())==set(members)
        assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in members.items())
    result=dict(phase=phase,archive=str(archive),sha256=sha(archive),members=members,actual_members_read=len(members),
        databases=databases,cross_database_atomic_snapshot=False,provider_requests_started=0,
        original_runtime_data_not_rewritten=True)
    write(target/'capture.json',result)
    write(PRIVATE/('capture-'+phase+'.json'),result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase');args=parser.parse_args()
    result=capture(args.phase);print('Durable capture '+args.phase+': '+str(result['actual_members_read'])+' members verified')
