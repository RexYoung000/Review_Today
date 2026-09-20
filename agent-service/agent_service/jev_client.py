"""Fixed-host Jev transport. Credentials are supplied explicitly, never discovered."""
from __future__ import annotations

import json
import threading
import time

import httpx

from agent_service.judgment_types import MODEL, JudgmentResult, digest, validate_choices

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevClient:
    def __init__(self, key, *, client=None):
        if not key:
            raise ValueError("Jev credential required")
        self._key = key
        self.client = client or httpx.Client(follow_redirects=False)
        self.blocked = threading.Event()

    def close(self):
        self.client.close()
        self._key = ""

    def call(self, request, *, timeout=5, on_request=lambda: None, on_usage=lambda _: None):
        result = JudgmentResult(node=request.node, version=request.version,
                                input_hash=digest(request.payload()), status="failed", sources=request.sources)
        if self.blocked.is_set():
            return result.model_copy(update=dict(status="skipped", reason="authentication_disabled")), None
        start, raw, key = time.perf_counter(), None, self._key
        try:
            on_request()
            response = self.client.post(ENDPOINT, headers={"Authorization": "Bearer " + key},
                                       json=request.payload(), timeout=timeout, follow_redirects=False)
            if response.status_code in {401, 403}:
                self.blocked.set()
                result.reason = "authentication_failed"
            elif response.status_code != 200:
                result.reason = "http_" + str(response.status_code)
            else:
                raw = response.json()
                if not isinstance(raw, dict):
                    raise ValueError("invalid response")
                # Keep invalid non-finite responses JSON-recordable, and redact
                # before validation can fail. They remain invalid probabilities.
                raw = json.loads(json.dumps(raw, ensure_ascii=False).replace(key, "[REDACTED]"),
                                 parse_constant=lambda value: "invalid_number:" + value)
                result.model = raw.get("model") if isinstance(raw.get("model"), str) else None
                usage = raw.get("usage")
                if isinstance(usage, dict):
                    counts = {k: usage.get(k) if type(usage.get(k)) is int and usage[k] >= 0 else None
                              for k in ("input_tokens", "output_tokens")}
                    result.usage = counts
                    on_usage(counts)
                if result.model != MODEL:
                    raise ValueError("model version mismatch")
                result.answers = validate_choices(request.questions, raw.get("answers"))
                result.status = "uncertain" if "unsure" in result.labels.values() else "ok"
                result.reason = "uncertain_judgment" if result.status == "uncertain" else ""
        except httpx.TimeoutException:
            result.reason = "timeout"
        except httpx.TransportError:
            result.reason = "connection_failed"
        except (ValueError, KeyError, TypeError):
            result.reason = "invalid_response"
        finally:
            result.elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        return result, raw
