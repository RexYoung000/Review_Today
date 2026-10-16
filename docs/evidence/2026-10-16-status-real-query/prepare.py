"""Prepare the approved last request. Does not launch UI or contact any model."""
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
    assert not (EVIDENCE / "setup.json").exists(), "Never reset a prepared real request"
    prior = json.loads((EVIDENCE.parent / "2026-10-16-status-native-input/setup.json").read_text())
    old = Path(prior["old_runtime"])
    assert (old / "STOP").exists() and json.loads((old / "request-count.json").read_text())["actual_requests"] == 29
    assert all(digest(ROOT / name) == value for name, value in prior["swift_source_sha256"].items())
    assert all(digest(ROOT / name) == value for name, value in prior["provider_config_sha256"].items())
    support_setup = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(support_setup["support_dir"])
    assert digest(support / "libReviewTodayContractSupport.dylib") == support_setup["support_library_sha256"]
    directory = Path(tempfile.mkdtemp(prefix="review-today-status-real-", dir="/tmp"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port != 8742
    source = ROOT / prior["source_checkpoint"]
    assert digest(source) == prior["source_sha256"]
    original = json.loads(source.read_text())
    shutil.copy2(source, directory / "source-checkpoint.json")
    with sqlite3.connect(f"file:{old / 'app.store'}?mode=ro", uri=True) as source_store:
        target = sqlite3.connect(directory / "app.store")
        source_store.backup(target)
        target.close()
    for name in (".app_SUPPORT", "ReviewBackups"):
        shutil.copytree(old / name, directory / name)
    shutil.copy2(old / "app.store.review-v2-backup", directory / "app.store.review-v2-backup")
    (directory / "qa-config.json").write_text(json.dumps(dict(session_id=original["session_id"])))
    shutil.copy2(old / "request-count.json", directory / "request-count.json")
    authorization = dict(starting_requests=29, additional_request_limit=1, original_limit=30,
        provider_config_sha256=prior["provider_config_sha256"],
        user_confirmation="用剩余 1 次验证（推荐）", no_retry=True)
    (directory / "qa-authorization.json").write_text(json.dumps(authorization, ensure_ascii=False, indent=2)+"\n")
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"), REVIEW_TODAY_JEV_TEST="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
    with store.transaction(original["session_id"]) as data:
        data.update(copy.deepcopy(original))
    before = store.get(original["session_id"])
    assert store.last_seq(before) == 130
    (directory / "backend-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2)+"\n")
    service = directory / "owned-project/agent-service"
    (service / ".venv/bin").mkdir(parents=True)
    real = ROOT / "agent-service"
    (service / ".venv/bin/python").symlink_to(real / ".venv/bin/python")
    shutil.copy2(real / ".venv/pyvenv.cfg", service / ".venv/pyvenv.cfg")
    (service / ".venv/lib").symlink_to(real / ".venv/lib", target_is_directory=True)
    (service / "sitecustomize.py").write_text(
        "import os, sys\ntry:\n"+f"    sys.path.insert(0, {str(real)!r})\n"+
        f"    sys.path.insert(0, {str(EVIDENCE)!r})\n    import bootstrap\n"+
        f"    bootstrap.install({str(directory)!r}, {str(ROOT)!r})\n"+
        "except BaseException as exc:\n    print('QA_BOOTSTRAP_FAILED:' + type(exc).__name__, flush=True)\n    os._exit(74)\n")
    previous_entry = (EVIDENCE.parent / "2026-10-16-status-native-input/NativeStatusInputQA.swift").read_text()
    old_input = json.loads((EVIDENCE.parent / "2026-10-16-status-native-input/setup.json").read_text())
    entry = previous_entry.replace(old_input["directory"], str(directory)).replace(f'"{old_input["port"]}"', f'"{port}"')
    entry = entry.replace("NativeStatusInputQA", "NativeStatusRealQA").replace("状态查询 · 原生输入受控验收", "状态查询 · 真实单次验收")
    entry = entry.replace("原生输入受控检查 · 冻结模型判断 · 新模型请求 0", "真实状态查询 · 只用最后 1 次 · 总上限 30 次")
    native_entry = EVIDENCE / "NativeStatusRealQA.swift"
    native_entry.write_text(entry)
    app = directory / "StatusRealQA.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    info = dict(CFBundleIdentifier="Rex.Review-Today.StatusReal.NativeQA", CFBundleExecutable="StatusRealQA",
        CFBundleName="StatusRealQA", CFBundlePackageType="APPL", CFBundleVersion="1", CFBundleShortVersionString="1.0",
        NSPrincipalClass="NSApplication", NSHighResolutionCapable=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
        "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
        "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support),
        str(native_entry), "-o", str(app / "Contents/MacOS/StatusRealQA")]
    with (EVIDENCE / "native-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    setup = dict(directory=str(directory), port=port, native_app=str(app), session_id=original["session_id"],
        baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        starting_requests=29, additional_request_limit=1, total_limit=30, native_entry_sha256=digest(native_entry),
        native_binary_sha256=digest(app / "Contents/MacOS/StatusRealQA"),
        source_checkpoint=str(source.relative_to(ROOT)), source_sha256=digest(source), source_cursor=130,
        provider_config_sha256=prior["provider_config_sha256"], swift_source_sha256=prior["swift_source_sha256"],
        old_runtime=str(old), old_counter_sha256=digest(old / "request-count.json"), old_stop_sha256=digest(old / "STOP"),
        project_diff_sha256=hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest(),
        daily_files_before=[dict(path=x["path"], sha256=digest(x["path"])) for x in prior["daily_files_before"]],
        old_evidence_sha256={str(p.relative_to(ROOT)):digest(p) for folder in (
            EVIDENCE.parent / "2026-10-16-status-query-scope", EVIDENCE.parent / "2026-10-16-status-native-input",
            EVIDENCE.parent / "2026-10-16-native-save-continuation") for p in folder.rglob("*") if p.is_file() and p.suffix != ".pyc"})
    (EVIDENCE / "setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({k:setup[k] for k in ("directory", "port", "native_app", "starting_requests", "additional_request_limit")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
