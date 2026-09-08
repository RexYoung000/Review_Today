"""Count actual SDK requests, including stream fallback; never read reasoning."""

import threading
import time
from types import SimpleNamespace


class Meter:
    def __init__(self, limit, on_change=lambda: None):
        self.limit, self.calls, self.phase = limit, [], "harness"
        self.lock = threading.Lock()
        self.on_change = on_change

    def wrap(self, client):
        meter = self

        class Endpoint:
            def __init__(self, obj):
                self.obj = obj

            def __getattr__(self, name):
                fn = getattr(self.obj, name)
                if name not in ("create", "parse"):
                    return fn

                def call(*args, **kwargs):
                    with meter.lock:
                        if len(meter.calls) >= meter.limit:
                            from agent_service.openai_client import ModelCallError

                            raise ModelCallError(
                                "EVAL_BUDGET", "evaluation request limit reached"
                            )
                        entry = dict(
                            phase=meter.phase,
                            model=kwargs.get("model"),
                            stream=bool(kwargs.get("stream")),
                            ms=None,
                            usage=None,
                            error=None,
                        )
                        meter.calls.append(entry)
                        meter.on_change()
                    started = time.monotonic()

                    def finish(response=None, error=None):
                        entry["ms"] = round((time.monotonic() - started) * 1000)
                        entry["error"] = error
                        usage = getattr(response, "usage", None)
                        if usage:
                            entry["usage"] = {
                                k: getattr(usage, k, None)
                                for k in (
                                    "input_tokens",
                                    "output_tokens",
                                    "total_tokens",
                                    "prompt_tokens",
                                    "completion_tokens",
                                )
                            }
                        meter.on_change()

                    try:
                        value = fn(*args, **kwargs)
                    except Exception as exc:
                        finish(error=type(exc).__name__)
                        raise
                    if not kwargs.get("stream"):
                        finish(value)
                        return value

                    class Stream:
                        def __enter__(self):
                            self.active = value.__enter__()
                            return self

                        def __iter__(self):
                            for event in self.active:
                                if event.type == "response.completed":
                                    finish(event.response)
                                yield event

                        def __exit__(self, typ, exc, tb):
                            if entry["ms"] is None:
                                finish(
                                    error=typ.__name__ if typ else "stream_incomplete"
                                )
                            return value.__exit__(typ, exc, tb)

                    return Stream()

                return call

        class Client:
            def __init__(self):
                self.responses = Endpoint(client.responses)
                self.chat = SimpleNamespace(
                    completions=Endpoint(client.chat.completions)
                )

            def __getattr__(self, name):
                return getattr(client, name)

        return Client()
