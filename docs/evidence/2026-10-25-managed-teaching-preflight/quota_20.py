"""Use the existing SDK guard with this new ceiling and zero web allowance."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
source = ROOT / "docs/evidence/2026-10-21-learning-save-preflight/quota.py"
text = source.read_text()
SOURCE_SHA256 = hashlib.sha256(source.read_bytes()).hexdigest()
for old, new in [
    ("not 0 < spec['actual_model_request_limit'] <= 24", "not 0 < spec['actual_model_request_limit'] <= 20"),
    ("not 0 < spec['provider_web_operation_limit'] <= 16", "spec['provider_web_operation_limit'] != 0"),
]:
    assert text.count(old) == 1
    text = text.replace(old, new)
exec(compile(text, str(source), "exec"), globals())
base_install = install


def install(directory):
    quota = base_install(directory)
    from agent_service import openai_client
    from functools import wraps

    def stop_probe(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            try:
                result = function(*args, **kwargs)
                if result is False or isinstance(result, dict) and result.get("ready") is False:
                    raise RuntimeError("Startup probe was not ready")
                return result
            except BaseException:
                try:
                    with (quota.directory / "STOP").open("x") as stream:
                        stream.write("Startup probe failed; no retry or replacement startup authorized.\n")
                except FileExistsError:
                    pass
                raise
        return invoke
    for name in ["model_is_callable", "model_stream_capability"]:
        setattr(openai_client, name, stop_probe(getattr(openai_client, name)))
    return quota
