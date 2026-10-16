"""Prepare a paused native continuation; no UI launch, permission grant or model call."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def main():
    assert not (EVIDENCE / "resume-setup.json").exists(), "Do not replace a prepared permission continuation"
    original = json.loads((EVIDENCE.parent / "live/setup.json").read_text())
    qa = Path(original["directory"])
    assert json.loads((qa / "request-count.json").read_text()) == {"actual_requests": 0, "limit": 30}
    assert (qa / "STOP").read_text().startswith("HOLD:")
    source = (EVIDENCE.parent / "live/NativeContinuousQA.swift").read_text()
    source = source.replace("NativeContinuousQA", "NativeContinuousResumeQA")
    source = source.replace('precondition(try! context.fetch(FetchDescriptor<AgentSession>()).isEmpty)',
        'precondition(try! context.fetch(FetchDescriptor<LearningTask>()).isEmpty)\n'
        '        precondition(try! context.fetch(FetchDescriptor<AgentRun>()).isEmpty)\n'
        '        precondition(try! context.fetch(FetchDescriptor<FsrsState>()).isEmpty)')
    old = '''session = AgentSession(id: sid, title: "RAG · 全新连续验收", modePreset: "source_learning")
        session.learningChecklistExpanded = true
        context.insert(session)
        try! context.save()'''
    new = '''let existing = try! context.fetch(FetchDescriptor<AgentSession>())
        precondition(existing.count == 1 && existing[0].id == sid)
        session = existing[0]
        precondition(session.lastSessionEventSeq == 0 && session.captureOffersJSON == "[]")'''
    assert old in source
    source = source.replace(old, new)
    source = source.replace('"完整连续验收 · 新批上限 30 次 · 独立数据"', '"连续验收续接 · 暂停等待项目授权 · 本批 0／30"')
    source = source.replace('            if showLibrary {\n', '            projectFolderControls\n            if showLibrary {\n', 1)
    source = source.replace('                record("initial")\n                monitor.start()', '                record("resume_held")')
    source = source.replace('.task { await ConversationSync().run(context: context, monitor: monitor) }',
        '.task(id: startupAuthorized) {\n                guard startupAuthorized else { return }\n                await ConversationSync().run(context: context, monitor: monitor)\n            }')
    source = source.replace('            .task {\n                // Match', '            .task(id: startupAuthorized) {\n                guard startupAuthorized else { return }\n                // Match')
    source = source.replace('"native-events.jsonl"', '"native-resume-events.jsonl"')
    controls = (EVIDENCE / "permission_controls.swift.inc").read_text()
    source = source.replace('    private func record(', controls + '\n    private func record(', 1)
    assert source.count('monitor.start()') == 1
    entry = EVIDENCE / "NativeContinuousResumeQA.swift"
    entry.write_text(source)
    diag = Path(json.loads((EVIDENCE / "setup.json").read_text())["diagnostic_directory"])
    app = diag / "ContinuousResumeQA.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    info = dict(CFBundleIdentifier="Rex.Review-Today.ContinuousResume.NativeQA", CFBundleExecutable="ContinuousResumeQA",
        CFBundleName="ContinuousResumeQA", CFBundlePackageType="APPL", CFBundleVersion="1",
        NSPrincipalClass="NSApplication", NSHighResolutionCapable=True,
        NSDesktopFolderUsageDescription="为隔离验收加载已选择的 Review_Today 项目运行环境和现有模型配置。")
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    previous = json.loads((ROOT / "docs/evidence/2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(previous["support_dir"])
    assert hashlib.sha256((support / "libReviewTodayContractSupport.dylib").read_bytes()).hexdigest() == previous["support_library_sha256"]
    with (EVIDENCE / "resume-build.log").open("w") as output:
        subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5",
            "-default-isolation", "MainActor", "-enable-upcoming-feature", "MemberImportVisibility",
            "-I", str(support), "-L", str(support), "-lReviewTodayContractSupport", "-lFSRS",
            "-Xlinker", "-rpath", "-Xlinker", str(support), str(entry), "-o", str(app / "Contents/MacOS/ContinuousResumeQA")],
            stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    setup = dict(app=str(app), bundle_id=info["CFBundleIdentifier"], qa_runtime=str(qa),
        session_id=original["session_id"], request_count=0, limit=30, service_initially_paused=True,
        permission_granted=False, probe_run=False, selected_project=str(ROOT),
        original_entry_unchanged=True, original_binary_unchanged=True,
        source_sha256=hashlib.sha256(entry.read_bytes()).hexdigest(),
        binary_sha256=hashlib.sha256((app / "Contents/MacOS/ContinuousResumeQA").read_bytes()).hexdigest())
    (EVIDENCE / "resume-setup.json").write_text(json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    print(str(app))


if __name__ == "__main__":
    main()
