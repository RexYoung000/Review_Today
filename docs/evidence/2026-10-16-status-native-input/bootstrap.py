"""QA-only frozen status router over the real app-owned localhost service."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time


def install(directory, root):
    directory, root = Path(directory), Path(root)
    lock = threading.Lock()

    def emit(kind, **values):
        with lock, (directory / "service-audit.jsonl").open("a") as output:
            output.write(json.dumps(dict(type=kind, at=time.time(), **values), ensure_ascii=False) + "\n")

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
                emit("forbidden_external_connect", address_type=type(address).__name__)
                raise AssertionError("QA forbids external connections")

    sys.addaudithook(audit)
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        # Local health must enable input; this placeholder has no provider access.
        os.environ[key] = "LOCAL_CONTROLLED_QA_NO_REMOTE_ACCESS"
    for key in ("TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[key] = ""
    os.environ.update(REVIEW_TODAY_LLM_PROVIDER="deepseek", REVIEW_TODAY_JEV_TEST="0",
                      REVIEW_TODAY_SEARCH_PROVIDER="none", REVIEW_TODAY_CONTEXT_PROVIDER="none",
                      REVIEW_TODAY_BROWSER_FALLBACK="0")

    from agent_service import conversation, model_capabilities, openai_client
    from agent_service.schemas import IntentDecision

    source = json.loads((directory / "source-checkpoint.json").read_text())
    frozen = copy.deepcopy(list(source["runs"].values())[-1]["intent"])
    call_count = 0

    def forbidden(*args, **kwargs):
        emit("forbidden_model_or_capture")
        raise AssertionError("QA forbids model SDK and capture")

    def response(system, user, schema, **kwargs):
        nonlocal call_count
        payload = json.loads(user)
        with lock:
            call_count += 1
            count = call_count
        assert schema is IntentDecision and count == 1, "Only one recorded status route is allowed"
        emit("frozen_status_route", schema=schema.__name__, input=payload,
             output_sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest())
        return IntentDecision.model_validate(copy.deepcopy(frozen))

    conversation.parse_model = response
    conversation.run_capture = forbidden
    openai_client._client = forbidden
    model_capabilities.start_probe = lambda *args, **kwargs: emit("controlled_probe_disabled")
    for value in model_capabilities._state.values():
        value.update(status="ready", error="", retryable=False, checked_at=time.time(),
                     streaming="buffered", strengths={"smart": dict(status="ready", error="", retryable=False)})

    from agent_service import main as api

    @api.app.middleware("http")
    async def observe(request, call_next):
        response = await call_next(request)
        if request.method != "GET" or not request.url.path.startswith("/healthz"):
            emit("local_http", method=request.method, path=request.url.path, status=response.status_code)
        return response

    emit("controlled_bootstrap", real_model_requests=0, synthetic_capability_ready=True,
         source_session=source["session_id"], substituted_output="recorded IntentDecision only")
