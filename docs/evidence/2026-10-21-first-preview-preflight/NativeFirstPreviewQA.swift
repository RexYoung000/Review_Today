import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeContinuousResumeQA: App {
    let container: ModelContainer
    let session: AgentSession
    init() {
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", "/tmp/review-today-first-preview-pending-8dzum5y0", 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "49384", 1)
        setenv("REVIEW_TODAY_PROJECT_ROOT", "/tmp/review-today-first-preview-pending-8dzum5y0/owned-project", 1)
        setenv("REVIEW_TODAY_JEV_TEST", "0", 1)
        precondition(AppRuntime.current.mode == .modelValidation)
        let directory = AppRuntime.current.validationDirectory!
        let disk = try! M1DebugFixture.makeValidationContainer(directory)
        container = disk
        let context = disk.mainContext
        precondition(try! context.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<Source>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<AgentMessage>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<LearningTask>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<AgentRun>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<FsrsState>()).isEmpty)
        precondition(try! context.fetch(FetchDescriptor<AgentSession>()).isEmpty)
        let sid = UUID(uuidString: "a223ea4d-869d-4620-8a44-67495ba4a80d")!
        session = AgentSession(id: sid, title: "RAG · 首次预览复验", modePreset: "source_learning")
        session.learningChecklistExpanded = true
        context.insert(session)
        try! context.save()
    }
    var body: some Scene {
        WindowGroup("RAG · 首次知识预览复验") {
            LiveRoot(session: session).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

struct LiveRoot: View {
    let session: AgentSession
    @Environment(\.modelContext) private var context
    @State private var monitor = AgentServiceMonitor()
    @State private var selected: UUID?
    @State private var knowledge: UUID?
    @State private var showLibrary = false
    @State private var coordinator = ReviewCoordinator()
    @State private var observer: NSObjectProtocol?
    @State private var dark = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(startupAuthorized ? "首次知识预览复验 · 累计请求以账本为准" : "首次知识预览复验 · 暂停 · 待确认新批 0／20；网页禁用").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark)
                Button("记录当前状态") { record("snapshot") }
                if showLibrary { Button("回到学习") { showLibrary = false } }
            }.controlSize(.small).padding(8)
            projectFolderControls
            if showLibrary {
                LibraryView(selectedID: $knowledge, coordinator: coordinator)
            } else {
                LearningWorkspace(monitor: monitor, selectedSessionID: $selected,
                    onOpenKnowledge: { id in knowledge = id; showLibrary = true; record("open_details") })
            }
        }.frame(minWidth: 760, minHeight: 620)
            .onAppear {
                selected = session.id
                dark = AppearanceController.shared.isDark
                observer = NotificationCenter.default.addObserver(forName: .knowledgeIngestionSaved, object: nil, queue: .main) { note in
                    MainActor.assumeIsolated {
                        guard let c = note.object as? ModelContext, c === context,
                              let receipt = note.userInfo?["receipt"] as? KnowledgeIngestionReceipt,
                              receipt.sessionID == session.id else { return }
                        record("durable_receipt", receipt: receipt)
                    }
                }
                record("first_preview_fresh_held")
            }
            .onChange(of: dark) { _, value in
                AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true)
            }
            .task(id: startupAuthorized) {
                guard startupAuthorized else { return }
                await ConversationSync().run(context: context, monitor: monitor)
            }
            .task(id: startupAuthorized) {
                guard startupAuthorized else { return }
                // Match the production ContentView's existing local commit loop.
                while !Task.isCancelled {
                    await HarnessProcessor.tick(context: context, monitor: monitor)
                    await CaptureProcessor.tick(context: context, monitor: monitor)
                    try? await Task.sleep(for: .seconds(2))
                }
            }
            .onDisappear { monitor.stop() }
    }

    @State private var startupAuthorized = false
    @State private var selectedProjectURL: URL?
    @State private var folderPanel: NSOpenPanel?
    @State private var permissionNotice = "先检查运行环境；学习服务尚未启动，不调用模型。"
    @State private var probeRunning = false
    @State private var probeReady = false

    private var projectFolderControls: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(permissionNotice).font(.caption)
            HStack {
                Button("选择 Review_Today 项目文件夹") { chooseProjectFolder() }
                    .disabled(probeRunning || startupAuthorized)
                if !startupAuthorized {
                    Button("检查运行环境（不调用模型）") { Task { await checkInterpreter() } }
                        .disabled(probeRunning || startupAuthorized)
                }
                if probeReady && !startupAuthorized {
                    Button("开始已授权的学习验收") {
                        guard let directory = AppRuntime.current.validationDirectory,
                              !FileManager.default.fileExists(atPath: directory.appendingPathComponent("STOP").path) else {
                            permissionNotice = "环境检查通过；暂停记录仍保留，学习验收尚未启动。"
                            return
                        }
                        record("resume_start")
                        startupAuthorized = true
                        monitor.start()
                    }
                }
            }
        }.padding(.horizontal, 8).padding(.bottom, 8)
    }

    private func chooseProjectFolder() {
        let expected = URL(fileURLWithPath: "/Users/rexyoung/Desktop/vibe coding/Review_Today", isDirectory: true)
        let panel = NSOpenPanel()
        panel.title = "为隔离验收选择项目文件夹"
        panel.message = "仅选择 Review_Today 项目，用于加载运行环境与现有模型配置。选择后先检查环境，不会自动开始模型调用。"
        panel.prompt = "选择此项目"
        panel.canChooseFiles = false; panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false; panel.canCreateDirectories = false
        panel.directoryURL = expected
        folderPanel = panel
        panel.begin { response in
            guard response == .OK, let url = panel.url else {
                permissionNotice = "未授予项目访问；学习服务继续暂停。"
                folderPanel = nil
                return
            }
            guard url.standardizedFileURL.resolvingSymlinksInPath() == expected.standardizedFileURL.resolvingSymlinksInPath() else {
                permissionNotice = "请选择 Review_Today 项目本身；服务仍暂停。"
                folderPanel = nil
                return
            }
            _ = url.startAccessingSecurityScopedResource()
            selectedProjectURL = url
            permissionNotice = "已选择本项目；请先检查运行环境，学习服务仍暂停。"
            record("project_folder_selected")
            folderPanel = nil
        }
    }

    private func checkInterpreter() async {
        guard !probeRunning, !startupAuthorized else { return }
        probeRunning = true; probeReady = false
        permissionNotice = "正在检查依赖目录访问（最多 15 秒）；不运行学习服务。"
        let directory = URL(fileURLWithPath: "/tmp/review-today-first-preview-pending-8dzum5y0/probe")
        let qa = AppRuntime.current.validationDirectory!
        let outputURL = directory.appendingPathComponent("permission-probe.stdout")
        let errorURL = directory.appendingPathComponent("permission-probe.stderr")
        FileManager.default.createFile(atPath: outputURL.path, contents: nil)
        FileManager.default.createFile(atPath: errorURL.path, contents: nil)
        let output = try! FileHandle(forWritingTo: outputURL)
        let errors = try! FileHandle(forWritingTo: errorURL)
        let process = Process()
        process.executableURL = qa.appendingPathComponent("owned-project/agent-service/.venv/bin/python")
        process.currentDirectoryURL = directory
        process.arguments = ["-u", "-c", "print('RT.DIAG.PERMISSION_READY', flush=True)"]
        let inherited = ProcessInfo.processInfo.environment
        var environment: [String: String] = [
            "PATH": inherited["PATH"] ?? "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": inherited["HOME"] ?? NSHomeDirectory(), "TMPDIR": inherited["TMPDIR"] ?? NSTemporaryDirectory(),
            "LANG": inherited["LANG"] ?? "zh_CN.UTF-8", "PYTHONUNBUFFERED": "1", "PYTHONPATH": directory.path,
        ]
        for key in ["USER", "LOGNAME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"] {
            if let value = inherited[key] { environment[key] = value }
        }
        process.environment = environment; process.standardOutput = output; process.standardError = errors
        let started = Date()
        do {
            try process.run()
            while process.isRunning && Date().timeIntervalSince(started) < 15 {
                try? await Task.sleep(for: .milliseconds(100))
            }
            let timedOut = process.isRunning
            if timedOut { process.terminate() }
            process.waitUntilExit()
            try? output.close(); try? errors.close()
            let text = (try? String(contentsOf: outputURL, encoding: .utf8)) ?? ""
            probeReady = !timedOut && process.terminationStatus == 0 && text.contains("RT.DIAG.PERMISSION_READY")
            let row: [String: Any] = ["timed_out": timedOut, "exit": process.terminationStatus,
                "seconds": Date().timeIntervalSince(started), "ready": probeReady, "model_calls": 0]
            let data = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .prettyPrinted])
            try! data.write(to: directory.appendingPathComponent("permission-probe-result.json"))
            permissionNotice = probeReady ? "依赖加载检查通过；学习服务尚未启动。" : "依赖加载仍受阻；已停止，不启动学习服务。"
            record(probeReady ? "permission_probe_ready" : "permission_probe_failed")
        } catch {
            try? output.close(); try? errors.close()
            permissionNotice = "运行环境检查未能启动；学习服务继续暂停。"
        }
        probeRunning = false
    }

    private func record(_ phase: String, receipt: KnowledgeIngestionReceipt? = nil) {
        do {
            // An independent context reads what is actually durable at this boundary.
            let reader = ModelContext(context.container)
            let cards = try reader.fetch(FetchDescriptor<Knowledge>())
            let tasks = try reader.fetch(FetchDescriptor<LearningTask>())
            let sources = try reader.fetch(FetchDescriptor<Source>())
            let messages = try reader.fetch(FetchDescriptor<AgentMessage>())
            var row: [String: Any] = ["phase": phase, "at": Date().timeIntervalSince1970,
                "session_id": session.id.uuidString, "mode": "modelValidation", "show_library": showLibrary,
                "selected_knowledge": knowledge?.uuidString ?? "", "knowledge_count": cards.count,
                "knowledge": cards.map { ["id": $0.id.uuidString, "title": $0.title,
                    "explanation": $0.explanation, "evidence": $0.evidenceExcerpt,
                    "review": $0.participatesInReview,
                    "origin_task": $0.originTaskID?.uuidString ?? "",
                    "origin_session": $0.originSessionID?.uuidString ?? ""] as [String: Any] },
                "sources": sources.map { ["id": $0.id.uuidString, "raw_text": $0.rawText] },
                "tasks": tasks.map { ["id": $0.id.uuidString, "status": $0.status, "mode": $0.mode,
                    "memory_committed": $0.memoryCommitted] as [String: Any] },
                "capture_offers_json": session.captureOffersJSON, "checkpoint_json": session.checkpointJSON ?? "", "cursor": session.lastSessionEventSeq, "runs": (try reader.fetch(FetchDescriptor<AgentRun>())).map { ["id": $0.id.uuidString, "status": $0.status] },
                "messages": messages.map { ["id": $0.id.uuidString, "role": $0.role, "text": $0.content, "delivery": $0.deliveryStatus, "run_id": $0.runID?.uuidString ?? "", "client_id": $0.clientMessageID?.uuidString ?? "", "response_state": $0.responseState] }]
            if let receipt {
                let ids = Set(cards.map(\.id))
                row["receipt_task"] = receipt.taskID.uuidString
                row["receipt_card_ids"] = receipt.knowledgeIDs.map(\.uuidString)
                row["receipt_already_durable"] = !receipt.knowledgeIDs.isEmpty && Set(receipt.knowledgeIDs).isSubset(of: ids)
            }
            let directory = AppRuntime.current.validationDirectory!
            let target = directory.appendingPathComponent("native-recheck-events.jsonl")
            var data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            data.append(10)
            if !FileManager.default.fileExists(atPath: target.path) { FileManager.default.createFile(atPath: target.path, contents: nil) }
            let handle = try FileHandle(forWritingTo: target)
            try handle.seekToEnd(); try handle.write(contentsOf: data); try handle.close()
        } catch {
            print("QA_RECORD_ERROR: \(type(of: error))", terminator: "\n")
        }
    }
}
