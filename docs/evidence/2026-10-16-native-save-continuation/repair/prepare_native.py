"""Prepare an isolated retry of the actual failed native save; never launches UI."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import socket
import sqlite3
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not (EVIDENCE / "result.json").exists(), "Closed real batch: never reset its cumulative request counter"
    previous = json.loads((EVIDENCE.parent / "setup.json").read_text())
    old = Path(previous["directory"])
    assert (old / "STOP").exists()
    assert json.loads((old / "request-count.json").read_text())["actual_requests"] == 23
    assert all(digest(ROOT / name) == value for name, value in previous["swift_source_sha256"].items())
    assert all(digest(ROOT / name) == value for name, value in previous["provider_config_sha256"].items())
    support = Path(previous["support_dir"])
    assert digest(support / "libReviewTodayContractSupport.dylib") == previous["support_library_sha256"]
    directory = Path(tempfile.mkdtemp(prefix="review-today-verify-save-", dir="/tmp"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 8742
    # Use SQLite's consistent backup, including rows still in a closed WAL.
    for name in ("app.store", "checkpoint.sqlite3"):
        source = sqlite3.connect(f"file:{old / name}?mode=ro", uri=True)
        target = sqlite3.connect(directory / name)
        source.backup(target)
        target.close()
        source.close()
    if (old / ".app_SUPPORT").exists():
        shutil.copytree(old / ".app_SUPPORT", directory / ".app_SUPPORT")
    # The cloned store has already completed the native migration. Preserve
    # its marker and recoverable backup as part of the same native snapshot.
    shutil.copy2(old / "app.store.review-v2-backup", directory / "app.store.review-v2-backup")
    shutil.copytree(old / "ReviewBackups", directory / "ReviewBackups")
    shutil.copy2(old / "qa-config.json", directory / "qa-config.json")
    (directory / "request-count.json").write_text(json.dumps(dict(actual_requests=23, limit=30)))
    service = directory / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    real_service = ROOT / "agent-service"
    (service / ".venv/bin/python").symlink_to(real_service / ".venv/bin/python")
    shutil.copy2(real_service / ".venv/pyvenv.cfg", service / ".venv/pyvenv.cfg")
    (service / ".venv/lib").symlink_to(real_service / ".venv/lib", target_is_directory=True)
    (service / "sitecustomize.py").write_text(
        "import sys\n" + f"sys.path.insert(0, {str(real_service)!r})\n" +
        f"sys.path.insert(0, {str(EVIDENCE)!r})\nimport bootstrap\n" +
        f"bootstrap.install({str(directory)!r}, {str(ROOT)!r})\n")
    entry = (EVIDENCE.parent / "NativeSaveQA.swift").read_text()
    entry = entry.replace(str(old), str(directory)).replace(str(previous["port"]), str(port))
    begin = entry.index("        // A continuation needs")
    end = entry.index("        session.learningChecklistExpanded", begin)
    entry = entry[:begin] + '        precondition(existing != nil, "Retry must preserve the actual failed native checkpoint")\n' + entry[end:]
    entry = entry.replace('if existing == nil { nativeContext.insert(session) }',
                          '// The copied native store already owns this failed invitation and cursor.')
    entry = entry.replace("真实保存续接 · 独立测试库 · 总上限 30 次", "真实失败邀请重试 · 独立测试库 · 已用 23／30 次")
    entry = entry.replace('            .task { await ConversationSync().run(context: context, monitor: monitor) }', "            .task { await ConversationSync().run(context: context, monitor: monitor) }\n            .task {\n                // Match the production ContentView's existing local commit loop.\n                while !Task.isCancelled {\n                    await HarnessProcessor.tick(context: context, monitor: monitor)\n                    await CaptureProcessor.tick(context: context, monitor: monitor)\n                    try? await Task.sleep(for: .seconds(2))\n                }\n            }\n            .onDisappear { monitor.stop() }")
    native_entry = EVIDENCE / "NativeVerifyQA.swift"
    native_entry.write_text(entry)
    app = directory / "VerifySaveQA.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    info = dict(CFBundleIdentifier="Rex.Review-Today.VerifySave.NativeQA", CFBundleExecutable="VerifySaveQA",
                CFBundleName="VerifySaveQA", CFBundleDisplayName="VerifySaveQA", CFBundlePackageType="APPL",
                CFBundleVersion="1", CFBundleShortVersionString="1.0", NSPrincipalClass="NSApplication",
                NSHighResolutionCapable=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
           "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
           "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support),
           str(native_entry), "-o", str(app / "Contents/MacOS/VerifySaveQA")]
    with (EVIDENCE / "native-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    setup = dict(directory=str(directory), native_app=str(app), port=port, session_id=previous["session_id"],
                 offer_id=previous["offer_id"], offer_version=previous["offer_version"], starting_requests=23,
                 actual_request_limit=30, max_additional_requests=7, previous_runtime=str(old),
                 resume="Consistent copies of the actual failed native and backend databases; no offer reset or fabricated ACK",
                 initial_knowledge_count=0, startup_probe_scope=previous["bootstrap_scope"],
                 native_entry_sha256=digest(native_entry), native_binary_sha256=digest(app / "Contents/MacOS/VerifySaveQA"),
                 bootstrap_sha256=digest(EVIDENCE / "bootstrap.py"),
                 production_fix_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                     [ROOT / "agent-service/agent_service/conversation.py", ROOT / "agent-service/agent_service/capture/__init__.py"]})
    (EVIDENCE / "setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(setup, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
