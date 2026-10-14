"""One-run observation/budget for the authorized live native audit.

Loaded only by the isolated App-owned service's sitecustomize. Never stores
headers, credentials, or raw upstream error bodies. No model is substituted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse
import uuid

lock = threading.RLock()
local = threading.local()
directory: Path
wire_count = 0


def emit(kind, **values):
    with lock:
        entry = dict(type=kind, at=datetime.now(timezone.utc).isoformat(), **values)
        with (directory / "live-events.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def install(data_directory, service_root):
    global directory, wire_count
    directory = Path(data_directory)
    assert directory.name.startswith("review-today-")
    assert Path(os.environ["REVIEW_TODAY_HARNESS_DB"]).resolve() == (directory / "checkpoint.sqlite3").resolve()
    counter = directory / "request-count.json"
    wire_count = json.loads(counter.read_text())["actual_requests"] if counter.exists() else 0
    from agent_service import config
    from agent_service import openai_client
    from agent_service.call_errors import ModelCallError
    import httpx

    host = urlparse(config.BASE_URL or "https://api.openai.com/v1").hostname
    send = httpx.Client.send
    identify = openai_client._request_identity
    report_usage = openai_client._report_usage
    parse = openai_client.parse_model

    def identity(callback):
        global wire_count
        with lock:
            if (directory / "STOP").exists() or wire_count >= 30:
                emit("budget_blocked", actual_requests=wire_count)
                raise ModelCallError("CANCELLED", "isolated audit stopped or request cap reached")
            value = identify(callback)
            wire_count += 1
            local.request_id = value
            local.request_number = wire_count
            emit("request_entry", number=wire_count, request_id=value,
                 thread=threading.current_thread().name,
                 counting_basis="production on_request before SDK call; pretransport failures counted conservatively")
            (directory / "request-count.json").write_text(json.dumps(dict(actual_requests=wire_count, limit=30)))
            return value

    def counted_send(client, request, *args, **kwargs):
        if request.url.host == host and request.method == "POST":
            number = getattr(local, "request_number", None)
            emit("http_observed", number=number, request_id=getattr(local, "request_id", None),
                 host=host, path=request.url.path)
            try:
                response = send(client, request, *args, **kwargs)
            except Exception as error:
                emit("transport_error", number=number, error_type=type(error).__name__)
                raise
            emit("transport_response", request_id=getattr(local, "request_id", None), status=response.status_code)
            return response
        return send(client, request, *args, **kwargs)

    def usage(response, callback, *, request_id=None):
        result = report_usage(response, callback, request_id=request_id)
        value = getattr(response, "usage", None)
        emit("reported_usage", request_id=request_id,
             usage=value.model_dump() if hasattr(value, "model_dump") else value if isinstance(value, dict) else None)
        return result

    def observed_parse(system, user, schema, **kwargs):
        call_id = str(uuid.uuid4())
        try:
            payload = json.loads(user)
        except ValueError:
            payload = user
        emit("semantic_start", call_id=call_id, schema=schema.__name__, model=kwargs.get("model"),
             system_sha256=hashlib.sha256(system.encode()).hexdigest(), input=payload)
        try:
            result = parse(system, user, schema, **kwargs)
        except Exception as error:
            emit("semantic_error", call_id=call_id, error_type=type(error).__name__,
                 error_code=getattr(error, "code", None))
            raise
        emit("semantic_output", call_id=call_id, schema=schema.__name__, output=result.model_dump())
        return result

    httpx.Client.send = counted_send
    openai_client._request_identity = identity
    openai_client._report_usage = usage
    openai_client.parse_model = observed_parse
    # Reuse only this batch's actual successful startup probes after observer repair.
    # This is QA bootstrap bookkeeping, not a model/lesson/grading substitution.
    verified_roles = directory / "verified-roles.json"
    if verified_roles.exists():
        from agent_service import model_capabilities
        roles = json.loads(verified_roles.read_text())
        expected = dict(router=config.ROUTER_MODEL, coach=config.COACH_MODEL, risk=config.RISK_MODEL)
        assert all(roles[k]["model"] == v and roles[k]["status"] == "ready" for k, v in expected.items())
        model_capabilities._state = roles
        model_capabilities.start_probe = lambda *args, **kwargs: None
        emit("same_batch_verified_probe_reused", initial_requests=8, provider=config.PROVIDER, models=expected)
    emit("runtime_header", provider=config.PROVIDER,
         models=dict(router=config.ROUTER_MODEL, coach=config.COACH_MODEL, risk=config.RISK_MODEL),
         service_root=str(service_root), checkpoint=str(directory / "checkpoint.sqlite3"),
         actual_request_limit=30, model_substituted=False, native_write="isolated disk only")
