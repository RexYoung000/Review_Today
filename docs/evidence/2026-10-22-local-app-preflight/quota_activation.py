"""Temporary activation guard; reuses the pinned SDK admission implementation."""
import hashlib
import json
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
_source = _root/'docs/evidence/2026-10-21-learning-save-preflight/quota.py'
SOURCE_SHA256 = hashlib.sha256(_source.read_bytes()).hexdigest()
assert SOURCE_SHA256 == json.loads((Path(__file__).parent/'source-pins.json').read_text())[str(_source.relative_to(_root))]
_text = _source.read_text()
for _old, _new in (
        ("not 0 < spec['actual_model_request_limit'] <= 24", "not 0 < spec['actual_model_request_limit'] <= 8"),
        ("not 0 < spec['provider_web_operation_limit'] <= 16", "not 0 <= spec['provider_web_operation_limit'] <= 16"),
        ("Path(configured_db).resolve() != quota.directory / 'checkpoint.sqlite3'",
         "Path(configured_db).resolve() != Path(quota.spec.get('database_path', quota.directory / 'checkpoint.sqlite3')).resolve()")):
    assert _text.count(_old) == 1
    _text = _text.replace(_old, _new)
exec(compile(_text, str(_source), 'exec'), globals())


def probes_only(quota):
    """Only the existing two startup-probe functions may admit model transport."""
    from functools import wraps
    from agent_service import openai_client
    from agent_service.call_errors import ModelCallError
    local = threading.local()
    identity = openai_client._request_identity

    def stop():
        try:
            with (quota.directory/'STOP').open('x') as output:
                output.write('Activation probe failed; no retry is authorized.\n')
        except FileExistsError:
            pass

    def probe_identity(callback):
        if not getattr(local, 'probe', False):
            raise ModelCallError('CANCELLED', 'This activation allowance only covers startup probes')
        return identity(callback)

    def allowed(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            previous = getattr(local, 'probe', False)
            local.probe = True
            try:
                result = function(*args, **kwargs)
                if result is False or isinstance(result, dict) and result.get('ready') is False:
                    stop()
                return result
            except BaseException:
                stop()
                raise
            finally:
                local.probe = previous
        return invoke

    openai_client._request_identity = probe_identity
    for name in ('model_is_callable', 'model_stream_capability'):
        setattr(openai_client, name, allowed(getattr(openai_client, name)))
