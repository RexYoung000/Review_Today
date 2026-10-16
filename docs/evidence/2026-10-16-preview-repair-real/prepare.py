"""Prepare paused QA from the stopped real trial, without launching any app."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
TRIAL = EVIDENCE.parent / "2026-10-16-continuous-acceptance"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not (EVIDENCE / "setup.json").exists(), "Never reset an approved continuation"
    base = json.loads((TRIAL / "live/setup.json").read_text())
    old = Path(base["directory"])
    assert json.loads((old / "request-count.json").read_text()) == dict(actual_requests=20, limit=30)
    assert (old / "STOP").read_text().startswith("STOP: EVAL-03 same-topic update reached final")
    for group in ("provider_config_sha256", "swift_source_sha256"):
        assert all(digest(ROOT / name) == value for name, value in base[group].items()), group
    assert hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest() == base["project_diff_sha256"]
    resume = json.loads((TRIAL / "startup-diagnosis/resume-setup.json").read_text())
    app = Path(resume["app"])
    binary = app / "Contents/MacOS/ContinuousResumeQA"
    assert digest(binary) == resume["binary_sha256"]
    support_setup = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(support_setup["support_dir"])
    assert digest(support / "libReviewTodayContractSupport.dylib") == support_setup["support_library_sha256"]
    directory = Path(tempfile.mkdtemp(prefix="review-today-preview-repair-real-", dir="/tmp"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 8742
    old_files = {p.name: digest(p) for p in old.iterdir() if p.is_file()}
    for p in old.iterdir():
        if p.is_file() and (p.name.startswith("app.store") or p.name.startswith("checkpoint.sqlite3")):
            shutil.copy2(p, directory / p.name)
    for name in (".app_SUPPORT", "ReviewBackups"):
        shutil.copytree(old / name, directory / name)
    previous = json.loads((EVIDENCE.parent / "2026-10-16-preview-real-recheck/setup.json").read_text())
    parent23 = Path(previous["directory"])
    assert json.loads((parent23 / "request-count.json").read_text()) == dict(actual_requests=23, limit=30)
    assert (parent23 / "STOP").exists()
    source = TRIAL / "resumed/backend-after.json"
    original = json.loads(source.read_text())
    assert len(original["runs"]) == 4 and list(original["runs"].values())[-1]["status"] == "retryable_failed"
    assert next(iter(original["capture_offers"].values()))["version"] == 2
    (directory / "qa-config.json").write_text(json.dumps(dict(session_id=base["session_id"])))
    shutil.copy2(parent23 / "request-count.json", directory / "request-count.json")
    shutil.copy2(parent23 / "STOP", directory / "parent-STOP.txt")
    shutil.copy2(source, directory / "source-checkpoint.json")
    roles = json.loads((TRIAL / "resumed/startup-health.json").read_text())["model_roles"]
    assert all(value["status"] == "ready" for value in roles.values())
    (directory / "verified-roles.json").write_text(json.dumps(roles, ensure_ascii=False, indent=2) + "\n")
    authorization = dict(decision=240, parent_decision=239, batch_decision=237, new_batch=False, starting_requests=23, limit=30,
        additional_request_limit=7, user_confirmation="决定 239 修复交付并说明仅定向复验当前预览后，Rex 回复：继续",
        scope="only same-topic preview supplementation without saving or advancing",
        provider_config_sha256=base["provider_config_sha256"], verified_roles_sha256=digest(directory / "verified-roles.json"))
    (directory / "authorization.json").write_text(json.dumps(authorization, ensure_ascii=False, indent=2) + "\n")
    service = directory / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    real = ROOT / "agent-service"
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
    entry = (TRIAL / "startup-diagnosis/NativeContinuousResumeQA.swift").read_text()
    entry = entry.replace(str(old), str(directory)).replace('"49316"', json.dumps(str(port)))
    for type_name, count in (("AgentMessage", 8), ("LearningTask", 1), ("AgentRun", 4)):
        old_check = f"precondition(try! context.fetch(FetchDescriptor<{type_name}>()).isEmpty)"
        assert old_check in entry
        entry = entry.replace(old_check, f"precondition(try! context.fetch(FetchDescriptor<{type_name}>()).count == {count})")
    entry = entry.replace('precondition(session.lastSessionEventSeq == 0 && session.captureOffersJSON == "[]")',
        'precondition(session.lastSessionEventSeq == 121 && session.captureOffersJSON != "[]")')
    entry = entry.replace('WindowGroup("RAG · 完整连续验收")', 'WindowGroup("RAG · 预览修复真实复验")')
    entry = entry.replace('Text("连续验收续接 · 暂停等待项目授权 · 本批 0／30")',
        'Text(startupAuthorized ? "预览修复真实复验 · 累计请求以账本为准" : "预览修复真实复验 · 暂停 · 原累计 23／30")')
    entry = entry.replace('"native-resume-events.jsonl"', '"native-recheck-events.jsonl"')
    entry = entry.replace('record("resume_held")', 'record("recheck_held")')
    entry = entry.replace('"启动已暂停；先选择本项目文件夹，再检查运行环境。"', '"先检查运行环境；学习服务尚未启动，不调用模型。"')
    entry = entry.replace('if selectedProjectURL != nil {', 'if !startupAuthorized {')
    entry = entry.replace('guard selectedProjectURL != nil, !probeRunning, !startupAuthorized else', 'guard !probeRunning, !startupAuthorized else')
    entry = entry.replace('URL(fileURLWithPath: "/tmp/review-today-startup-diagnosis-1ux5ch6l")',
        'URL(fileURLWithPath: ' + json.dumps(str(probe)) + ')')
    target = EVIDENCE / "NativePreviewRecheckQA.swift"
    target.write_text(entry)
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
        "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
        "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support), str(target), "-o", str(binary)]
    with (EVIDENCE / "native-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    setup = dict(directory=str(directory), port=port, native_app=str(app), session_id=base["session_id"],
        baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
        starting_requests=23, limit=30, additional_request_limit=7, source_checkpoint=str(source.relative_to(ROOT)),
        source_sha256=digest(source), native_entry_sha256=digest(target), native_binary_sha256=digest(binary),
        provider_config_sha256=base["provider_config_sha256"], swift_source_sha256=base["swift_source_sha256"],
        python_source_sha256={str(p.relative_to(ROOT)): digest(p) for p in real.glob("agent_service/**/*.py")},
        daily_files_before=base["daily_files_before"], project_diff_sha256=base["project_diff_sha256"],
        parent_runtime=str(old), parent_runtime_sha256=old_files, parent_stop_sha256=digest(old / "STOP"),
        prior_native_app_backup=str(backup), prior_native_binary_sha256=resume["binary_sha256"],
        protected_archive_sha256={str(p.relative_to(ROOT)):digest(p) for folder in (
            TRIAL / "live", TRIAL / "startup-diagnosis", TRIAL / "resumed", EVIDENCE.parent / "2026-10-16-preview-deferral", EVIDENCE.parent / "2026-10-16-preview-real-recheck", EVIDENCE.parent / "2026-10-16-preview-repair")
            for p in folder.rglob("*") if p.is_file() and p.suffix != ".pyc"},
        previous_real_runtime=str(parent23), previous_real_runtime_sha256={p.name:digest(p) for p in parent23.iterdir() if p.is_file()},
        previous_real_archive_counter=23, same_batch_actual_probe_state_reused=True, new_model_outputs_frozen=False, service_initially_paused=True)
    (EVIDENCE / "setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:setup[k] for k in ("directory", "port", "native_app", "session_id", "starting_requests", "limit")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
