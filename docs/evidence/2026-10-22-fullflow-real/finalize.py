"""Freeze and preserve this completed isolated run; no App/model launch."""
import importlib.util,json,os,shutil,sqlite3,subprocess,sys
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
PRIVATE=ROOT/'output/fullflow-real-2026-10-22'
spec=importlib.util.spec_from_file_location('held_prepare',ROOT/'docs/evidence/2026-10-22-fullflow-preflight/prepare.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
s=m.read(ROOT/'docs/evidence/2026-10-22-fullflow-preflight/setup.json');r=Path(s['directory']);app=Path(s['native_app'])
assert (r/'STOP').exists() and m.read(r/'quota.json')['model_requests']==25
assert subprocess.run(['pgrep','-x','FreshFullflowQA'],capture_output=True).returncode==1
assert not subprocess.run(['lsof','-nP','-iTCP:'+str(s['port']),'-sTCP:LISTEN'],capture_output=True).stdout
m.stopped()
assert m.read(r/'native-disk-read.json')['layer']=='fresh_process_swiftdata_read_after_app_quit'
archive=Path.home()/'Library/Developer/ReviewTodayAppArchives.noindex/2026-10-22-fullflow-real/FreshFullflowQA.zip'
assert app.exists()
archive.parent.mkdir(mode=0o700,exist_ok=True)
inv=m.app_files(app);assert inv==s['native_bundle_inventory']
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
if not archive.exists():subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
check=r/'final-archive-check.noindex'
if not check.exists():
    check.mkdir()
    subprocess.run(['ditto','-x','-k',str(archive),str(check)],check=True)
assert m.app_files(check/app.name)==inv
subprocess.run(['codesign','--verify','--deep','--strict',str(check/app.name)],check=True)
unregister=[]
for target in [app,check/app.name]:
    res=subprocess.run([m.LS,'-u',str(target)],capture_output=True,text=True)
    assert res.returncode in [0,1]
    unregister.append(dict(path=str(target),returncode=res.returncode,output=res.stdout+res.stderr))
# An extracted copy may never have been registered. Final registry check is independent.
(PRIVATE/'targeted-unregister.json').write_text(json.dumps(unregister,ensure_ascii=False,indent=2))
# Only verified disposable QA bundle copies; the archive and data are retained.
shutil.rmtree(check);shutil.rmtree(app)
PRIVATE.mkdir(parents=True,exist_ok=True);os.chmod(PRIVATE,0o700)
for name in ['authorization.json','quota.json','STOP','live-events.jsonl','native-recheck-events.jsonl','native-disk-read.json']:
    shutil.copy2(r/name,PRIVATE/name)
shadow=PRIVATE/'disk-final';shadow.mkdir()
for pat in ['app.store*','checkpoint.sqlite3*']:
    for item in r.glob(pat):
        if item.is_file():shutil.copy2(item,shadow/item.name)
with closing(sqlite3.connect((shadow/'checkpoint.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
    assert db.execute('pragma quick_check').fetchall()==[('ok',)]
    tables={x[0] for x in db.execute("select name from sqlite_master where type='table'")}
    counts={t:db.execute('select count(*) from '+t).fetchone()[0] for t in sorted(tables) if not t.startswith('sqlite_')}
with closing(sqlite3.connect((shadow/'app.store').as_uri()+'?mode=ro',uri=True)) as db:
    assert db.execute('pragma quick_check').fetchall()==[('ok',)]
    native={t:db.execute('select count(*) from '+t).fetchone()[0] for t in ['ZKNOWLEDGE','ZSOURCE','ZAGENTMESSAGE','ZLEARNINGTASK','ZAGENTRUN','ZAGENTSESSION','ZFSRSSTATE']}
report=dict(status='QA_CLOSED_ARCHIVED',archive=str(archive),archive_sha256=m.sha(archive),inventory_matched=True,actual_extract_and_signature_verified=True,raw_qa_removed=True,owned_qa_and_service_stopped=True,normal_app_not_started=True,native_counts=native,service_counts=counts)
m.write(OUT/'cleanup.json',report)
print(json.dumps(report,ensure_ascii=False))
