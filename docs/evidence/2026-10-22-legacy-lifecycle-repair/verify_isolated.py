"""Exercise the actual fixed-scope CLI, then the unchanged native/HTTP queue."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
INPUT = ROOT/'output/deletion-queue-audit-2026-10-22'
WORK = ROOT/'output/legacy-lifecycle-repair-2026-10-22'/('real-'+uuid.uuid4().hex)
WORK.mkdir()
for name in ('app.store','checkpoint.sqlite3','review.sqlite3'):
    with closing(sqlite3.connect((INPUT/name).as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(WORK/name)) as dest:
        source.backup(dest)
shutil.copy2(INPUT/'pre-sept7-archive-proof.store',WORK/'archive-proof.store')

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def sql_tables(path):
    with closing(sqlite3.connect(path)) as db:
        return {t:db.execute('select * from "'+t+'"').fetchall() for t, in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}

original_native_sha = digest(WORK/'app.store')
before_service = sql_tables(WORK/'checkpoint.sqlite3')
before_review = sql_tables(WORK/'review.sqlite3')
tool_results = []
for label,apply in [('check',False),('apply',True),('repeat',True)]:
    args = ['python3',str(ROOT/'tools/repair-legacy-deletion-lifecycle.py'),'--work-dir',str(WORK)]
    if apply:args.append('--apply')
    run = subprocess.run(args,capture_output=True,text=True,timeout=60)
    (WORK/(label+'.log')).write_text(run.stdout+run.stderr)
    assert run.returncode == 0,'inspect isolated CLI log: '+label
    report = json.loads(run.stdout)
    assert report['status'] == {'check':'ready','apply':'applied','repeat':'already_applied'}[label]
    tool_results.append(report)
    if not apply:assert sql_tables(WORK/'checkpoint.sqlite3') == before_service
    assert digest(WORK/'app.store') == original_native_sha
with closing(sqlite3.connect(WORK/'app.store')) as db:
    markers = json.loads(db.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchone()[0])
    before_native = {t:dict(columns=[c[1] for c in db.execute('pragma table_info("'+t+'")')],rows=db.execute('select * from "'+t+'" order by Z_PK').fetchall())
                     for t, in db.execute("select name from sqlite_master where type='table' and name like 'Z%'") if not t.startswith('Z_')}
with closing(sqlite3.connect(WORK/'compatibility-backup/checkpoint.sqlite3')) as db:
    original_backed_up = {t:db.execute('select * from "'+t+'"').fetchall() for t in before_service}
assert original_backed_up == before_service
scope = json.loads((ROOT/'tools/legacy-deletion-lifecycle-scope.json').read_text())
patched = sql_tables(WORK/'checkpoint.sqlite3')
assert [k for k in patched if patched[k] != before_service[k]] == ['agent_sessions_v2']
old_payloads = dict(before_service['agent_sessions_v2'])
for sid,raw in patched['agent_sessions_v2']:
    if sid in {r['session_id'] for r in scope['records']}:
        p = json.loads(raw);assert p.pop('status') == 'archived' and p.pop('lifecycle_revision') == 0
        assert p == json.loads(old_payloads[sid])
    else:assert raw == old_payloads[sid]

os.environ.update(REVIEW_TODAY_HARNESS_DB=str(WORK/'import.sqlite3'),OPENAI_API_KEY='',DEEPSEEK_API_KEY='',
    REVIEW_TODAY_LLM_PROVIDER='openai_compatible',REVIEW_TODAY_JEV_TEST='0',REVIEW_TODAY_SEARCH_PROVIDER='none',REVIEW_TODAY_READ_PROVIDER='local')
denied = []
def audit(event,values):
    if event == 'socket.connect' and not (isinstance(values[1],tuple) and values[1][0] == '127.0.0.1'):
        denied.append(event);raise AssertionError('External network forbidden')
    if event == 'sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(WORK):
        denied.append(event);raise AssertionError('Only the fresh isolated workspace is allowed')
sys.addaudithook(audit)
sys.path.insert(0,str(ROOT/'agent-service'))
from fastapi.testclient import TestClient
from agent_service import main,openai_client
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore

def forbidden(*args,**kwargs):
    denied.append('model_or_startup');raise AssertionError('No models, startup or probes')
openai_client._client = forbidden
main.start_probe = forbidden;main.resume_incomplete_tasks = forbidden
client = TestClient(main.app)  # No lifespan/context-manager startup.
tasks = HarnessStore(str(WORK/'checkpoint.sqlite3'));store = ConversationStore(tasks)
main.harness_store = tasks;main.conversation_harness = ConversationHarness(store)
allowed = {m['session_id']:m for m in markers}
requests = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        sid = self.path.split('/')[-2]
        assert sid in allowed and self.path == '/v2/sessions/'+sid+'/actions'
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        marker = allowed[sid]
        archive = body['action'] == 'archive'
        assert body['action_id'] == marker['archive_action_id' if archive else 'action_id']
        assert body['lifecycle_revision'] == marker['lifecycle_revision']-(1 if archive else 0)
        assert not archive or marker['lifecycle_revision'] > 1
        response = client.post(self.path,json=body);value = response.json()
        requests.append(dict(action=body['action'],status=response.status_code,error=(value.get('detail') or {}).get('error_code')))
        data = json.dumps(value).encode();self.send_response(response.status_code);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server = ThreadingHTTPServer(('127.0.0.1',0),Handler);assert server.server_port != 8742
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    (WORK/'native-home').mkdir()
    executable = INPUT/'NativeQueueAudit'
    module = Path('/tmp/review-today-shared-contracts.j3r_7v6g/libReviewTodayContractSupport.dylib')
    assert digest(module) == 'db4a0a68cdf01bd9582d9ad2ef9f54911d251953bc4fb076506d3b75830aedcd'
    pins = json.loads((ROOT/'docs/evidence/2026-10-22-deletion-sync-repair/source-pins.json').read_text())
    assert digest(ROOT/'Review_Today/SessionDeletion.swift') == pins['Review_Today/SessionDeletion.swift']
    run = subprocess.run([str(executable),str(WORK),f'http://127.0.0.1:{server.server_port}'],
        env=dict(os.environ,CFFIXED_USER_HOME=str(WORK/'native-home')),capture_output=True,text=True,timeout=60)
    (WORK/'native.log').write_text(run.stdout+run.stderr)
    assert run.returncode == 0,'inspect isolated native.log'
    native = json.loads((WORK/'native-result.json').read_text())
    assert native['pending_before'] == 37 and native['pending_after'] == 0 and native['all_other_marker_fields_retained']
    assert len(requests) == 68 and sum(r['action'] == 'delete' and r['status'] == 200 for r in requests) == 37
    assert all(r['status'] == 200 or (r['action'] == 'archive' and r['error'] == 'RT.SESSION.VERSION_CONFLICT') for r in requests)
    with closing(sqlite3.connect(WORK/'app.store')) as db:
        persisted = json.loads(db.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchone()[0])
        assert len(persisted) == 37 and all(m['cleaned'] for m in persisted)
        assert [dict(m,cleaned=False) for m in persisted] == markers
        defaults = {}
        for table,before in before_native.items():
            cs = [c for c in before['columns'] if table != 'ZAPPSETTINGS' or c not in {'Z_OPT','ZSESSIONDELETIONSJSON'}]
            indexes = [before['columns'].index(c) for c in cs]
            result = db.execute('select '+','.join('"'+c+'"' for c in cs)+' from "'+table+'" order by Z_PK').fetchall()
            assert result == [tuple(row[i] for i in indexes) for row in before['rows']],table
            new = [c[1] for c in db.execute('pragma table_info("'+table+'")') if c[1] not in before['columns']]
            if new:defaults[table] = new
    after_service = sql_tables(WORK/'checkpoint.sqlite3')
    pending_ids = set(allowed)
    for table,index in [('agent_sessions_v2',0),('harness_tasks',1),('agent_memory_policy_v2',0)]:
        assert after_service[table] == [row for row in before_service[table] if row[index] not in pending_ids],table
    assert len(after_service['agent_session_deletions']) == 37
    for row in after_service['agent_session_deletions']:
        m = allowed[row[0]];assert row[1] == m['action_id'] and row[2] == m['lifecycle_revision']
    for table in before_service:
        if table not in {'agent_sessions_v2','harness_tasks','agent_memory_policy_v2','agent_session_deletions'}:
            assert after_service[table] == before_service[table],table
    assert sql_tables(WORK/'review.sqlite3') == before_review
    assert not denied
    report = dict(outcome='PASS',work_directory=str(WORK),actual_fixed_scope_cli=[dict(status=x['status'],written_records=x['written_records']) for x in tool_results],
        consistent_backup_verified=True,native_queue=37,pending_after=0,production_http_requests=68,delete_receipts=37,
        original_action_ids_and_revisions_retained=True,only_approved_metadata_changed_before_cleanup=True,all_other_original_native_fields_unchanged=True,
        all_other_service_rows_unchanged=True,review_database_unchanged=True,additive_schema_defaults_in_test_copy=defaults,
        actual_model_requests=0,actual_web_operations=0,daily_cleanup=False,daily_app_updated=False,
        shared_native_module_sha256=digest(module),native_driver_sha256=digest(executable))
    (OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
finally:
    server.shutdown();server.server_close()
