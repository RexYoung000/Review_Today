"""Compile a no-network native projection of the controlled public event page."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import socket
import sqlite3
import subprocess


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    replay = json.loads((EVIDENCE / "replay-result.json").read_text())
    previous = ROOT / "docs/evidence/2026-10-16-native-save-continuation"
    old = Path(setup["old_runtime"])
    directory = Path(replay["directory"])
    assert not (EVIDENCE / "native-result.json").exists(), "Native evidence is already closed"
    assert (old / "STOP").exists() and json.loads((old / "request-count.json").read_text())["actual_requests"] == 29
    for name, value in setup["swift_source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
    for name in ("app.store",):
        with sqlite3.connect(f"file:{old / name}?mode=ro", uri=True) as source:
            target = sqlite3.connect(directory / name)
            source.backup(target)
            target.close()
    for name in (".app_SUPPORT", "ReviewBackups"):
        if (old / name).exists():
            shutil.copytree(old / name, directory / name)
    shutil.copy2(old / "app.store.review-v2-backup", directory / "app.store.review-v2-backup")
    shutil.copy2(EVIDENCE / "public-page.json", directory / "public-page.json")
    (directory / "qa-config.json").write_text(json.dumps(dict(session_id=replay["session_id"])))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # This port is never served. No service monitor, outbox or model loop runs.
    assert port != 8742
    old_entry = (previous / "repair/NativeVerifyQA.swift").read_text()
    beginning = '''import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeStatusQA: App {
    let container: ModelContainer
    let session: AgentSession
    init() {
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", "DIRECTORY", 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "PORT", 1)
        setenv("REVIEW_TODAY_JEV_TEST", "0", 1)
        precondition(AppRuntime.current.mode == .modelValidation)
        let directory = AppRuntime.current.validationDirectory!
        let container = try! M1DebugFixture.makeValidationContainer(directory)
        self.container = container
        let context = container.mainContext
        let config = try! JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("qa-config.json"))) as! [String: Any]
        let sid = UUID(uuidString: config["session_id"] as! String)!
        session = try! context.fetch(FetchDescriptor<AgentSession>()).first { $0.id == sid }!
        let oldCards = Set((try! context.fetch(FetchDescriptor<Knowledge>())).map(\\.id))
        precondition(oldCards.count == 4)
        let page = try! JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("public-page.json"))) as! [String: Any]
        let events = page["events"] as! [[String: Any]]
        precondition((events.first?["seq"] as? Int) == session.lastSessionEventSeq + 1)
        try! ConversationProcessor.persist(page, session: session, context: context)
        try! context.save()
        precondition(Set((try! context.fetch(FetchDescriptor<Knowledge>())).map(\\.id)) == oldCards)
    }
    var body: some Scene {
        WindowGroup("状态查询 · 受控回放 · 无模型请求") {
            LiveRoot(session: session).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

'''
    beginning = beginning.replace("DIRECTORY", str(directory)).replace("PORT", str(port))
    root = old_entry[old_entry.index("struct LiveRoot: View"):]
    root = root.replace("真实失败邀请重试 · 独立测试库 · 已用 23／30 次", "受控查询回放 · 原有真实 4 卡 · 新模型请求 0")
    root = root.replace("                monitor.start()", "                monitor.useFixturePresentation()")
    start = root.index("            .task { await ConversationSync().run")
    end = root.index("            .onDisappear", start)
    root = root[:start] + root[end:]
    entry = EVIDENCE / "NativeStatusQA.swift"
    entry.write_text(beginning + root)
    support = Path(json.loads((previous / "setup.json").read_text())["support_dir"])
    app = directory / "StatusScopeQA.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    info = dict(CFBundleIdentifier="Rex.Review-Today.StatusScope.NativeQA", CFBundleExecutable="StatusScopeQA",
                CFBundleName="StatusScopeQA", CFBundleDisplayName="StatusScopeQA", CFBundlePackageType="APPL",
                CFBundleVersion="1", CFBundleShortVersionString="1.0", NSPrincipalClass="NSApplication",
                NSHighResolutionCapable=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    cmd = ["xcrun", "swiftc", "-parse-as-library", "-D", "DEBUG", "-swift-version", "5", "-default-isolation", "MainActor",
           "-enable-upcoming-feature", "MemberImportVisibility", "-I", str(support), "-L", str(support),
           "-lReviewTodayContractSupport", "-lFSRS", "-Xlinker", "-rpath", "-Xlinker", str(support),
           str(entry), "-o", str(app / "Contents/MacOS/StatusScopeQA")]
    with (EVIDENCE / "native-build.log").open("w") as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(app)], stdout=output, stderr=subprocess.STDOUT, check=True)
    result = dict(directory=str(directory), native_app=str(app), native_port_unused=port, model_requests=0,
                  scope="Production event projection and workspace using frozen router output, copied real native cards; no live service or sync loop",
                  source_cursor=replay["source_cursor"], session_id=replay["session_id"],
                  source_entry_sha256=hashlib.sha256(entry.read_bytes()).hexdigest(),
                  binary_sha256=hashlib.sha256((app / "Contents/MacOS/StatusScopeQA").read_bytes()).hexdigest())
    (EVIDENCE / "native-setup.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
