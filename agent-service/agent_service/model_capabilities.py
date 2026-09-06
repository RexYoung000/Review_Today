from __future__ import annotations

import threading
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_service.config import COACH_MODEL, RISK_MODEL, ROUTER_MODEL, PROVIDER, openai_key
from agent_service.openai_client import ModelCallError, model_is_callable, model_stream_capability
from agent_service.service_diagnostics import diagnose

_lock = threading.RLock()
_probing = False
_retry_attempt = 0
_next_probe = 0.0
_scheduler_started = False
_state = {role: dict(model=model, status="checking", error="", streaming="checking")
          for role, model in {"router": ROUTER_MODEL, "coach": COACH_MODEL, "risk": RISK_MODEL}.items()}


def _check(model, effort=None):
    try:
        ready = model_is_callable(model, reasoning_effort=effort) if effort else model_is_callable(model)
        if not ready:
            raise ModelCallError("EMPTY")
        return dict(status="ready", error="", category=None, retryable=False, recovery=None)
    except Exception as exc:
        diagnostic = diagnose(exc)
        return dict(status="unavailable", error=diagnostic["diagnostic"], **diagnostic)


def _check_strengths(model):
    result = _check(model)
    if PROVIDER == "deepseek":
        # Failure of high reasoning must not block a verified smart call. Conversely
        # smart success cannot certify deep support or silently authorize a downgrade.
        smart = dict(result)
        deep = _check(model, "high") if result["status"] == "ready" else dict(result)
        result["strengths"] = {"smart": smart, "deep": deep}
    return result


def _needs_retry(value):
    return (value.get("retryable") or value.get("stream_retryable") or
            any(v.get("retryable") or v.get("stream_retryable") for v in value.get("strengths", {}).values()))


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
        grouped = {}
        for role, value in snapshot().items():
            if roles is None or role in roles:
                grouped.setdefault(value["model"], []).append(role)
        pending = {executor.submit(_check_strengths, model): names for model, names in grouped.items()}
        for future in as_completed(pending):
            result = future.result()
            with _lock:
                for role in pending[future]:
                    _state[role].update(**deepcopy(result), checked_at=time.time(), elapsed_ms=int((time.monotonic() - started) * 1000))


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
        if PROVIDER == "deepseek" and (roles is None or "coach" in roles):
            deep = current["coach"].get("strengths", {}).get("deep", {})
            if deep.get("status") == "ready":
                try:
                    result = model_stream_capability(current["coach"]["model"], reasoning_effort="high")
                    update = dict(streaming=result["streaming"] if result["ready"] else "unavailable",
                                  stream_error="", stream_retryable=False)
                except Exception as exc:
                    update = dict(streaming="unavailable", stream_error=diagnose(exc)["diagnostic"],
                                  stream_retryable=diagnose(exc)["retryable"])
                with _lock:
                    _state["coach"]["strengths"]["deep"].update(update)
    finally:
        with _lock:
            retryable = any(_needs_retry(v) for v in _state.values())
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
        roles = list(_state) if reset else [role for role, value in _state.items() if _needs_retry(value)]
        for role in roles:
            value = _state[role]
            value.update(status="checking", error="", streaming="checking")
        if not _scheduler_started:
            _scheduler_started = True
            threading.Thread(target=_schedule, name="review-today-capability-recovery", daemon=True).start()
    threading.Thread(target=probe_with_streaming, args=(roles,), name="review-today-model-capabilities", daemon=True).start()


def require_model(model, *, thinking_strength="smart"):
    role = next((v for v in snapshot().values() if v["model"] == model), None)
    if role:
        role = role.get("strengths", {}).get(thinking_strength, role)
    if role and role["status"] == "unavailable":
        raise ModelCallError("UNAVAILABLE", role.get("error", ""))


def snapshot():
    with _lock:
        return {key: dict(deepcopy(value), next_probe_at=_next_probe or None) for key, value in _state.items()}
