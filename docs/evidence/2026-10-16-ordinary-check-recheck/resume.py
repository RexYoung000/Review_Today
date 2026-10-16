"""User-authorized continuation; preserve the stopped 10-15 batch and 14/30 count.

Reuses the original case runner and SDK admission gate. The only new observation
is HTTPX request/response hooks on the SDK's actual client: no headers, content,
credentials or model parameters are changed or logged by those hooks.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time


EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[2]
lock = threading.RLock()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(directory / "checkpoint.sqlite3")
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service import openai_client
    factory = openai_client._client

    def emit(kind, request, **values):
        row = dict(type=kind, at=time.time(), thread=threading.current_thread().name,
                   method=request.method, host=request.url.host, path=request.url.path, **values)
        with lock, (directory / "transport-events.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")

    def observed_client(**kwargs):
        client = factory(**kwargs)
        client._client.event_hooks["request"].append(lambda request: emit("sdk_http_request", request))
        client._client.event_hooks["response"].append(
            lambda response: emit("sdk_http_response_headers", response.request, status=response.status_code))
        return client

    openai_client._client = observed_client
    original = EVIDENCE.parent / "2026-10-15-ordinary-check-completeness/recheck.py"
    spec = importlib.util.spec_from_file_location("check01_original_runner", original)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.EVIDENCE = EVIDENCE
    # This is a new evidence directory. Old STOP/results remain untouched, while
    # the SDK admission counter starts at the previous conservative total of 14.
    return runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
