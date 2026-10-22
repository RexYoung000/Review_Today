"""Only after explicit approval: original actions against the actual daily backend."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import urlsplit,unquote
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from approval import require_approved
from prepare import ROOT, PRIVATE, SUPPORT, sha, write


def cleanup(work):
    require_approved()
    previous = json.loads((ROOT/'docs/evidence/2026-10-22-legacy-lifecycle-repair/result.json').read_text())
    if sha(PRIVATE/'fresh-input/NativeQueueAudit')!=previous['native_driver_sha256'] or sha(Path('/tmp/review-today-shared-contracts.j3r_7v6g/libReviewTodayContractSupport.dylib'))!=previous['shared_native_module_sha256']:
        raise RuntimeError('The fixed native cleanup driver changed')
    database = (SUPPORT/'agent-harness.sqlite3').resolve()
    work = work.resolve()
    with closing(sqlite3.connect(work/'app.store')) as db:
        markers = json.loads(db.execute('select ZSESSIONDELETIONSJSON from ZAPPSETTINGS').fetchone()[0])
    allowed = {m['session_id']:m for m in markers}
    if len(allowed)!=37 or any(m['cleaned'] for m in markers):raise RuntimeError('Unexpected native queue')
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(database),OPENAI_API_KEY='',DEEPSEEK_API_KEY='',
        REVIEW_TODAY_LLM_PROVIDER='openai_compatible',REVIEW_TODAY_JEV_TEST='0',REVIEW_TODAY_SEARCH_PROVIDER='none',REVIEW_TODAY_READ_PROVIDER='local')
    def audit(event,values):
        if event=='socket.connect' and not (isinstance(values[1],tuple) and values[1][0]=='127.0.0.1'):raise RuntimeError('External network forbidden')
        if event=='sqlite3.connect':
            raw=str(values[0]);path=Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).resolve()
            if not (path==database or path.is_relative_to(work)):raise RuntimeError('Database outside approved scope')
    sys.addaudithook(audit);sys.path.insert(0,str(ROOT/'agent-service'))
    from fastapi.testclient import TestClient
    from agent_service import main,openai_client
    from agent_service.conversation import ConversationHarness
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    def forbidden(*args,**kwargs):raise RuntimeError('No model, probes or automatic resume during cleanup')
    openai_client._client=forbidden;main.start_probe=forbidden;main.resume_incomplete_tasks=forbidden
    client=TestClient(main.app)  # Intentionally no lifespan startup.
    tasks=HarnessStore(str(database));store=ConversationStore(tasks)
    main.harness_store=tasks;main.conversation_harness=ConversationHarness(store)
    def rows():
        with closing(sqlite3.connect(database)) as db:
            return {t:db.execute('select * from "'+t+'"').fetchall() for t, in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
    before=rows()
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            sid=self.path.split('/')[-2]
            if sid not in allowed or self.path!='/v2/sessions/'+sid+'/actions':raise RuntimeError('Out-of-scope action')
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if body.get('action') not in {'archive','delete'}:raise RuntimeError('Only the original archive/delete actions are allowed')
            m=allowed[sid];archive=body['action']=='archive'
            if body['action_id']!=m['archive_action_id' if archive else 'action_id'] or body['lifecycle_revision']!=m['lifecycle_revision']-(1 if archive else 0):raise RuntimeError('Original action changed')
            result=client.post(self.path,json=body);value=result.json()
            requests.append(dict(session_id=sid,action=body['action'],status=result.status_code,error=(value.get('detail') or {}).get('error_code')))
            write(work/'actual-backend-requests.json',requests)
            payload=json.dumps(value).encode();self.send_response(result.status_code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    if server.server_port==8742:raise RuntimeError('Unexpected cleanup port')
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        (work/'native-home').mkdir()
        result=subprocess.run([str(PRIVATE/'fresh-input/NativeQueueAudit'),str(work),f'http://127.0.0.1:{server.server_port}'],env=dict(os.environ,CFFIXED_USER_HOME=str(work/'native-home')),capture_output=True,text=True,timeout=90)
        (work/'native.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('Actual cleanup stopped; inspect retained receipts, do not roll back tombstones')
        native=json.loads((work/'native-result.json').read_text())
        if native['pending_after']!=0 or sum(r['action']=='delete' and r['status']==200 for r in requests)!=37:raise RuntimeError('Incomplete actual backend cleanup')
        with closing(sqlite3.connect(database)) as db:
            tombstones=db.execute('select session_id,action_id,lifecycle_revision from agent_session_deletions').fetchall()
        relevant=[t for t in tombstones if t[0] in allowed]
        if len(relevant)!=37 or any(t[1]!=allowed[t[0]]['action_id'] or t[2]!=allowed[t[0]]['lifecycle_revision'] for t in relevant):raise RuntimeError('Actual receipt identities differ')
        after=rows()
        for table,index in [('agent_sessions_v2',0),('harness_tasks',1),('agent_memory_policy_v2',0)]:
            if after[table]!=[r for r in before[table] if r[index] not in allowed]:raise RuntimeError('Unexpected backend row changes: '+table)
        for table in before:
            if table not in {'agent_sessions_v2','harness_tasks','agent_memory_policy_v2','agent_session_deletions'} and before[table]!=after[table]:raise RuntimeError('Unexpected backend table changes: '+table)
        if [r for r in after['agent_session_deletions'] if r[0] not in allowed]!=before['agent_session_deletions']:raise RuntimeError('Unrelated deletion receipts changed')
        write(work/'actual-backend-result.json',dict(status='backend_cleaned',sessions=37,production_http_requests=len(requests),native_daily_file_changed=False,model_requests=0,web_operations=0))
    finally:server.shutdown();server.server_close()


# Importing this file does not enter runtime or open a database.
