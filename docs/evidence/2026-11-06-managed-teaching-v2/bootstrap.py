"""Only the approved, isolated App may create one guarded service process."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import types

OUT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise PermissionError(message)


def check_approved(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    setup = json.loads((OUT / "setup.json").read_text())
    require(directory == Path(setup["directory"]), "Runtime directory changed")
    spec = json.loads((directory / "authorization.json").read_text())
    if spec.get("status") != "approved" or any((directory / n).exists() for n in ["HOLD", "STOP"]):
        raise PermissionError("pending/HOLD/STOP: new 20/0 batch is not active")
    require(spec["batch_id"] == setup["batch_id"], "Batch identity changed")
    require((spec["actual_model_request_limit"], spec["provider_web_operation_limit"]) == (20, 0), "Limits changed")
    require(spec["scope"] == setup["scope"], "Scope changed")
    require(spec["plan_sha256"] == hashlib.sha256((OUT / "plan.json").read_bytes()).hexdigest(), "Plan changed")
    require(spec["source_pins_sha256"] == hashlib.sha256((OUT / "source-pins.json").read_bytes()).hexdigest(), "Source pins changed")
    require(not (directory / "bootstrap-ready.json").exists() and not (directory / "startup-claim.json").exists(), "Startup already claimed")
    for name, value in json.loads((OUT / "source-pins.json").read_text()).items():
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == value, "Source changed: " + name)
    for name, value in setup.get("post_exit_native_dependencies", {}).items():
        require(hashlib.sha256(Path(name).read_bytes()).hexdigest() == value, "Dependency changed: " + name)
    return setup


def install(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    setup = check_approved(directory, root)
    require(Path(os.environ["REVIEW_TODAY_HARNESS_DB"]).resolve() == directory / "checkpoint.sqlite3", "Service DB not isolated")
    require(Path(os.environ["REVIEW_TODAY_REVIEW_DB"]).resolve() == directory / "review.sqlite3", "Review DB not isolated")
    require(int(os.environ["REVIEW_TODAY_SERVICE_PORT"]) == setup["port"], "Service port differs")
    from common import require_idle_port
    require_idle_port(8742)
    require_idle_port(setup["port"])
    parent = os.getppid()
    buf = ctypes.create_string_buffer(4096)
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    require(library.proc_pidpath(parent, buf, len(buf)) > 0, "Cannot identify parent")
    parent_path = Path(os.fsdecode(buf.value)).resolve()
    require(parent_path == (Path(setup["native_app"]) / "Contents/MacOS/Review_Today").resolve(), "Service was not launched by the prepared App")
    claim = dict(pid=os.getpid(), parent_pid=parent, parent_executable=str(parent_path), app_managed=True,
                 batch_id=setup["batch_id"], python_arguments=sys.orig_argv)
    with (directory / "startup-claim.json").open("x") as stream:
        json.dump(claim, stream, indent=2)
        stream.write("\n")
    import quota_20
    sys.modules["quota"] = quota_20
    source_file = root / "docs/evidence/2026-10-21-learning-save-real/bootstrap.py"
    source = source_file.read_text()
    for old, new in [
        ("evidence = root / 'docs/evidence/2026-10-21-learning-save-real'", "evidence = Path(__file__).resolve().parent"),
        ("decision=249", "decision=278"),
        ("limits=dict(model=24, web=16)", "limits=dict(model=20, web=0)"),
    ]:
        assert source.count(old) == 1
        source = source.replace(old, new)
    module = types.ModuleType("managed_teaching_observer")
    module.__file__ = str(OUT / "bootstrap.py")
    exec(compile(source, str(source_file), "exec"), module.__dict__)
    module.install(directory, root)
    from agent_service import config
    require(Path(config.HARNESS_DB).resolve() == directory / "checkpoint.sqlite3" and config.PORT == setup["port"], "Imported service config differs")
    (directory / "bootstrap-ready.json").write_text(json.dumps(claim, indent=2) + "\n")
