"""Offline approval, exact pending-entry, SDK cap and zero-web checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from common import ROOT, OUT, PRIVATE, ARCHIVE, read, write, sha, files, unchanged


def sdk_fixture(failure=False):
    directory = Path(tempfile.mkdtemp(prefix="review-today-managed-sdk-", suffix=".noindex")).resolve()
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"),
        REVIEW_TODAY_LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY="offline-fixture", REVIEW_TODAY_JEV_TEST="0",
        REVIEW_TODAY_SEARCH_PROVIDER="deepseek", REVIEW_TODAY_SEARCH_FALLBACKS="exa,tavily",
        REVIEW_TODAY_READ_PROVIDER="exa", REVIEW_TODAY_READ_FALLBACKS="tavily,deepseek",
        REVIEW_TODAY_BROWSER_FALLBACK="1", REVIEW_TODAY_CONTEXT_PROVIDER="none")
    write(directory / "authorization.json", dict(status="approved", batch_id="offline-20-0", actual_model_request_limit=20, provider_web_operation_limit=0))
    def audit(event, args):
        if event in {"socket.connect", "sqlite3.connect"}:
            raise AssertionError("Offline SDK fixture must not connect to network or SQLite")
    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service import openai_client, web_tools
    from agent_service.call_errors import ModelCallError, WebToolError
    import httpx2 as sdk_http
    from pydantic import BaseModel
    from quota_20 import install
    wires, usages, backend_calls = [], [], []
    factory = openai_client._client
    def handler(request):
        wires.append(request.method)
        if failure:
            raise sdk_http.ReadTimeout("offline startup failure", request=request)
        response = dict(id=str(uuid.uuid4()), object="response", created_at=0, status="completed", model="deepseek-flash",
            output=[dict(id="fixture", type="message", role="assistant", status="completed",
                content=[dict(type="output_text", text='{"ready":true,"message":"ready"}', annotations=[])])],
            usage=dict(input_tokens=2, output_tokens=1, total_tokens=3))
        if json.loads(request.content).get("stream"):
            event = dict(type="response.completed", sequence_number=0, response=response)
            return sdk_http.Response(200, request=request, headers={"content-type": "text/event-stream"},
                content=("data: " + json.dumps(event) + "\n\n").encode())
        return sdk_http.Response(200, request=request, json=response)
    def client(**kwargs):
        value = factory(**kwargs)
        assert value.max_retries == 0
        value._client._transport.close()
        for transport in value._client._mounts.values():
            if transport is not None:
                transport.close()
        value._client._mounts = {}
        value._client._transport = sdk_http.MockTransport(handler)
        return value
    class Backend:
        def __init__(self, provider): self.name = provider
        def search(self, *args, **kwargs): backend_calls.append("search")
        def read(self, *args, **kwargs): backend_calls.append("read")
        def context(self, *args, **kwargs): backend_calls.append("context")
    openai_client._client, web_tools._backend = client, Backend
    quota = install(directory)
    for provider in ["deepseek", "exa", "tavily", "browser"]:
        for operation in ["search", "read", "context"]:
            try: getattr(web_tools._backend(provider), operation)("offline")
            except WebToolError: pass
            else: raise AssertionError("Zero-web operation admitted")
    assert not backend_calls and not wires
    if failure:
        for _ in range(2):
            try: openai_client.model_is_callable("deepseek-flash", on_request=lambda: str(uuid.uuid4()))
            except ModelCallError: pass
            else: raise AssertionError("Startup failure was not stopped")
        assert len(wires) == 1 and (directory / "STOP").exists()
    else:
        class Reply(BaseModel):
            ready: bool
        # Includes ordinary teaching calls as well as structured/stream probes.
        for _ in range(2):
            assert openai_client.parse_model("fixture", "fixture", Reply, model="deepseek-flash", on_request=lambda: str(uuid.uuid4()), on_usage=usages.append).ready
        for _ in range(16):
            assert openai_client.model_is_callable("deepseek-flash", on_request=lambda: str(uuid.uuid4()), on_usage=usages.append)
        for _ in range(2):
            assert openai_client.model_stream_capability("deepseek-flash", on_request=lambda: str(uuid.uuid4()), on_usage=usages.append)["ready"]
        try: openai_client.parse_model("fixture", "fixture", Reply, model="deepseek-flash", on_request=lambda: str(uuid.uuid4()))
        except ModelCallError: pass
        else: raise AssertionError("Twenty-first SDK request admitted")
        assert len(wires) == len(usages) == 20
        ledger = read(directory / "quota.json")
        assert ledger["closed"] and ledger["model_requests"] == 20 and ledger["web_operations"] == 0
        assert all(e["outcome"] == "returned" and e["dispatched"] for e in ledger["entries"])
    report = dict(status="PASS", fixture=str(directory), fake_sdk_requests=len(wires), actual_model_requests=0,
        actual_web_operations=0, zero_web_entries_denied=12, startup_first_failure_stops=failure,
        ordinary_structured_and_stream_paths_checked=not failure, twenty_first_denied=not failure)
    write(OUT / ("failure-check.json" if failure else "sdk-check.json"), report)
    print(json.dumps(report))


def approval_fixture():
    import bootstrap
    directory = Path(tempfile.mkdtemp(prefix="review-today-managed-approval-", suffix=".noindex")).resolve()
    old_out = bootstrap.OUT
    bootstrap.OUT = directory
    (directory / "input.py").write_text("# fixture\n")
    write(directory / "plan.json", dict(scope="fixture"))
    write(directory / "source-pins.json", {"input.py": sha(directory / "input.py")})
    write(directory / "setup.json", dict(directory=str(directory), batch_id="fixture", scope="fixture"))
    good = dict(status="approved", batch_id="fixture", scope="fixture", actual_model_request_limit=20,
        provider_web_operation_limit=0, plan_sha256=sha(directory / "plan.json"), source_pins_sha256=sha(directory / "source-pins.json"))
    cases = []
    def attempt(name, spec, success=False):
        write(directory / "authorization.json", spec)
        before = files(directory)
        try: bootstrap.check_approved(directory, directory)
        except (AssertionError, PermissionError): assert not success, name
        else: assert success, name
        assert files(directory) == before
        cases.append(dict(case=name, passed=True))
    attempt("exact 20/0 scope", good, True)
    for key, value in [("status", "pending"), ("batch_id", "old"), ("scope", "daily writes"),
                       ("actual_model_request_limit", 21), ("provider_web_operation_limit", 1),
                       ("plan_sha256", "changed"), ("source_pins_sha256", "changed")]:
        attempt(key + " mismatch", dict(good, **{key: value}))
    for name in ["HOLD", "STOP", "bootstrap-ready.json", "startup-claim.json"]:
        (directory / name).write_text("fixture\n")
        attempt(name + " refuses", good)
        (directory / name).unlink()
    (directory / "input.py").write_text("# changed\n")
    attempt("source changed refuses", good)
    bootstrap.OUT = old_out
    return cases


def main():
    unchanged()
    setup = read(OUT / "setup.json")
    runtime = Path(setup["directory"])
    frozen = files(runtime)
    assert not (runtime / "app.store").exists() and not (runtime / "checkpoint.sqlite3").exists()
    cases = approval_fixture()
    for flag in ["--sdk", "--failure"]:
        result = subprocess.run([sys.executable, "-B", str(OUT / "checks.py"), flag], capture_output=True, text=True, timeout=45)
        (OUT / (flag[2:] + ".log")).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr
    # Exactly the interpreter command and environment constructed by the App.
    env = dict(PATH=os.environ.get("PATH", "/usr/bin:/bin"), HOME=str(Path.home()), LANG="zh_CN.UTF-8",
        PYTHONUNBUFFERED="1", PYTHONPATH=str(runtime / "owned-project/agent-service"),
        REVIEW_TODAY_JEV_TEST="0", REVIEW_TODAY_BROWSER_FALLBACK="1",
        REVIEW_TODAY_HARNESS_DB=str(runtime / "checkpoint.sqlite3"), REVIEW_TODAY_SERVICE_PORT=str(setup["port"]))
    command = [str(runtime / "owned-project/agent-service/.venv/bin/python"), "-u", "-c",
        'print("RT.STARTUP.INTERPRETER_READY",flush=True)\nfrom agent_service.main import run\nprint("RT.STARTUP.SERVICE_IMPORTED",flush=True)\nrun()']
    result = subprocess.run(command, cwd=runtime / "owned-project/agent-service", env=env, capture_output=True, text=True, timeout=15)
    (OUT / "actual-child-pending.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 74 and "QA_BOOTSTRAP_FAILED:PermissionError" in result.stdout
    assert "RT.STARTUP.INTERPRETER_READY" not in result.stdout
    assert files(runtime) == frozen
    launcher = subprocess.run([sys.executable, "-B", str(OUT / "launch_after_approval.py")], capture_output=True, text=True, timeout=15)
    (OUT / "actual-launcher-pending.log").write_text(launcher.stdout + launcher.stderr)
    assert launcher.returncode != 0 and "pending/HOLD/STOP" in launcher.stderr
    assert files(runtime) == frozen
    audit = '''import runpy,sys
def audit(event,args):
    if event in {'socket.connect','sqlite3.connect'}:
        print('EARLY_RUNTIME_ATTEMPT',flush=True)
        raise AssertionError(event)
sys.addaudithook(audit)
runpy.run_path(sys.argv[1],run_name='__main__')
'''
    external = subprocess.run([sys.executable, "-S", "-B", "-c", audit, str(runtime / "owned-project/agent-service/sitecustomize.py")],
        capture_output=True, text=True, timeout=15)
    (OUT / "actual-source-pending-audit.log").write_text(external.stdout + external.stderr)
    assert external.returncode == 74 and "QA_BOOTSTRAP_FAILED:PermissionError" in external.stdout
    assert "EARLY_RUNTIME_ATTEMPT" not in external.stdout and files(runtime) == frozen
    unchanged()
    write(OUT / "checks.json", dict(status="PASS", approval_cases=cases, actual_pending_child_rejected_before_interpreter_marker=True,
        actual_pending_launcher_refused_before_mutation_or_ui=True, external_source_audit_no_sqlite_or_socket=True,
        real_pending_runtime_files_unchanged=True, native_store_absent=True, service_store_absent=True,
        real_ledger_and_events_absent=True, sdk=read(OUT / "sdk-check.json"), first_failure=read(OUT / "failure-check.json"),
        app_launched=False, service_started=False, actual_model_requests=0, actual_web_operations=0))
    print(f"PASS: {len(cases)} approval cases, real pending App-child/launcher/external audit, fake SDK 20/0 cap and startup first-failure stop; real 0/0.")


if __name__ == "__main__":
    if "--sdk" in sys.argv: sdk_fixture()
    elif "--failure" in sys.argv: sdk_fixture(True)
    else: main()
