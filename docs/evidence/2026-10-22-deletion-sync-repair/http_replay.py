"""Actual native cleanup -> loopback -> production routes; no lifespan/probes/LLM."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
setup = json.loads((OUT/'setup.json').read_text())
directory = Path(setup['directory']).resolve()
os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/'import.sqlite3'), OPENAI_API_KEY='', DEEPSEEK_API_KEY='',
    REVIEW_TODAY_LLM_PROVIDER='openai_compatible', REVIEW_TODAY_JEV_TEST='0',
    REVIEW_TODAY_SEARCH_PROVIDER='none', REVIEW_TODAY_READ_PROVIDER='local')
denied = []


def audit(event, values):
    if event == 'socket.connect' and not (isinstance(values[1],tuple) and values[1][0]=='127.0.0.1'):
        denied.append(event); raise AssertionError('External network is forbidden')
    if event == 'sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(directory):
        denied.append(event); raise AssertionError('SQLite outside isolated replay')


sys.addaudithook(audit)
sys.path.insert(0,str(ROOT/'agent-service'))
from fastapi.testclient import TestClient
from agent_service import main, openai_client
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore


def no_models(*args,**kwargs):
    denied.append('model'); raise AssertionError('No model calls or probes in deletion replay')


openai_client._client = no_models
main.start_probe = no_models
main.resume_incomplete_tasks = no_models
client = TestClient(main.app)  # No context manager: do not execute startup/lifespan.
current = None
requests = []
ack_lost = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        global ack_lost
        assert self.path == '/v2/sessions/'+current['marker']['session_id']+'/actions'
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if current['scenario']=='archive_failure_v2' and body['action']=='archive':
            status,result = 503,dict(detail=dict(error_code='RT.HARNESS.SERVICE_UNAVAILABLE'))
        else:
            response = client.post(self.path,json=body)
            status,result = response.status_code,response.json()
            if current['scenario']=='lost_ack_v2' and body['action']=='delete' and status==200 and not ack_lost:
                ack_lost = True
                status,result = 503,dict(detail=dict(error_code='RT.HARNESS.SERVICE_UNAVAILABLE'))
        requests.append(dict(action=body['action'],revision=body['lifecycle_revision'],action_id=body['action_id'],status=status,
            error=(result.get('detail') or {}).get('error_code')))
        data = json.dumps(result).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)


def native_tables(path):
    with sqlite3.connect(path) as db:
        return {t:db.execute('select * from '+t).fetchall() for t in
            ['ZKNOWLEDGE','ZAGENTMESSAGE','ZSOURCE','ZQUESTION','ZFSRSSTATE','ZREVIEWSESSION','ZREVIEWATTEMPT','ZAGENTSESSION','ZLEARNINGTASK']}


server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
assert server.server_port != 8742
threading.Thread(target=server.serve_forever,daemon=True).start()
results = []
run_directory = directory/('http-replay-'+str(uuid.uuid4()))
run_directory.mkdir()
try:
    for scenario in ['real','active_v2','lost_ack_v2','active_v1','stale_v1','archive_failure_v2']:
        work = run_directory/scenario;work.mkdir()
        if scenario=='real':
            shutil.copy2(directory/'app.store',work/'app.store');shutil.copy2(directory/'checkpoint.sqlite3',work/'checkpoint.sqlite3')
            marker = json.loads((directory/'real-config.json').read_text())['marker']
            before_native = native_tables(work/'app.store')
        else:
            marker = dict(session_id=str(uuid.uuid4()),action_id=str(uuid.uuid4()),archive_action_id=str(uuid.uuid4()),
                          action='delete',lifecycle_revision=1 if scenario.endswith('v1') else 2,cleaned=False)
        tasks = HarnessStore(str(work/'checkpoint.sqlite3'))
        store = ConversationStore(tasks);harness = ConversationHarness(store)
        main.harness_store,main.conversation_harness = tasks,harness
        sid = marker['session_id']
        if scenario!='real':
            with store.transaction(sid) as data:
                data.update(status='archived' if scenario=='stale_v1' else 'active',lifecycle_revision=1 if scenario=='stale_v1' else 0)
        else:
            with sqlite3.connect(work/'checkpoint.sqlite3') as db:
                before_sessions = db.execute('select * from agent_sessions_v2').fetchall()
            bad = client.post('/v2/sessions/'+sid+'/actions',json=dict(action_id=marker['archive_action_id'],action='archive',lifecycle_revision=0))
            assert bad.status_code==409 and bad.json()['detail']['error_code']=='RT.SESSION.INVALID_ACTION'
        current = dict(scenario=scenario,marker=marker)
        (work/'config.json').write_text(json.dumps(current))
        requests.clear();ack_lost=False
        (directory/'isolated-home').mkdir(exist_ok=True)
        env = dict(os.environ,CFFIXED_USER_HOME=str(directory/'isolated-home'))
        completed = subprocess.run([sys.argv[1],str(work),f'http://127.0.0.1:{server.server_port}'],env=env,capture_output=True,text=True,timeout=60)
        (work/'native.log').write_text(completed.stdout+completed.stderr)
        assert completed.returncode==0,scenario+': inspect private native.log'
        actual = json.loads((work/'native-result.json').read_text())
        expected = {'real':[('delete',1,200)],'active_v2':[('archive',1,200),('delete',2,200)],
            'lost_ack_v2':[('archive',1,200),('delete',2,503),('archive',1,409),('delete',2,200)],
            'active_v1':[('delete',1,409)],'stale_v1':[('delete',1,409)],'archive_failure_v2':[('archive',1,503)]}[scenario]
        assert [(r['action'],r['revision'],r['status']) for r in requests] == expected
        if scenario=='real':
            assert native_tables(work/'app.store') == before_native
            with sqlite3.connect(work/'checkpoint.sqlite3') as db:
                assert db.execute('select * from agent_sessions_v2').fetchall()==before_sessions
                assert db.execute('select count(*) from harness_tasks where session_id=?',(sid,)).fetchone()[0]==0
        if scenario=='active_v1':assert requests[0]['error']=='RT.SESSION.NOT_ARCHIVED'
        if scenario=='stale_v1':assert requests[0]['error']=='RT.SESSION.VERSION_CONFLICT'
        if scenario=='lost_ack_v2':
            assert requests[0]['action_id']==requests[2]['action_id'] and requests[1]['action_id']==requests[3]['action_id']
        if actual['cleared']:
            assert store.deleted(sid) and store.get(sid) is None
            duplicate = client.post('/v2/sessions/'+sid+'/actions',json=marker)
            assert duplicate.status_code==200 and duplicate.json()['status']=='deleted'
        else:
            assert not store.deleted(sid) and store.get(sid) is not None
        results.append(dict(scenario=scenario,outcome='PASS',cleared=actual['cleared'],sequence=[{k:v for k,v in r.items() if k!='action_id'} for r in requests],
            pending_before=actual['pending_before'],pending_after=actual['pending_after'],
            unrelated_marker_requests_blocked=actual['unrelated_marker_requests_blocked'],expected_native_state_retained=True,model_requests=0,web_operations=0))
        print('PASS isolated native / production HTTP:',scenario,flush=True)
    assert not denied
    (OUT/'http-result.json').write_text(json.dumps(dict(outcome='PASS',directory=str(run_directory),scenarios=results,external_network_attempts=0,
        actual_model_requests=0,actual_web_operations=0,daily_app_launched=False,daily_cleanup=False),indent=2)+'\n')
finally:
    server.shutdown();server.server_close()
