"""Only the approved, isolated App may create one guarded service process."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import types

OUT = Path(__file__).resolve().parent


def check_approved(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    setup = json.loads((OUT / "setup.json").read_text())
    assert directory == Path(setup["directory"])
    spec = json.loads((directory / "authorization.json").read_text())
    if spec.get("status") != "approved" or any((directory / n).exists() for n in ["HOLD", "STOP"]):
        raise PermissionError("pending/HOLD/STOP: new 20/0 batch is not active")
    assert spec["batch_id"] == setup["batch_id"]
    assert (spec["actual_model_request_limit"], spec["provider_web_operation_limit"]) == (20, 0)
    assert spec["scope"] == setup["scope"]
    assert spec["plan_sha256"] == hashlib.sha256((OUT / "plan.json").read_bytes()).hexdigest()
    assert spec["source_pins_sha256"] == hashlib.sha256((OUT / "source-pins.json").read_bytes()).hexdigest()
    assert not (directory / "bootstrap-ready.json").exists() and not (directory / "startup-claim.json").exists()
    for name, value in json.loads((OUT / "source-pins.json").read_text()).items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == value, name
    for name, value in setup.get("post_exit_native_dependencies", {}).items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == value, name
    return setup


def install(directory, root):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    setup = check_approved(directory, root)
    assert Path(os.environ["REVIEW_TODAY_HARNESS_DB"]).resolve() == directory / "checkpoint.sqlite3"
    assert Path(os.environ["REVIEW_TODAY_REVIEW_DB"]).resolve() == directory / "review.sqlite3"
    assert int(os.environ["REVIEW_TODAY_SERVICE_PORT"]) == setup["port"]
    parent = os.getppid()
    buf = ctypes.create_string_buffer(4096)
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    assert library.proc_pidpath(parent, buf, len(buf)) > 0
    parent_path = Path(os.fsdecode(buf.value)).resolve()
    assert parent_path == Path(setup["native_app"]) / "Contents/MacOS/Review_Today", "Service was not launched by the prepared App"
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
        ("decision=249", "decision='managed-teaching-after-273'"),
        ("limits=dict(model=24, web=16)", "limits=dict(model=20, web=0)"),
    ]:
        assert source.count(old) == 1
        source = source.replace(old, new)
    module = types.ModuleType("managed_teaching_observer")
    module.__file__ = str(OUT / "bootstrap.py")
    exec(compile(source, str(source_file), "exec"), module.__dict__)
    module.install(directory, root)
    from agent_service import config
    assert Path(config.HARNESS_DB).resolve() == directory / "checkpoint.sqlite3" and config.PORT == setup["port"]
    (directory / "bootstrap-ready.json").write_text(json.dumps(claim, indent=2) + "\n")
