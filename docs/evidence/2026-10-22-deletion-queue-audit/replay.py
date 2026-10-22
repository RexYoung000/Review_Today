"""Audit the existing queue on fresh copies; never enter lifespan or daily databases."""
from pathlib import Path
import os,sys,json,sqlite3,shutil,subprocess,threading,uuid,hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[3]
PRIVATE=ROOT/'output/deletion-queue-audit-2026-10-22'
SIMULATE='--simulate-legacy-metadata' in sys.argv
WORK=PRIVATE/(('simulation-' if SIMULATE else 'replay-')+uuid.uuid4().hex);WORK.mkdir()
for name in ['app.store','checkpoint.sqlite3','review.sqlite3']:
    with sqlite3.connect((PRIVATE/name).as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(WORK/name) as dest:source.backup(dest)
os.environ.update(REVIEW_TODAY_HARNESS_DB=str(WORK/'import.sqlite3'),OPENAI_API_KEY='',DEEPSEEK_API_KEY='',
    REVIEW_TODAY_LLM_PROVIDER='openai_compatible',REVIEW_TODAY_JEV_TEST='0',REVIEW_TODAY_SEARCH_PROVIDER='none',REVIEW_TODAY_READ_PROVIDER='local')
denied=[]
def audit(event,values):
    if event=='socket.connect' and not (isinstance(values[1],tuple) and values[1][0]=='127.0.0.1'):
        denied.append(event);raise AssertionError('External network forbidden')
    if event=='sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(WORK):
        denied.append(event);raise AssertionError('Only fresh isolated database copies')
sys.addaudithook(audit)
sys.path.insert(0,str(ROOT/'agent-service'))
from fastapi.testclient import TestClient
from agent_service import main,openai_client
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore

def forbidden(*args,**kwargs):
    denied.append('models_or_startup');raise AssertionError('No models, probe or startup')
openai_client._client=forbidden
main.start_probe=forbidden;main.resume_incomplete_tasks=forbidden
client=TestClient(main.app)  # Intentionally no lifespan/context manager.
tasks=HarnessStore(str(WORK/'checkpoint.sqlite3'));store=ConversationStore(tasks)
main.harness_store=tasks;main.conversation_harness=ConversationHarness(store)
markers=json.loads((PRIVATE/'pending-markers.json').read_text());allowed={m['session_id']:m for m in markers}
if SIMULATE:
    proof=json.loads((PRIVATE/'legacy-proof.json').read_text())
    assert len(proof)==3
    with sqlite3.connect(WORK/'checkpoint.sqlite3') as db:
        for record in proof:
            sid=record['session_id'];marker=allowed[sid]
            assert record['old_native_status']=='archived' and record['old_native_revision']==0 and marker['lifecycle_revision']==1
            row=db.execute('select payload from agent_sessions_v2 where session_id=?',(sid,)).fetchone()
            payload=json.loads(row[0]);assert 'status' not in payload and 'lifecycle_revision' not in payload
            payload.update(status='archived',lifecycle_revision=0)
            db.execute('update agent_sessions_v2 set payload=? where session_id=?',(json.dumps(payload,ensure_ascii=False),sid))
requests=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        sid=self.path.split('/')[-2];assert sid in allowed and self.path=='/v2/sessions/'+sid+'/actions'
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        marker=allowed[sid]
        if body['action']=='archive':
            assert SIMULATE and marker['lifecycle_revision']>1 and body['action_id']==marker['archive_action_id'] and body['lifecycle_revision']==marker['lifecycle_revision']-1
        else:
            assert body['action']=='delete' and body['action_id']==marker['action_id'] and body['lifecycle_revision']==marker['lifecycle_revision']
        response=client.post(self.path,json=body)
        result=response.json();requests.append(dict(session_id=sid,action=body['action'],revision=body['lifecycle_revision'],status=response.status_code,
            error=(result.get('detail') or {}).get('error_code')))
        data=json.dumps(result).encode();self.send_response(response.status_code);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);assert server.server_port!=8742
threading.Thread(target=server.serve_forever,daemon=True).start()
def table_rows(path):
    with sqlite3.connect(path) as db:
        return {t:dict(columns=[c[1] for c in db.execute('pragma table_info(\"'+t+'\")')],rows=db.execute('select * from \"'+t+'\" order by Z_PK').fetchall()) for t, in db.execute("select name from sqlite_master where type='table' and name like 'Z%'") if not t.startswith('Z_')}
