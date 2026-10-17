"""App-owned real continuation of EVAL-03, starting at 26 with cap 30."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlparse


def install(directory, root):
    directory, root = Path(directory), Path(root)
    setup = json.loads((directory / "authorization.json").read_text())
    assert setup["decision"] == 241 and setup["starting_requests"] == 26 and setup["limit"] == 30
    for name, expected in setup["provider_config_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    roles_path = directory / "verified-roles.json"
    assert hashlib.sha256(roles_path.read_bytes()).hexdigest() == setup["verified_roles_sha256"]
    spec = importlib.util.spec_from_file_location("separate_topic_audit", root / "docs/evidence/2026-10-14-live-learning-save/audit_runtime.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.install(str(directory), str(root / "agent-service"))
    assert audit.wire_count == 26
    from agent_service import config, openai_client
    from agent_service.call_errors import ModelCallError
    assert config.PROVIDER == "deepseek"
    host = urlparse(config.BASE_URL).hostname
    factory = openai_client._client
    seen = set()

    def blocked(reason):
        with audit.lock:
            marker = directory / "STOP"
            if not marker.exists():
                marker.write_text(reason + "\n")
            audit.emit("sdk_guard_blocked", reason=reason)
        raise ModelCallError("CANCELLED", "isolated continuation request not authorized")

    def client(**kwargs):
        value = factory(**kwargs)
        assert value.max_retries == 0

        def before(request):
            with audit.lock:
                identity = getattr(audit.local, "request_id", None)
                number = getattr(audit.local, "request_number", None)
                if ((directory / "STOP").exists() or not identity or identity in seen or not isinstance(number, int)
                        or not 27 <= number <= 30 or request.url.host != host or request.method != "POST"):
                    blocked("STOP: unaccounted, duplicate or out-of-scope SDK transport")
                seen.add(identity)
                audit.emit("sdk_wire_request", number=number, request_id=identity, host=request.url.host,
                    path=request.url.path, method=request.method, http_module=type(request).__module__)
                if number == 30:
                    (directory / "STOP").write_text("STOP: original EVAL-03 30/30 admitted; no further model requests.\n")

        def after(response):
            audit.emit("sdk_wire_response", number=getattr(audit.local, "request_number", None),
                request_id=getattr(audit.local, "request_id", None), status=response.status_code)

        value._client.event_hooks["request"].append(before)
        value._client.event_hooks["response"].append(after)
        return value

    openai_client._client = client
    from agent_service import main as api

    @api.app.middleware("http")
    async def observe(request, call_next):
        response = await call_next(request)
        if request.method == "POST":
            audit.emit("native_http_post", path=request.url.path, status=response.status_code)
        return response

    audit.emit("separate_topic_bootstrap", pid=os.getpid(), decision=241, new_batch=False,
        starting_requests=26, limit=30, model_output_substituted=False,
        probe_results_reused=True, probe_source="same EVAL-03 actual eight successful probes",
        default_startup_probes=False)
