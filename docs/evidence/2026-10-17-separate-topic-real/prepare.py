"""Clone the actual 26-request result; prepare paused native QA without calls."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
PREVIOUS = EVIDENCE.parent / "2026-10-16-preview-repair-real"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files(directory):
    return {p.name: digest(p) for p in Path(directory).iterdir() if p.is_file()}


def main():
    assert not (EVIDENCE / "setup.json").exists(), "Never reset an approved continuation"
    previous = json.loads((PREVIOUS / "setup.json").read_text())
    old = Path(previous["directory"])
    assert json.loads((old / "request-count.json").read_text()) == dict(actual_requests=26, limit=30)
    assert (old / "STOP").read_text().startswith("STOP: KT-04 single real preview recheck finished at 26/30")
    for group in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256"):
        assert all(digest(ROOT / name) == value for name, value in previous[group].items()), group
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == previous["project_diff_sha256"]
    assert not subprocess.run(["pgrep", "-fl", "/ContinuousResumeQA.app/Contents/MacOS/"], capture_output=True, text=True).stdout.strip()
    app = Path(previous["native_app"])
    binary = app / "Contents/MacOS/ContinuousResumeQA"
    assert digest(binary) == previous["prior_native_binary_sha256"]
    support_setup = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(support_setup["support_dir"])
    assert digest(support / "libReviewTodayContractSupport.dylib") == support_setup["support_library_sha256"]
    source = PREVIOUS / "backend-after.json"
    original = json.loads(source.read_text())
    offer = next(iter(original["capture_offers"].values()))
    assert len(original["runs"]) == 5 and list(original["runs"].values())[-1]["status"] == "completed"
    assert offer["version"] == offer["preview_version"] == 3 and len(offer["preview_points"]) == 4
    native = json.loads((PREVIOUS / "native-disk-read.json").read_text())
    assert len(native["messages"]) == 10 and len(native["runs"]) == 5
    cursor = native["sessions"][0]["cursor"]
    daily = []
    for item in previous["daily_files_before"]:
        path = Path(item["path"])
        daily.append(dict(path=str(path), exists=path.exists(), sha256=digest(path) if path.exists() else None))
    directory = Path(tempfile.mkdtemp(prefix="review-today-separate-topic-real-", dir="/tmp"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 8742
    parent_runtimes = {name: dict(directory=path, sha256=files(path)) for name, path in (
        ("original_20", previous["parent_runtime"]), ("original_23", previous["previous_real_runtime"]),
        ("original_26", str(old)))}
    for path in old.iterdir():
        if path.is_file() and (path.name.startswith("app.store") or path.name.startswith("checkpoint.sqlite3")):
            shutil.copy2(path, directory / path.name)
    for name in (".app_SUPPORT", "ReviewBackups"):
        shutil.copytree(old / name, directory / name)
    for name in ("request-count.json", "verified-roles.json"):
        shutil.copy2(old / name, directory / name)
    shutil.copy2(old / "STOP", directory / "parent-STOP.txt")
    shutil.copy2(source, directory / "source-checkpoint.json")
    (directory / "qa-config.json").write_text(json.dumps(dict(session_id=previous["session_id"])))
    authorization = dict(decision=241, parent_decision=240, batch_decision=237, new_batch=False,
        starting_requests=26, limit=30, additional_request_limit=4,
        user_confirmation="原生预览交付并明确下一条为独立插问分开后，Rex 回复：继续",
        scope="one separate ordinary knowledge question; preserve original RAG offer and learning task; no save",
        provider_config_sha256=previous["provider_config_sha256"], verified_roles_sha256=digest(directory / "verified-roles.json"))
    (directory / "authorization.json").write_text(json.dumps(authorization, ensure_ascii=False, indent=2) + "\n")
    real = ROOT / "agent-service"
    service = directory / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    (service / ".venv/bin/python").symlink_to(real / ".venv/bin/python")
    shutil.copy2(real / ".venv/pyvenv.cfg", service / ".venv/pyvenv.cfg")
    (service / ".venv/lib").symlink_to(real / ".venv/lib", target_is_directory=True)
    (service / "sitecustomize.py").write_text("import os, sys\ntry:\n" +
        f"    sys.path.insert(0, {str(real)!r})\n    sys.path.insert(0, {str(EVIDENCE)!r})\n" +
        f"    import bootstrap\n    bootstrap.install({str(directory)!r}, {str(ROOT)!r})\n" +
        "except BaseException as exc:\n    print('QA_BOOTSTRAP_FAILED:' + type(exc).__name__, flush=True)\n    os._exit(74)\n")
    probe = directory / "probe"
    probe.mkdir()
    backup = directory / "prior-resume-app"
    shutil.copytree(app, backup)
    entry = (PREVIOUS / "NativePreviewRecheckQA.swift").read_text()
    entry = entry.replace(str(old), str(directory)).replace(json.dumps(str(previous["port"])), json.dumps(str(port)))
    entry = entry.replace("预览修复真实复验", "独立插问真实复验").replace("原累计 23／30", "原累计 26／30")
    for type_name, before, after in (("AgentMessage", 8, 10), ("AgentRun", 4, 5)):
        check = f"context.fetch(FetchDescriptor<{type_name}>()).count == {before}"
        assert check in entry
        entry = entry.replace(check, check.replace(str(before), str(after)))
    check = 'session.lastSessionEventSeq == 121 && session.captureOffersJSON != "[]"'
    assert check in entry
    entry = entry.replace(check, f'session.lastSessionEventSeq == {cursor} && session.captureOffersJSON != "[]"')
    entry = entry.replace('record("recheck_held")', 'record("separate_topic_held")')
    target = EVIDENCE / "NativeSeparateTopicQA.swift"
    target.write_text(entry)
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
        "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
        "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support), str(target), "-o", str(binary)]
    with (EVIDENCE / "native-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    archives = dict(previous["protected_archive_sha256"])
    archives.update({str(path.relative_to(ROOT)): digest(path) for path in PREVIOUS.rglob("*")
                     if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts})
    setup = dict(directory=str(directory), port=port, native_app=str(app), session_id=previous["session_id"],
        baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
        starting_requests=26, limit=30, additional_request_limit=4, source_checkpoint=str(source.relative_to(ROOT)),
        source_sha256=digest(source), native_entry_sha256=digest(target), native_binary_sha256=digest(binary),
        provider_config_sha256=previous["provider_config_sha256"], swift_source_sha256=previous["swift_source_sha256"],
        python_source_sha256=previous["python_source_sha256"], daily_files_before=daily,
        project_diff_sha256=previous["project_diff_sha256"], parent_runtimes=parent_runtimes,
        prior_native_app_backup=str(backup), prior_native_binary_sha256=previous["prior_native_binary_sha256"],
        protected_archive_sha256=archives, same_batch_actual_probe_state_reused=True,
        new_model_outputs_frozen=False, service_initially_paused=True, initial_native_cursor=cursor)
    (EVIDENCE / "setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: setup[k] for k in ("directory", "port", "native_app", "session_id", "starting_requests", "limit")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