before_native=table_rows(WORK/'app.store')
with sqlite3.connect(WORK/'checkpoint.sqlite3') as db:before_service={t:db.execute('select * from '+t).fetchall() for t, in db.execute("select name from sqlite_master where type='table'")}
try:
    (WORK/'native-home').mkdir()
    env=dict(os.environ,CFFIXED_USER_HOME=str(WORK/'native-home'))
    result=subprocess.run([str(PRIVATE/'NativeQueueAudit'),str(WORK),f'http://127.0.0.1:{server.server_port}'],env=env,capture_output=True,text=True,timeout=60)
    (WORK/'native.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,'inspect private native.log'
    native=json.loads((WORK/'native-result.json').read_text())
    expected_cleaned=37 if SIMULATE else 3
    assert native['cleaned_in_copy']==expected_cleaned and native['pending_after']==37-expected_cleaned
    if SIMULATE:
        assert len(requests)==68
        assert all(r['status']==200 for r in requests if r['action']=='delete')
        assert all(r['status']==200 or r['error']=='RT.SESSION.VERSION_CONFLICT' for r in requests)
    else:
        assert [r['status'] for r in requests]==[200,200,200,409]
        assert requests[-1]['error']=='RT.SESSION.NOT_ARCHIVED' and requests[-1]['session_id']==markers[3]['session_id']
    after_native=table_rows(WORK/'app.store')
    setting_indexes=[i for i,c in enumerate(before_native['ZAPPSETTINGS']['columns']) if c not in {'Z_OPT','ZSESSIONDELETIONSJSON'}]
    after_indexes=[after_native['ZAPPSETTINGS']['columns'].index(before_native['ZAPPSETTINGS']['columns'][i]) for i in setting_indexes]
    assert [tuple(row[i] for i in setting_indexes) for row in before_native['ZAPPSETTINGS']['rows']]==[tuple(row[i] for i in after_indexes) for row in after_native['ZAPPSETTINGS']['rows']]
    added_columns={}
    for table,before in before_native.items():
        if table=='ZAPPSETTINGS':continue
        after=after_native[table]
        indexes=[after['columns'].index(c) for c in before['columns']]
        assert before['rows']==[tuple(row[i] for i in indexes) for row in after['rows']],table
        for c in after['columns']:
            if c not in before['columns']:
                added_columns[table+'.'+c]=sorted(set(str(row[after['columns'].index(c)]) for row in after['rows']))
    with sqlite3.connect(WORK/'checkpoint.sqlite3') as db:
        after_service={t:db.execute('select * from '+t).fetchall() for t in before_service}
    assert len(after_service['agent_session_deletions'])==expected_cleaned
    service_changes=[t for t in before_service if before_service[t]!=after_service[t]]
    cleaned_ids={m['session_id'] for m in markers[:expected_cleaned]}
    expected_tables={'agent_session_deletions','harness_tasks','agent_memory_policy_v2'} | ({'agent_sessions_v2'} if SIMULATE else set())
    assert set(service_changes)==expected_tables,service_changes
    for table,index in [('harness_tasks',1),('agent_memory_policy_v2',0),('agent_sessions_v2',0)]:
        assert after_service[table]==[row for row in before_service[table] if row[index] not in cleaned_ids],table
    assert {row[0] for row in after_service['agent_session_deletions']}==cleaned_ids
    removed_counts={t:len(before_service[t])-len(after_service[t]) for t in ['harness_tasks','agent_memory_policy_v2','agent_sessions_v2']}
    assert not denied
    report=dict(outcome='COUNTERFACTUAL_PASS' if SIMULATE else 'CONFIRMED_BLOCKER',work_directory=str(WORK),pending_before=37,
        pending_after_in_copy=37-expected_cleaned,cleaned_in_copy=expected_cleaned,request_statuses=[r['status'] for r in requests],
        legacy_archive_metadata_reconstructed_in_copy=3 if SIMULATE else 0,
        blocked_marker_number=None if SIMULATE else 4,error=None if SIMULATE else requests[-1]['error'],
        all_original_native_business_fields_unchanged=True,additive_native_schema_defaults=added_columns,service_changes=service_changes,
        removed_counts_in_copy=removed_counts,all_other_service_rows_unchanged=True,
        later_33_markers_not_attempted=not SIMULATE,daily_cleanup=False,daily_app_updated=False,
        model_requests=0,web_operations=0,external_network_attempts=0,production_compatibility_change_implemented=False)
    (Path(__file__).parent/('simulation-result.json' if SIMULATE else 'replay-result.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
finally:
    server.shutdown();server.server_close()
