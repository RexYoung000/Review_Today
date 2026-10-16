import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeContinuousQA: App {
    let container: ModelContainer
    let session: AgentSession
    init() {
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", "/tmp/review-today-continuous-bnrjmda_", 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "49316", 1)
        setenv("REVIEW_TODAY_PROJECT_ROOT", "/tmp/review-today-continuous-bnrjmda_/owned-project", 1)
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
        let sid = UUID(uuidString: "4af445c0-3bd3-41a7-acb5-0e3f54b3344b")!
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
                Text("完整连续验收 · 新批上限 30 次 · 独立数据").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark)
                Button("记录当前状态") { record("snapshot") }
                if showLibrary { Button("回到学习") { showLibrary = false } }
            }.controlSize(.small).padding(8)
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
                record("initial")
                monitor.start()
            }
            .onChange(of: dark) { _, value in
                AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true)
            }
            .task { await ConversationSync().run(context: context, monitor: monitor) }
            .task {
                // Match the production ContentView's existing local commit loop.
                while !Task.isCancelled {
                    await HarnessProcessor.tick(context: context, monitor: monitor)
                    await CaptureProcessor.tick(context: context, monitor: monitor)
                    try? await Task.sleep(for: .seconds(2))
                }
            }
            .onDisappear { monitor.stop() }
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
            let target = directory.appendingPathComponent("native-events.jsonl")
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
