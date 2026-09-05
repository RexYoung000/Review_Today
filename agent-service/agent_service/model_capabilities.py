from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_service.config import COACH_MODEL, RISK_MODEL, ROUTER_MODEL, openai_key
from agent_service.openai_client import ModelCallError, model_is_callable, model_stream_capability
from agent_service.service_diagnostics import diagnose

_lock = threading.RLock()
_probing = False
_retry_attempt = 0
_next_probe = 0.0
_scheduler_started = False
_state = {role: dict(model=model, status="checking", error="", streaming="checking")
          for role, model in {"router": ROUTER_MODEL, "coach": COACH_MODEL, "risk": RISK_MODEL}.items()}


def probe(roles=None):
    # Listing models is optional: real calls with unchanged credentials establish capability.
    if not openai_key():
        with _lock:
            for value in _state.values():
                value.update(status="unavailable", error="credential_missing", category="credential_missing",
                             retryable=False, checked_at=time.time(), recovery="check_configuration")
        return
    with ThreadPoolExecutor(max_workers=3) as executor:
        started = time.monotonic()
        pending = {executor.submit(model_is_callable, value["model"]): role for role, value in snapshot().items() if roles is None or role in roles}
        for future in as_completed(pending):
            role = pending[future]
            try:
                if not future.result():
                    raise ModelCallError("EMPTY")
                result = dict(status="ready", error="", category=None, retryable=False, recovery=None)
            except Exception as exc:
                result = dict(status="unavailable", error=diagnose(exc)["diagnostic"], **diagnose(exc))
            with _lock:
                _state[role].update(**result, checked_at=time.time(), elapsed_ms=int((time.monotonic() - started) * 1000))


def probe_with_streaming(roles=None):
    global _probing, _next_probe, _retry_attempt
    try:
        probe(roles)
        current = snapshot()
        with _lock:
            for role in ("router", "risk"):
                _state[role]["streaming"] = "not_applicable"
        if current["coach"]["status"] == "ready" and (roles is None or "coach" in roles):
            try:
                result = model_stream_capability(current["coach"]["model"])
                with _lock:
                    _state["coach"].update(streaming=result["streaming"] if result["ready"] else "unavailable",
                                           stream_error="", stream_retryable=False)
            except Exception as exc:
                with _lock:
                    _state["coach"].update(streaming="unavailable", stream_error=diagnose(exc)["diagnostic"],
                                           stream_retryable=diagnose(exc)["retryable"])
        elif current["coach"]["status"] != "ready":
            with _lock:
                _state["coach"].update(streaming="unavailable", stream_retryable=False)
    finally:
        with _lock:
            retryable = any(v.get("retryable") or v.get("stream_retryable") for v in _state.values())
            delay = (10, 30, 120)[min(_retry_attempt, 2)]
            _next_probe = time.time() + delay if retryable else 0
            _retry_attempt = _retry_attempt + 1 if _next_probe else 0
            _probing = False
        if snapshot()["router"]["status"] == "ready":
            # Only unscheduled accepted/queued inputs are eligible. Failed replies
            # and paused Sessions remain explicitly user-controlled.
            from agent_service.conversation import conversation_harness
            for sid in conversation_harness.store.sessions():
                conversation_harness.start(sid)


def _schedule():
    previous_key = openai_key()
    while True:
        time.sleep(1)
        current_key = openai_key()
        changed = current_key != previous_key
        previous_key = current_key
        if changed or (_next_probe and time.time() >= _next_probe):
            start_probe(reset=changed)


def start_probe(reset=True):
    global _probing, _retry_attempt, _next_probe, _scheduler_started
    with _lock:
        if _probing:
            return
        _probing = True
        _next_probe = 0
        if reset:
            _retry_attempt = 0
        roles = list(_state) if reset else [role for role, value in _state.items() if value.get("retryable") or value.get("stream_retryable")]
        for role in roles:
            value = _state[role]
            value.update(status="checking", error="", streaming="checking")
        if not _scheduler_started:
            _scheduler_started = True
            threading.Thread(target=_schedule, name="review-today-capability-recovery", daemon=True).start()
    threading.Thread(target=probe_with_streaming, args=(roles,), name="review-today-model-capabilities", daemon=True).start()


def require_model(model):
    role = next((v for v in snapshot().values() if v["model"] == model), None)
    if role and role["status"] == "unavailable":
        raise ModelCallError("UNAVAILABLE", role.get("error", ""))


def snapshot():
    with _lock:
        return {key: dict(value, next_probe_at=_next_probe or None) for key, value in _state.items()}
