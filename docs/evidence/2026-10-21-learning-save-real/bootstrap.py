"""Observe real outputs after the tested admission guard; no substitutions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time


def install(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    evidence = root / 'docs/evidence/2026-10-21-learning-save-real'
    setup = json.loads((evidence / 'setup.json').read_text())
    assert Path(setup['directory']).resolve() == directory
    assert Path(os.environ['REVIEW_TODAY_HARNESS_DB']).resolve() == directory / 'checkpoint.sqlite3'
    assert not (directory / 'verified-roles.json').exists()
    for name, expected in setup['protected_fingerprints'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name

    def audit(event, values):
        if event == 'sqlite3.connect':
            assert Path(values[0]).resolve().is_relative_to(directory), 'SQLite outside isolated runtime'

    sys.addaudithook(audit)
    sys.path.insert(0, str(root / 'docs/evidence/2026-10-21-learning-save-preflight'))
    from quota import install as install_quota
    quota = install_quota(directory)
    lock = threading.RLock()

    def emit(kind, **values):
        with lock, (directory / 'live-events.jsonl').open('a') as output:
            output.write(json.dumps(dict(type=kind, at=time.time(), **values), ensure_ascii=False, default=str) + '\n')

    from agent_service import config, openai_client, web_tools
    parse, factory = openai_client.parse_model, openai_client._client
    backend_factory = web_tools._backend
    local = threading.local()

    def observed_parse(system, user, schema, **kwargs):
        import uuid
        call_id = str(uuid.uuid4())
        local.call_id = call_id
        try:
            payload = json.loads(user)
        except ValueError:
            payload = user
        emit('semantic_start', call_id=call_id, schema=schema.__name__, model=kwargs.get('model'),
             system_sha256=hashlib.sha256(system.encode()).hexdigest(), input=payload)
        try:
            result = parse(system, user, schema, **kwargs)
        except BaseException as error:
            emit('semantic_error', call_id=call_id, error_type=type(error).__name__, error_code=getattr(error, 'code', None))
            raise
        emit('semantic_output', call_id=call_id, schema=schema.__name__, output=result.model_dump())
        return result

    def client(**kwargs):
        value = factory(**kwargs)

        def before(request):
            # The guard's hook runs first. No headers, keys or raw errors logged.
            emit('sdk_wire_request', call_id=getattr(local, 'call_id', None),
                 host=request.url.host, path=request.url.path, method=request.method)

        def after(response):
            emit('sdk_wire_response', call_id=getattr(local, 'call_id', None), status=response.status_code)

        value._client.event_hooks['request'].append(before)
        value._client.event_hooks['response'].append(after)
        return value

    class ObservedBackend:
        def __init__(self, inner):
            self.inner, self.name = inner, inner.name

        def invoke(self, operation, *args, **kwargs):
            emit('web_entry', provider=self.name, operation=operation)
            try:
                result = getattr(self.inner, operation)(*args, **kwargs)
            except BaseException as error:
                emit('web_error', provider=self.name, operation=operation,
                     error_type=type(error).__name__, error_code=getattr(error, 'code', None))
                raise
            emit('web_return', provider=self.name, operation=operation)
            return result

        def search(self, *args, **kwargs): return self.invoke('search', *args, **kwargs)
        def read(self, *args, **kwargs): return self.invoke('read', *args, **kwargs)
        def context(self, *args, **kwargs): return self.invoke('context', *args, **kwargs)

    openai_client.parse_model = observed_parse
    openai_client._client = client
    web_tools._backend = lambda provider: ObservedBackend(backend_factory(provider))
    from agent_service import main as api

    @api.app.middleware('http')
    async def observe(request, call_next):
        response = await call_next(request)
        if request.method == 'POST':
            emit('native_http_post', path=request.url.path, status=response.status_code)
        return response

    emit('bootstrap_ready', pid=os.getpid(), decision=249, provider=config.PROVIDER,
         limits=dict(model=24, web=16), fresh_probes=True, substituted=False,
         web_search=web_tools.provider_chain('search'), web_read=web_tools.provider_chain('read'))
