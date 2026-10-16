"""QA-only App-owned service bootstrap for a real saved-invitation continuation.

No teaching/grading/capture output is replaced. Reuse the current batch's actual
smart router/coach successes, leave risk/deep/streaming unchecked, and avoid new
startup probes while retaining the original 30-request SDK admission counter.
"""
import importlib.util
import json
from pathlib import Path
import sys
import time


def install(directory, root):
    directory, root = Path(directory), Path(root)
    spec = importlib.util.spec_from_file_location("save_live_audit", root / "docs/evidence/2026-10-14-live-learning-save/audit_runtime.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.install(str(directory), str(root / "agent-service"))

    from agent_service import config, model_capabilities, openai_client
    from agent_service.call_errors import ModelCallError
    assert config.PROVIDER == "deepseek"
    previous = root / "docs/evidence/2026-10-16-ordinary-check-recheck"
    setup = json.loads((previous / "setup.json").read_text())
    import hashlib
    for name, expected in setup["provider_config_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    events = [json.loads(line) for line in (previous / "live-events.jsonl").read_text().splitlines()]
    calls = {row["call_id"]: row for row in events if row["type"] == "semantic_start"}
    successes = {calls[row["call_id"]]["schema"]: calls[row["call_id"]]
                 for row in events if row["type"] == "semantic_output"}
    for role, schema, model in (("router", "IntentDecision", config.ROUTER_MODEL), ("coach", "MasteryEvaluation", config.COACH_MODEL)):
        assert successes[schema]["model"] == model
        value = model_capabilities._state[role]
        value.update(status="ready", error="", checked_at=time.time(), retryable=False,
                     streaming="checking" if role == "coach" else "not_applicable",
                     strengths={"smart": dict(status="ready", error="", retryable=False),
                                "deep": dict(status="checking", error="")})
    # This private QA task continues an already running logical learning batch.
    # Startup health/probe behavior is explicitly outside this run's evidence.
    model_capabilities.start_probe = lambda *args, **kwargs: None
    audit.emit("qa_resume_bootstrap", starting_requests=20, reused_roles=["router", "coach"],
               reused_evidence="2026-10-16-ordinary-check-recheck", risk_ready=False,
               deep_or_streaming_verified=False, startup_probes=False, model_output_substituted=False)

    factory = openai_client._client
    def observed_client(**kwargs):
        client = factory(**kwargs)
        client._client.event_hooks["request"].append(lambda request: audit.emit(
            "sdk_http_request", method=request.method, host=request.url.host, path=request.url.path))
        client._client.event_hooks["response"].append(lambda response: audit.emit(
            "sdk_http_response_headers", host=response.request.url.host, path=response.request.url.path,
            status=response.status_code))
        return client
    openai_client._client = observed_client
