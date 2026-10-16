"""Real status-only request using existing config and the original 30-call cap."""
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import urlparse

from fence import OneRequestFence


def install(directory, root):
    directory, root = Path(directory), Path(root)
    spec = importlib.util.spec_from_file_location("status_real_audit", root / "docs/evidence/2026-10-14-live-learning-save/audit_runtime.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.install(str(directory), str(root / "agent-service"))
    from agent_service import config, model_capabilities, openai_client
    import httpx
    assert config.PROVIDER == "deepseek" and audit.wire_count == 29
    setup = json.loads((directory / "qa-authorization.json").read_text())
    assert setup["starting_requests"] == 29 and setup["additional_request_limit"] == 1
    for name, expected in setup["provider_config_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    prior = root / "docs/evidence/2026-10-16-ordinary-check-recheck/live-events.jsonl"
    rows = [json.loads(x) for x in prior.read_text().splitlines()]
    starts = {r["call_id"]:r for r in rows if r["type"] == "semantic_start"}
    successes = {starts[r["call_id"]]["schema"]:starts[r["call_id"]] for r in rows if r["type"] == "semantic_output"}
    for role, schema, model in (("router", "IntentDecision", config.ROUTER_MODEL), ("coach", "MasteryEvaluation", config.COACH_MODEL)):
        assert successes[schema]["model"] == model
        model_capabilities._state[role].update(status="ready", error="", checked_at=time.time(), retryable=False,
            streaming="checking" if role == "coach" else "not_applicable",
            strengths={"smart": dict(status="ready", error="", retryable=False), "deep": dict(status="checking", error="")})
    model_capabilities.start_probe = lambda *args, **kwargs: audit.emit("startup_probe_disabled")
    fence = OneRequestFence(directory, audit.emit)
    real_parse = openai_client.parse_model

    def status_parse(system, user, schema, **kwargs):
        fence.admit_parse(schema.__name__, json.loads(user))
        assert kwargs.get("model") == config.ROUTER_MODEL
        try:
            return real_parse(system, user, schema, **kwargs)
        except BaseException:
            fence.stop("STOP: first real status request failed; no retry authorized")
            raise

    openai_client.parse_model = status_parse
    factory = openai_client._client
    wire_events = 0

    def guarded_client(**kwargs):
        client = factory(**kwargs)
        assert client.max_retries == 0
        def before_transport(request):
            nonlocal wire_events
            with fence.lock:
                if wire_events != 0 or request.url.host != urlparse(config.BASE_URL).hostname:
                    fence.stop("STOP: second SDK transport or redirected host blocked")
                    raise AssertionError("Only one actual provider HTTP request is authorized")
                wire_events += 1
                audit.emit("sdk_wire_request", number=30, method=request.method,
                           host=request.url.host, path=request.url.path)
        client._client.event_hooks["request"].append(before_transport)
        return client

    openai_client._client = guarded_client
    audited_send = httpx.Client.send
    host = urlparse(config.BASE_URL).hostname

    def single_send(client, request, *args, **kwargs):
        if request.url.host in {"127.0.0.1", "localhost", "::1"}:
            return audited_send(client, request, *args, **kwargs)
        fence.admit_wire(host=request.url.host, expected_host=host, method=request.method,
            number=getattr(audit.local, "request_number", None), request_id=getattr(audit.local, "request_id", None))
        try:
            response = audited_send(client, request, *args, **kwargs)
        except BaseException:
            audit.emit("single_transport_failed")
            raise
        audit.emit("single_transport_response", number=30, status=response.status_code)
        return response

    httpx.Client.send = single_send
    from agent_service import main as api

    @api.app.middleware("http")
    async def observe(request, call_next):
        response = await call_next(request)
        if request.method == "POST":
            audit.emit("native_http_post", path=request.url.path, status=response.status_code)
        return response

    audit.emit("real_status_bootstrap", starting_requests=29, additional_request_limit=1, original_limit=30,
        model_output_substituted=False, capability_source="same batch real successes, 2026-10-16-ordinary-check-recheck",
        startup_probes=False, risk_deep_and_streaming_unchecked=True)
