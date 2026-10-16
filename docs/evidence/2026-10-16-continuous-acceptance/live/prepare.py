"""Build a new empty native QA. No model, HTTP or app launch here."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import socket
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert not (EVIDENCE/"setup.json").exists(), "Never reset an approved batch"
    prior = json.loads((ROOT/"docs/evidence/2026-10-16-status-real-query/setup.json").read_text())
    old = Path(prior["directory"])
    assert json.loads((old/"request-count.json").read_text())["actual_requests"] == 30 and (old/"STOP").exists()
    assert all(digest(ROOT/name)==value for name,value in prior["provider_config_sha256"].items())
    assert all(digest(ROOT/name)==value for name,value in prior["swift_source_sha256"].items())
    support_setup = json.loads((ROOT/"docs/evidence/2026-10-16-native-save-continuation/setup.json").read_text())
    support = Path(support_setup["support_dir"])
    assert digest(support/"libReviewTodayContractSupport.dylib") == support_setup["support_library_sha256"]
    directory = Path(tempfile.mkdtemp(prefix="review-today-continuous-",dir="/tmp"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port = sock.getsockname()[1]
    assert port != 8742
    sid = str(uuid.uuid4())
    (directory/"qa-config.json").write_text(json.dumps(dict(session_id=sid)))
    (directory/"request-count.json").write_text(json.dumps(dict(actual_requests=0,limit=30)))
    (directory/"authorization.json").write_text(json.dumps(dict(decision=237,new_batch=True,limit=30,
        user_confirmation="按新批 30 次上限验收（推荐）",provider_config_sha256=prior["provider_config_sha256"]),ensure_ascii=False,indent=2)+"\n")
    service = directory/"owned-project/agent-service"
    (service/".venv/bin").mkdir(parents=True)
    real = ROOT/"agent-service"
    (service/".venv/bin/python").symlink_to(real/".venv/bin/python")
    shutil.copy2(real/".venv/pyvenv.cfg",service/".venv/pyvenv.cfg")
    (service/".venv/lib").symlink_to(real/".venv/lib",target_is_directory=True)
    (service/"sitecustomize.py").write_text("import os,sys\ntry:\n"+
        f"    sys.path.insert(0,{str(real)!r})\n    sys.path.insert(0,{str(EVIDENCE)!r})\n"+
        f"    import bootstrap\n    bootstrap.install({str(directory)!r},{str(ROOT)!r})\n"+
        "except BaseException as exc:\n    print('QA_BOOTSTRAP_FAILED:'+type(exc).__name__,flush=True)\n    os._exit(74)\n")
    old_entry = (ROOT/"docs/evidence/2026-10-16-status-real-query/NativeStatusRealQA.swift").read_text()
    root = old_entry[old_entry.index("struct LiveRoot: View"):]
    root = root.replace("真实状态查询 · 只用最后 1 次 · 总上限 30 次","完整连续验收 · 新批上限 30 次 · 独立数据")
    root = root.replace('"cursor": session.lastSessionEventSeq,',
        '"capture_offers_json": session.captureOffersJSON, "checkpoint_json": session.checkpointJSON ?? "", "cursor": session.lastSessionEventSeq,')
    beginning = '''import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeContinuousQA: App {
    let container: ModelContainer
    let session: AgentSession
    init() {
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", "DIRECTORY", 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "PORT", 1)
        setenv("REVIEW_TODAY_PROJECT_ROOT", "DIRECTORY/owned-project", 1)
        setenv("REVIEW_TODAY_JEV_TEST", "0", 1)
        precondition(AppRuntime.current.mode == .modelValidation)
        let directory = AppRuntime.current.validationDirectory!
        let disk = try! M1DebugFixture.makeValidationContainer(directory)
        container = disk
        let context = disk.mainContext
        precondition(try! context.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<Source>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<AgentMessage>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<AgentSession>()).isEmpty)
        let sid = UUID(uuidString: "SESSION")!
        session = AgentSession(id: sid, title: "RAG · 全新连续验收", modePreset: "source_learning")
        session.learningChecklistExpanded = true
        context.insert(session)
        try! context.save()
    }
    var body: some Scene {
        WindowGroup("RAG · 完整连续验收") {
            LiveRoot(session: session).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

'''.replace('"DIRECTORY"',json.dumps(str(directory))).replace('"DIRECTORY/owned-project"',json.dumps(str(directory/"owned-project"))).replace('"PORT"',json.dumps(str(port))).replace('"SESSION"',json.dumps(sid))
    entry = EVIDENCE/"NativeContinuousQA.swift"
    entry.write_text(beginning+root)
    app = directory/"ContinuousQA.app"
    (app/"Contents/MacOS").mkdir(parents=True)
    info = dict(CFBundleIdentifier="Rex.Review-Today.Continuous.NativeQA",CFBundleExecutable="ContinuousQA",CFBundleName="ContinuousQA",
        CFBundlePackageType="APPL",CFBundleVersion="1",CFBundleShortVersionString="1.0",NSPrincipalClass="NSApplication",NSHighResolutionCapable=True)
    (app/"Contents/Info.plist").write_bytes(plistlib.dumps(info))
    cmd=["xcrun","swiftc","-parse-as-library","-D","DEBUG","-swift-version","5","-default-isolation","MainActor",
        "-enable-upcoming-feature","MemberImportVisibility","-I",str(support),"-L",str(support),"-lReviewTodayContractSupport","-lFSRS",
        "-Xlinker","-rpath","-Xlinker",str(support),str(entry),"-o",str(app/"Contents/MacOS/ContinuousQA")]
    with (EVIDENCE/"native-build.log").open("w") as output:
        subprocess.run(cmd,stdout=output,stderr=subprocess.STDOUT,check=True)
        subprocess.run(["codesign","--force","--sign","-",str(app)],stdout=output,stderr=subprocess.STDOUT,check=True)
        subprocess.run(["codesign","--verify","--strict",str(app)],stdout=output,stderr=subprocess.STDOUT,check=True)
    setup=dict(decision=237,directory=str(directory),port=port,native_app=str(app),session_id=sid,starting_requests=0,limit=30,
        baseline_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        native_entry_sha256=digest(entry),native_binary_sha256=digest(app/"Contents/MacOS/ContinuousQA"),
        provider_config_sha256=prior["provider_config_sha256"],swift_source_sha256=prior["swift_source_sha256"],
        python_source_sha256={str(p.relative_to(ROOT)):digest(p) for p in (ROOT/"agent-service/agent_service").rglob("*.py")},
        daily_files_before=[dict(path=x["path"],sha256=digest(x["path"])) for x in prior["daily_files_before"]],
        project_diff_sha256=hashlib.sha256(subprocess.check_output(["git","diff","--","Review_Today.xcodeproj/project.pbxproj"],cwd=ROOT)).hexdigest(),
        prior_runtime=str(old),prior_counter_sha256=digest(old/"request-count.json"),prior_stop_sha256=digest(old/"STOP"),
        prior_evidence_sha256={str(p.relative_to(ROOT)):digest(p) for folder in (
            ROOT/"docs/evidence/2026-10-16-status-real-query",ROOT/"docs/evidence/2026-10-16-native-save-continuation")
            for p in folder.rglob("*") if p.is_file() and p.suffix != ".pyc"},
        imported_model_outputs=False,imported_native_or_backend_data=False,reused_probe_results=False)
    (EVIDENCE/"setup.json").write_text(json.dumps(setup,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:setup[k] for k in ("directory","port","native_app","session_id","starting_requests","limit")},ensure_ascii=False))


if __name__ == "__main__":
    main()
