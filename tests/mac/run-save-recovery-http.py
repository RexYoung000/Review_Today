"""Bridge native disk contracts to actual FastAPI routes using synthetic stores."""
import os
import sys
import tempfile
from pathlib import Path

audit_temp = tempfile.TemporaryDirectory(prefix='review-today-http-recovery-')
os.environ.update(REVIEW_TODAY_HARNESS_DB=str(Path(audit_temp.name) / 'import.sqlite3'),
                  OPENAI_API_KEY='', DEEPSEEK_API_KEY='', TYPESAFE_API_KEY='',
                  REVIEW_TODAY_JEV_TEST='0', REVIEW_TODAY_SEARCH_PROVIDER='none',
                  REVIEW_TODAY_READ_PROVIDER='local', REVIEW_TODAY_LLM_PROVIDER='openai_compatible')
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'agent-service'))
import json
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi.testclient import TestClient
from tests.test_conversation_v2 import ConversationTests
from agent_service import main

fixture = None
scenario = None
claims = acks = releases = 0
stopped = False
failed_ack = False
summaries = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        global fixture, scenario, claims, acks, releases, stopped, failed_ack
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
        status = 200
        if self.path == '/fixture/reset':
            if fixture:
                fixture.tearDown()
            fixture = ConversationTests(); fixture.setUp()
            run, task_id = fixture.make_committable()
            self.server.run_id, self.server.task_id = run.run_id, task_id
            main.conversation_harness, main.harness_store = fixture.harness, fixture.tasks
            scenario = body['scenario']; claims = acks = releases = 0; stopped = failed_ack = False
            result = fixture.tasks.get(task_id).view().model_dump()
        elif self.path == '/fixture/stop':
            fixture.control(self.server.run_id, 'stop'); stopped = True
            result = {'stopped': True}
        elif self.path == '/fixture/retry':
            state = fixture.state()
            offer = state['capture_offers'][state['tasks'][self.server.task_id]['context']['capture_offer_id']]
            fixture.send('保存为知识卡', operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version']))
            result = {'retried': True}
        elif self.path == '/fixture/stats':
            state = fixture.state()
            result = dict(scenario=scenario, claims=claims, acks=acks, releases=releases,
                          status=state['tasks'][self.server.task_id]['status'], paused=state['paused'],
                          foreground=state['foreground'], capture_calls=fixture.capture.call_count)
            summaries.append(result)
        else:
            if self.path.endswith('/commit-claim'): claims += 1
            if self.path.endswith('/commit-release'): releases += 1
            if self.path.endswith('/ack'): acks += 1
            if scenario == 'saved' and self.path.endswith('/ack') and not failed_ack:
                failed_ack = True; status = 503
                result = {'detail': {'error_code': 'RT.HARNESS.SERVICE_UNAVAILABLE', 'message': '受控回执丢失'}}
            else:
                client = TestClient(main.app)
                response = client.post(self.path, json=body) if self.command == 'POST' else client.get(self.path)
                status, result = response.status_code, response.json()
                if scenario == 'unsaved' and self.path.endswith('/commit-claim') and status == 200 and not stopped:
                    fixture.control(self.server.run_id, 'stop'); stopped = True
        payload = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    subprocess.run([sys.argv[1], f'http://127.0.0.1:{server.server_port}'], check=True, timeout=60)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
finally:
    server.shutdown(); server.server_close()
    if fixture: fixture.tearDown()
    audit_temp.cleanup()
