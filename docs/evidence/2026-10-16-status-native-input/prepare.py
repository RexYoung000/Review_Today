"""Prepare isolated stores and native production input; does not launch any app."""
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not (EVIDENCE / "setup.json").exists(), "Do not reset a prepared run"
    prior = json.loads((EVIDENCE.parent / "2026-10-16-status-query-scope/setup.json").read_text())
    old = Path(prior["old_runtime"])
    source_path = ROOT / prior["source_checkpoint"]
    assert digest(source_path) == prior["source_sha256"]
    assert (old / "STOP").exists() and json.loads((old / "request-count.json").read_text())["actual_requests"] == 29
    assert all(digest(ROOT / name) == value for name, value in prior["swift_source_sha256"].items())
    assert all(digest(ROOT / name) == value for name, value in prior["provider_config_sha256"].items())
    support_setup = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(support_setup["support_dir"])
    assert digest(support / "libReviewTodayContractSupport.dylib") == support_setup["support_library_sha256"]
    directory = Path(tempfile.mkdtemp(prefix="review-today-status-input-", dir="/tmp"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 8742
    original = json.loads(source_path.read_text())
    shutil.copy2(source_path, directory / "source-checkpoint.json")
    with sqlite3.connect(f"file:{old / 'app.store'}?mode=ro", uri=True) as source:
        target = sqlite3.connect(directory / "app.store")
        source.backup(target)
        target.close()
    for name in (".app_SUPPORT", "ReviewBackups"):
        shutil.copytree(old / name, directory / name)
    shutil.copy2(old / "app.store.review-v2-backup", directory / "app.store.review-v2-backup")
    (directory / "qa-config.json").write_text(json.dumps(dict(session_id=original["session_id"])))

    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"), REVIEW_TODAY_JEV_TEST="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
    with store.transaction(original["session_id"]) as data:
        data.update(copy.deepcopy(original))
    before = store.get(original["session_id"])
    assert store.last_seq(before) == 130
    (directory / "backend-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n")

    service = directory / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    real = ROOT / "agent-service"
    (service / ".venv/bin/python").symlink_to(real / ".venv/bin/python")
    shutil.copy2(real / ".venv/pyvenv.cfg", service / ".venv/pyvenv.cfg")
    (service / ".venv/lib").symlink_to(real / ".venv/lib", target_is_directory=True)
    (service / "sitecustomize.py").write_text(
        "import os, sys\ntry:\n" + f"    sys.path.insert(0, {str(real)!r})\n" +
        f"    sys.path.insert(0, {str(EVIDENCE)!r})\n    import bootstrap\n" +
        f"    bootstrap.install({str(directory)!r}, {str(ROOT)!r})\n" +
        "except BaseException as exc:\n    print('QA_BOOTSTRAP_FAILED:' + type(exc).__name__, flush=True)\n    os._exit(74)\n")
    entry = (EVIDENCE.parent / "2026-10-16-native-save-continuation/repair/NativeVerifyQA.swift").read_text()
    entry = entry.replace(str(old), str(directory)).replace('"50518"', f'"{port}"')
    entry = entry.replace("NativeLiveQA", "NativeStatusInputQA").replace("RAG · 原生保存隔离验收", "状态查询 · 原生输入受控验收")
    entry = entry.replace("真实失败邀请重试 · 独立测试库 · 已用 23／30 次", "原生输入受控检查 · 冻结模型判断 · 新模型请求 0")
    entry = entry.replace('"messages": messages.map { ["id": $0.id.uuidString, "role": $0.role, "text": $0.content] }]',
        '"cursor": session.lastSessionEventSeq, "runs": (try reader.fetch(FetchDescriptor<AgentRun>())).map { ["id": $0.id.uuidString, "status": $0.status] },\n' +
        '                "messages": messages.map { ["id": $0.id.uuidString, "role": $0.role, "text": $0.content, "delivery": $0.deliveryStatus, "run_id": $0.runID?.uuidString ?? "", "client_id": $0.clientMessageID?.uuidString ?? "", "response_state": $0.responseState] }]')
    native_entry = EVIDENCE / "NativeStatusInputQA.swift"
    native_entry.write_text(entry)
    app = directory / "StatusInputQA.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    info = dict(CFBundleIdentifier="Rex.Review-Today.StatusInput.NativeQA", CFBundleExecutable="StatusInputQA",
                CFBundleName="StatusInputQA", CFBundlePackageType="APPL", CFBundleVersion="1",
                CFBundleShortVersionString="1.0", NSPrincipalClass="NSApplication", NSHighResolutionCapable=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
           "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
           "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support),
           str(native_entry), "-o", str(app / "Contents/MacOS/StatusInputQA")]
    with (EVIDENCE / "native-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    setup = dict(directory=str(directory), port=port, native_app=str(app), baseline_commit=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), session_id=original["session_id"],
        source_checkpoint=str(source_path.relative_to(ROOT)), source_sha256=digest(source_path),
        source_cursor=130, original_requests=29, real_model_request_budget=0,
        old_runtime=str(old), old_counter_sha256=digest(old / "request-count.json"), old_stop_sha256=digest(old / "STOP"),
        provider_config_sha256=prior["provider_config_sha256"], swift_source_sha256=prior["swift_source_sha256"],
        daily_files_before=[dict(path=x["path"], sha256=digest(x["path"])) for x in prior["daily_files_before"]],
        project_diff_sha256=hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest(),
        old_evidence_sha256={str(p.relative_to(ROOT)):digest(p) for folder in (
            EVIDENCE.parent / "2026-10-16-status-query-scope", EVIDENCE.parent / "2026-10-16-native-save-continuation")
            for p in folder.rglob("*") if p.is_file()}, native_binary_sha256=digest(app / "Contents/MacOS/StatusInputQA"),
        synthetic_capability_ready=True, frozen_router=True, scope="Native input and local service; no new model judgment or save")
    (EVIDENCE / "setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:setup[k] for k in ("directory", "port", "native_app", "session_id", "real_model_request_budget")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
