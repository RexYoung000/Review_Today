"""Offline SDK quota wiring: production client class, fake transport, no sockets."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def child(case, directory):
    directory = Path(directory)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/"checkpoint.sqlite3"), REVIEW_TODAY_LLM_PROVIDER="deepseek",
                      REVIEW_TODAY_JEV_TEST="0", OPENAI_API_KEY="local-sdk-fixture-only", DEEPSEEK_API_KEY="local-sdk-fixture-only")
    def no_socket(event, args):
        if event == "socket.connect":
            raise AssertionError("Offline SDK preflight forbids every network connection")
    sys.addaudithook(no_socket)
    sys.path.insert(0, str(ROOT/"agent-service"))
    from agent_service import openai_client
    from agent_service.call_errors import ModelCallError
    from pydantic import BaseModel
    # Match the SDK's actual transport dependency (this runtime uses httpx2).
    import httpx2 as httpx
    spec = importlib.util.spec_from_file_location("offline_audit", ROOT/"docs/evidence/2026-10-14-live-learning-save/audit_runtime.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.install(str(directory), str(ROOT/"agent-service"))
    factory = openai_client._client
    lock = threading.RLock()
    wires, sdk_hooks, usages = [], [], []
    classes = set()
    def handler(request):
        with lock:
            wires.append(dict(method=request.method, host=request.url.host))
        if case == "timeout":
            raise httpx.ReadTimeout("local transport fixture", request=request)
        return httpx.Response(200, request=request, json=dict(id="offline-fixture-response", object="response",
            created_at=0, status="completed", model="deepseek-flash", output=[dict(id="offline-message", type="message",
                role="assistant", status="completed", content=[dict(type="output_text", text='{"value":"local fixture"}', annotations=[])])],
            usage=dict(input_tokens=2, output_tokens=1, total_tokens=3)))
    def client(**kwargs):
        value = factory(**kwargs)
        assert value.max_retries == 0
        classes.add(type(value._client).__name__)
        # Preserve the exact production SDK client class; replace only its I/O.
        value._client._transport.close()
        for transport in value._client._mounts.values():
            if transport is not None:
                transport.close()
        value._client._mounts = {}
        value._client._transport = httpx.MockTransport(handler)
        def on_wire(request):
            with lock:
                sdk_hooks.append(dict(request_id=getattr(audit.local,"request_id",None), number=getattr(audit.local,"request_number",None)))
        value._client.event_hooks["request"].append(on_wire)
        return value
    openai_client._client = client
    class Probe(BaseModel):
        value: str
    def invoke():
        try:
            result = openai_client.parse_model("Local schema fixture", "No remote request", Probe, model="deepseek-flash",
                on_request=lambda:str(uuid.uuid4()), on_usage=lambda usage:usages.append(usage))
            assert result.value == "local fixture"
            return "returned"
        except ModelCallError as error:
            return error.code
    if case == "parallel":
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _:invoke(), range(8)))
        assert outcomes.count("returned") == 2 and outcomes.count("RT.MODEL.CANCELLED") == 6, outcomes
        assert len(wires) == len(sdk_hooks) == len(usages) == 2
    elif case == "restart":
        outcomes = [invoke()]
        assert outcomes == ["RT.MODEL.CANCELLED"] and wires == sdk_hooks == usages == []
    elif case == "timeout":
        outcomes = [invoke(), invoke()]
        assert outcomes == ["RT.MODEL.TIMEOUT","RT.MODEL.CANCELLED"] and len(wires) == len(sdk_hooks) == 1 and not usages
    else:
        outcomes = [invoke(), invoke(), invoke()]
        assert outcomes == ["returned","returned","RT.MODEL.CANCELLED"] and len(wires) == len(sdk_hooks) == len(usages) == 2
    assert json.loads((directory/"request-count.json").read_text())["actual_requests"] == 30
    assert len({x["request_id"] for x in sdk_hooks}) == len(sdk_hooks)
    assert all(x["request_id"] and x["number"] <= 30 for x in sdk_hooks)
    if case != "timeout":
        assert {x["request_id"] for x in usages} == {x["request_id"] for x in sdk_hooks}
    result = dict(case=case, outcome="PASS", real_model_requests=0, mock_transport_requests=len(wires),
        sdk_hook_count=len(sdk_hooks), fixture_usage_reports=len(usages), sdk_http_module=httpx.__name__,
        client_classes=sorted(classes), outcomes=outcomes)
    (directory/(case+"-result.json")).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


def main():
    directory = Path(tempfile.mkdtemp(prefix="review-today-sdk-preflight-", dir="/tmp"))
    results = []
    for case in ("serial","restart","parallel","timeout"):
        target = directory/("review-today-serial" if case == "restart" else "review-today-"+case)
        if case != "restart":
            target.mkdir()
            (target/"request-count.json").write_text(json.dumps(dict(actual_requests=29 if case=="timeout" else 28,limit=30)))
        completed = subprocess.run([sys.executable,__file__,case,str(target)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (EVIDENCE/("sdk-"+case+".log")).write_text(completed.stdout)
        assert completed.returncode == 0, f"{case} failed; inspect sdk-{case}.log"
        results.append(json.loads((target/(case+"-result.json")).read_text()))
    result = dict(outcome="PASS", directory=str(directory), real_model_requests=0, cases=results)
    (EVIDENCE/"sdk-preflight-result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv)>1:
        child(sys.argv[1],sys.argv[2])
    else:
        main()
