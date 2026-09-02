from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_service.config import COACH_MODEL, RISK_MODEL, ROUTER_MODEL, openai_key
from agent_service.openai_client import available_model_ids, model_is_callable


_lock = threading.Lock()
_state: dict[str, dict[str, object]] = {
    "router": {"model": ROUTER_MODEL, "status": "checking", "error": ""},
    "coach": {"model": COACH_MODEL, "status": "checking", "error": ""},
    "risk": {"model": RISK_MODEL, "status": "checking", "error": ""},
}


def probe() -> None:
    if not openai_key():
        with _lock:
            for value in _state.values():
                value.update(status="unavailable", error="model credential is not configured")
        return
    try:
        ids = available_model_ids()
        advertised = {role: str(value["model"]) for role, value in _state.items() if value["model"] in ids}
        results: dict[str, tuple[str, str]] = {}
        with ThreadPoolExecutor(max_workers=max(len(advertised), 1)) as executor:
            futures = {executor.submit(model_is_callable, model): role for role, model in advertised.items()}
            for future in as_completed(futures):
                role = futures[future]
                try:
                    results[role] = ("ready", "") if future.result() else ("unavailable", "generation probe returned no choices")
                except Exception as exc:  # noqa: BLE001
                    results[role] = ("unavailable", f"generation probe failed: {type(exc).__name__}")
        with _lock:
            for role, value in _state.items():
                status, error = results.get(role, ("unavailable", "configured model is not advertised by provider"))
                value.update(status=status, error=error)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            for value in _state.values():
                value.update(status="unavailable", error=f"capability check failed: {type(exc).__name__}")


def start_probe() -> None:
    with _lock:
        for value in _state.values():
            value.update(status="checking", error="")
    threading.Thread(target=probe, name="review-today-model-capabilities", daemon=True).start()


def snapshot() -> dict[str, dict[str, object]]:
    with _lock:
        return {key: dict(value) for key, value in _state.items()}
