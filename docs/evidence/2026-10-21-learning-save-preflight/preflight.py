"""Offline SDK/web admission checks; every socket and outside SQLite is denied."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from quota import Quota, QuotaBlocked, install

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def child(case, directory):
    directory = Path(directory).resolve()
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / 'checkpoint.sqlite3'), REVIEW_TODAY_LLM_PROVIDER='deepseek',
        REVIEW_TODAY_JEV_TEST='0', OPENAI_API_KEY='local-sdk-fixture-only', DEEPSEEK_API_KEY='local-sdk-fixture-only',
        EXA_API_KEY='', TAVILY_API_KEY='', BRAVE_API_KEY='', DEEPSEEK_WEB_API_KEY='',
        REVIEW_TODAY_SEARCH_PROVIDER='deepseek', REVIEW_TODAY_SEARCH_FALLBACKS='exa,tavily',
        REVIEW_TODAY_READ_PROVIDER='exa', REVIEW_TODAY_READ_FALLBACKS='tavily,deepseek',
        REVIEW_TODAY_CONTEXT_PROVIDER='none', REVIEW_TODAY_BROWSER_FALLBACK='0')
    denied = dict(socket=0, outside_sqlite=0)

    def audit(event, values):
        if event == 'socket.connect':
            denied['socket'] += 1
            raise AssertionError('No network permitted in offline preflight')
        if event == 'sqlite3.connect' and not Path(values[0]).resolve().is_relative_to(directory):
            denied['outside_sqlite'] += 1
            raise AssertionError('No database outside fixture directory')

    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT / 'agent-service'))
    if case in {'pending', 'hold', 'restart', 'invalid_limits'}:
        original_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        try:
            install(directory)
        except QuotaBlocked:
            pass
        else:
            raise AssertionError('Unauthorized/stopped batch was installed')
        assert original_files == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        result = dict(case=case, outcome='PASS', mock_model_transport=0, mock_web_operations=0, real_requests=0, denied=denied,
                      pending_or_stopped_files_unchanged=True)
        write(directory / (case + '-result.json'), result)
        print(json.dumps(result))
        return

    from agent_service import openai_client, web_tools
    from agent_service.call_errors import ModelCallError, WebToolError
    from pydantic import BaseModel
    import httpx2 as sdk_http
    factory = openai_client._client
    wires, usages, backend_calls, classes = [], [], [], set()

    def handler(request):
        wires.append(dict(host=request.url.host, method=request.method))
        if case == 'timeout':
            raise sdk_http.ReadTimeout('local transport fixture', request=request)
        return sdk_http.Response(200, request=request, json=dict(id='offline-fixture', object='response', created_at=0,
            status='completed', model='deepseek-flash', output=[dict(id='offline-message', type='message', role='assistant',
                status='completed', content=[dict(type='output_text', text='{"value":"fixture"}', annotations=[])])],
            usage=dict(input_tokens=2, output_tokens=1, total_tokens=3)))

    def fake_transport_client(**kwargs):
        client = factory(**kwargs)
        classes.add(type(client._client).__name__)
        assert client.max_retries == 0
        client._client._transport.close()
        for transport in client._client._mounts.values():
            if transport is not None:
                transport.close()
        client._client._mounts = {}
        client._client._transport = sdk_http.MockTransport(handler)
        return client

    class FakeBackend:
        def __init__(self, provider):
            self.name = provider

        def search(self, query, **kwargs):
            backend_calls.append(dict(provider=self.name, operation='search'))
            if self.name == 'deepseek':
                raise WebToolError('UNSUPPORTED', 'offline fallback fixture')
            return [web_tools.SearchResult('https://example.com/rag', 'RAG', '公开资料')]

        def read(self, url, **kwargs):
            backend_calls.append(dict(provider=self.name, operation='read'))
            return ('RAG', '先检索资料再回答。')

        def context(self, query, **kwargs):
            backend_calls.append(dict(provider=self.name, operation='context'))
            return []

    openai_client._client = fake_transport_client
    web_tools._backend = FakeBackend
    quota = install(directory)

    class Probe(BaseModel):
        value: str

    def invoke():
        try:
            value = openai_client.parse_model('Offline schema fixture', 'No network', Probe, model='deepseek-flash',
                on_request=lambda: str(uuid.uuid4()), on_usage=usages.append)
            assert value.value == 'fixture'
            return 'returned'
        except ModelCallError as error:
            return error.code

    def seed(kind, count):
        for _ in range(count):
            token = quota.admit(kind, provider='fixture-prior')
            if kind == 'model':
                quota.bind(token, str(uuid.uuid4()))
            quota.dispatch(token)
            quota.finish(token, outcome='fixture_prior')

    if case == 'serial':
        outcomes = [invoke() for _ in range(25)]
        assert outcomes[:24] == ['returned'] * 24 and outcomes[24] != 'returned', outcomes
        assert len(wires) == len(usages) == 24
        try:
            quota.admit('web')
        except QuotaBlocked:
            pass
        else:
            raise AssertionError('Model cap must close new web admissions too')
    elif case == 'parallel':
        seed('model', 22)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: invoke(), range(8)))
        assert outcomes.count('returned') == 2 and len(wires) == len(usages) == 2, outcomes
    elif case == 'timeout':
        seed('model', 23)
        outcomes = [invoke(), invoke()]
        assert outcomes[0] == 'RT.MODEL.TIMEOUT' and outcomes[1] != 'returned', outcomes
        assert len(wires) == 1 and not usages
    elif case == 'bypass':
        client = openai_client._client()
        try:
            client.responses.create(model='deepseek-flash', input='offline', stream=False)
        except Exception:
            pass
        else:
            raise AssertionError('Unaccounted SDK transport admitted')
        finally:
            client.close()
        assert not wires and not quota.ledger.exists()
        outcomes = ['unaccounted transport blocked']
    elif case == 'duplicate':
        assert invoke() == 'returned'
        client = openai_client._client()
        try:
            client.responses.create(model='deepseek-flash', input='offline', stream=False)
        except Exception:
            pass
        else:
            raise AssertionError('Repeated transport identity admitted')
        finally:
            client.close()
        assert len(wires) == 1
        outcomes = ['returned', 'repeated transport blocked']
    elif case == 'revoked':
        identify = openai_client._request_identity

        def revoke(callback):
            value = identify(callback)
            spec = read(directory / 'authorization.json')
            spec['status'] = 'pending'
            write(directory / 'authorization.json', spec)
            return value

        openai_client._request_identity = revoke
        outcomes = [invoke()]
        assert outcomes[0] != 'returned' and not wires
        assert read(quota.ledger)['model_requests'] == 1
    elif case == 'web':
        web_tools.web_search_capability()
        assert not quota.ledger.exists(), 'Capability construction is not a paid operation'
        value = json.loads(web_tools.web_search_text('RAG 原理'))
        assert value['provider'] == 'exa' and len(backend_calls) == 2
        for _ in range(14):
            web_tools._backend('tavily').read('https://example.com/rag')
        try:
            web_tools._backend('exa').read('https://example.com/rag')
        except WebToolError:
            pass
        else:
            raise AssertionError('Seventeenth provider operation admitted')
        assert len(backend_calls) == 16 and read(quota.ledger)['web_operations'] == 16
        assert invoke() != 'returned' and not wires
        outcomes = ['provider fallback counted', '16 operations admitted', '17th blocked', 'model blocked after web cap']
    else:
        raise AssertionError('Unknown case')
    assert denied == dict(socket=0, outside_sqlite=0)
    if quota.ledger.exists():
        ledger = read(quota.ledger)
        ids = [e['program_id'] for e in ledger['entries'] if e['kind'] == 'model' and e['program_id']]
        assert len(ids) == len(set(ids))
        if case in {'serial', 'parallel', 'timeout'}:
            assert ledger['model_requests'] == 24 and ledger['closed'] and (directory / 'STOP').is_file()
    result = dict(case=case, outcome='PASS', real_requests=0, mock_model_transport=len(wires),
        mock_web_operations=len(backend_calls), fixture_usage_reports=len(usages), sdk_http_module=sdk_http.__name__,
        sdk_client_classes=sorted(classes), outcomes=outcomes, denied=denied)
    write(directory / (case + '-result.json'), result)
    print(json.dumps(result))


def main():
    directory = Path(tempfile.mkdtemp(prefix='review-today-learning-save-preflight-', dir='/tmp')).resolve()
    results = []
    for case in ('pending', 'hold', 'invalid_limits', 'serial', 'restart', 'parallel', 'timeout', 'bypass', 'duplicate', 'revoked', 'web'):
        target = directory / ('serial' if case == 'restart' else case)
        if case != 'restart':
            target.mkdir()
            write(target / 'authorization.json', dict(status='pending' if case == 'pending' else 'approved',
                batch_id='offline-' + case, actual_model_request_limit=25 if case == 'invalid_limits' else 24,
                provider_web_operation_limit=17 if case == 'invalid_limits' else 16))
            if case == 'hold':
                (target / 'HOLD').write_text('Offline HOLD fixture\n')
        completed = subprocess.run([sys.executable, __file__, case, str(target)], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=45)
        (OUT / (case + '.log')).write_text(completed.stdout)
        assert completed.returncode == 0, 'Inspect ' + case + '.log'
        results.append(read(target / (case + '-result.json')))
    write(OUT / 'preflight-result.json', dict(outcome='PASS', directory=str(directory), baseline_commit=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), cases=results,
        actual_model_requests=0, actual_web_operations=0, limits_tested=dict(model_requests=24, provider_web_operations=16),
        real_prepared_authorization_changed=False, real_service_or_app_started=False))
    print(json.dumps(dict(outcome='PASS', cases=len(results), actual_model_requests=0, actual_web_operations=0)))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(sys.argv[1], sys.argv[2])
    else:
        main()
