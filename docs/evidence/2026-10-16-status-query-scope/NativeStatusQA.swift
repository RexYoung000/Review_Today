import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeStatusQA: App {
    let container: ModelContainer
    let session: AgentSession
    init() {
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", "/tmp/review-today-status-scope-2br8dy6h", 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_62549", "62549", 1)
        setenv("REVIEW_TODAY_JEV_TEST", "0", 1)
        precondition(AppRuntime.current.mode == .modelValidation)
        let directory = AppRuntime.current.validationDirectory!
        let container = try! M1DebugFixture.makeValidationContainer(directory)
        self.container = container
        let context = container.mainContext
        let config = try! JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("qa-config.json"))) as! [String: Any]
        let sid = UUID(uuidString: config["session_id"] as! String)!
        session = try! context.fetch(FetchDescriptor<AgentSession>()).first { $0.id == sid }!
        let oldCards = Set((try! context.fetch(FetchDescriptor<Knowledge>())).map(\.id))
        precondition(oldCards.count == 4)
        let page = try! JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("public-page.json"))) as! [String: Any]
        let events = page["events"] as! [[String: Any]]
        precondition((events.first?["seq"] as? Int) == session.lastSessionEventSeq + 1)
        try! ConversationProcessor.persist(page, session: session, context: context)
        try! context.save()
        precondition(Set((try! context.fetch(FetchDescriptor<Knowledge>())).map(\.id)) == oldCards)
    }
    var body: some Scene {
        WindowGroup("状态查询 · 受控回放 · 无模型请求") {
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
                Text("受控查询回放 · 原有真实 4 卡 · 新模型请求 0").font(.caption)
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
                monitor.useFixturePresentation()
            }
            .onChange(of: dark) { _, value in
                AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true)
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
                "messages": messages.map { ["id": $0.id.uuidString, "role": $0.role, "text": $0.content] }]
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
