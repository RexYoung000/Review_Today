"""Exercise the actual SDK probe path and zero-web gate without sockets."""
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
directory = Path(tempfile.mkdtemp(prefix='review-today-activation-guard-'))
os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/'checkpoint.sqlite3'),
    REVIEW_TODAY_LLM_PROVIDER='deepseek', DEEPSEEK_API_KEY='offline-fixture',
    REVIEW_TODAY_SEARCH_PROVIDER='deepseek', REVIEW_TODAY_SEARCH_FALLBACKS='exa,tavily',
    REVIEW_TODAY_READ_PROVIDER='exa', REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek',
    REVIEW_TODAY_BROWSER_FALLBACK='1', REVIEW_TODAY_CONTEXT_PROVIDER='none')
(directory/'authorization.json').write_text(json.dumps(dict(status='approved', batch_id='offline-probe-only',
    actual_model_request_limit=8, provider_web_operation_limit=0)))
denied = []


def audit(event, values):
    if event == 'socket.connect':
        denied.append(event)
        raise AssertionError('Offline guard checks may not connect')
    if event == 'sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(directory):
        raise AssertionError('Daily stores may not be opened')


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT/'agent-service'))
from agent_service import openai_client, web_tools
from agent_service.call_errors import ModelCallError, WebToolError
import httpx2 as sdk_http
from pydantic import BaseModel
from quota_activation import install, probes_only

factory = openai_client._client
wires, usages, web_calls = [], [], []


def handler(request):
    wires.append(request.method)
    if '--failure' in sys.argv:
        raise sdk_http.ReadTimeout('Offline startup failure', request=request)
    response = dict(id='offline', object='response', created_at=0,
        status='completed', model='deepseek-flash', output=[dict(id='offline-message', type='message', role='assistant',
        status='completed', content=[dict(type='output_text', text='{"ready":true,"message":"ready"}', annotations=[])])],
        usage=dict(input_tokens=2, output_tokens=1, total_tokens=3))
    if json.loads(request.content).get('stream'):
        event = dict(type='response.completed', sequence_number=0, response=response)
        return sdk_http.Response(200, request=request, headers={'content-type':'text/event-stream'},
            content=('data: '+json.dumps(event)+'\n\n').encode())
    return sdk_http.Response(200, request=request, json=response)


def fake_client(**kwargs):
    client = factory(**kwargs)
    client._client._transport.close()
    for transport in client._client._mounts.values():
        if transport is not None:
            transport.close()
    client._client._mounts = {}
    client._client._transport = sdk_http.MockTransport(handler)
    return client


class Backend:
    def __init__(self, provider): self.name = provider
    def search(self, *args, **kwargs): web_calls.append('search'); return []
    def read(self, *args, **kwargs): web_calls.append('read'); return ('', '')
    def context(self, *args, **kwargs): web_calls.append('context'); return []


openai_client._client = fake_client
web_tools._backend = Backend
quota = install(directory)
probes_only(quota)
for provider in ['deepseek', 'exa', 'tavily', 'browser']:
    for operation in ['search','read','context']:
        try:
            getattr(web_tools._backend(provider), operation)('offline')
        except WebToolError:
            pass
        else:
            raise AssertionError('Zero-web entry admitted')
assert not web_calls


class NonProbe(BaseModel):
    ready: bool


try:
    openai_client.parse_model('fixture','fixture',NonProbe, model='deepseek-flash')
except ModelCallError:
    pass
else:
    raise AssertionError('Conversation model admitted')
assert not wires
if '--failure' in sys.argv:
    for _ in range(2):
        try:
            openai_client.model_is_callable('deepseek-flash', on_request=lambda:str(uuid.uuid4()))
        except ModelCallError:
            pass
        else:
            raise AssertionError('Failed probe must not be retried')
    assert len(wires) == 1 and (directory/'STOP').exists() and not denied
    report = dict(outcome='PASS', first_failure_stops=True, second_transport_blocked=True,
        fake_sdk_requests=1, actual_model_requests=0, actual_web_operations=0)
    (OUT/'probe-failure-check.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    sys.exit(0)
for _ in range(7):
    assert openai_client.model_is_callable('deepseek-flash', on_request=lambda:str(uuid.uuid4()), on_usage=usages.append)
result = openai_client.model_stream_capability('deepseek-flash', on_request=lambda:str(uuid.uuid4()), on_usage=usages.append)
assert result['ready'] and len(wires) == len(usages) == 8
try:
    openai_client.model_is_callable('deepseek-flash', on_request=lambda:str(uuid.uuid4()))
except ModelCallError:
    pass
else:
    raise AssertionError('Ninth request admitted')
assert len(wires) == 8 and not denied
report = dict(outcome='PASS', fake_sdk_requests=8, usage_receipts=8, actual_model_requests=0,
    actual_web_operations=0, zero_web_entries_blocked=12, conversation_call_blocked=True,
    structured_and_stream_probe_paths_pass=True, ninth_probe_blocked=True, network_attempts=0)
(OUT/'probe-checks.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report))
