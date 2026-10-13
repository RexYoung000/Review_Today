import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeMemoryQA: App {
    let container: ModelContainer
    let fixture: MemoryWindowFixture
    init() {
        precondition(AppRuntime.current.isPreview)
        container = try! ModelContainer(for: M1DebugFixture.schema,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        fixture = try! MemoryWindowFixture(container.mainContext)
    }
    var body: some Scene {
        WindowGroup("记忆失效 · 隔离检查") {
            MemoryQARoot(fixture: fixture).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

@MainActor final class MemoryWindowFixture {
    let context: ModelContext
    let origin: AgentSession
    let destination: AgentSession
    let response: AgentMessage
    let input: [String: Any]
    init(_ context: ModelContext) throws {
        self.context = context
        context.autosaveEnabled = false
        let url = URL(fileURLWithPath: ProcessInfo.processInfo.environment["REVIEW_TODAY_QA_INPUT"]!)
        let data = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        input = data
        origin = AgentSession(id: UUID(uuidString: data["origin_session_id"] as! String)!, title: "合成索引旧课")
        destination = AgentSession(id: UUID(uuidString: data["destination_session_id"] as! String)!, title: "记忆失效 · 隔离检查")
        context.insert(origin); context.insert(destination)
        LearningMemory.store(data["candidate"] as! [String: Any], session: origin)
        try context.save()
        try ConversationProcessor.persist(data["before"] as! [String: Any], session: destination, context: context)
        let runID = UUID(uuidString: data["run_id"] as! String)!
        response = try context.fetch(FetchDescriptor<AgentMessage>()).first { $0.runID == runID && $0.responseState == "recovering" }!
        let user = AgentMessage(sessionID: destination.id, role: "user", content: "用索引解释 RAG 检索", deliveryStatus: "accepted")
        user.runID = runID; user.createdAt = response.createdAt.addingTimeInterval(-10)
        context.insert(user); try context.save()
        try report("initial")
    }
    func exclude() throws {
        precondition(LearningMemory.setAllowed(false, session: origin, context: context))
        precondition(response.responseState == "interrupted" && response.content.contains("合成初稿"))
        try report("immediate")
    }
    func syncStop() async throws {
        let control = try context.fetch(FetchDescriptor<AgentRunControl>()).first { $0.action == "stop" }!
        try await ConversationProcessor.deliverControl(control, context: context, request: { _, _ in
            self.input["stop_receipt"] as! [String: Any]
        })
        precondition(response.responseState == "interrupted")
        try ConversationProcessor.persist(input["after"] as! [String: Any], session: destination, context: context)
        precondition(response.responseState == "interrupted" && response.content.contains("合成初稿"))
        try report("synced")
    }
    private func report(_ phase: String) throws {
        let output = URL(fileURLWithPath: ProcessInfo.processInfo.environment["REVIEW_TODAY_QA_OUTPUT"]!)
        var rows = (try? JSONSerialization.jsonObject(with: Data(contentsOf: output))) as? [[String: Any]] ?? []
        rows.append(["phase": phase, "reply_state": response.responseState, "reply_text": response.content,
                     "knowledge_count": try context.fetchCount(FetchDescriptor<Knowledge>()),
                     "review_count": try context.fetchCount(FetchDescriptor<ReviewAttempt>()),
                     "memory_allowed": origin.memoryUseAllowed, "preview": AppRuntime.current.isPreview])
        try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys]).write(to: output)
    }
}

struct MemoryQARoot: View {
    let fixture: MemoryWindowFixture
    @State private var selected: UUID?
    @State private var monitor = AgentServiceMonitor()
    @State private var phase = 0
    @State private var dark = false
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("隔离检查 · 合成服务事件 · 不调用模型").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark)
                Button("排除来源记忆") { try! fixture.exclude(); phase = 1 }.disabled(phase != 0)
                Button("同步停止结果") { Task { try! await fixture.syncStop(); phase = 2 } }.disabled(phase != 1)
            }.controlSize(.small).padding(8)
            LearningWorkspace(monitor: monitor, selectedSessionID: $selected, onOpenKnowledge: { _ in })
        }.frame(minWidth: 760, minHeight: 620)
            .preferredColorScheme(dark ? .dark : .light)
            .onAppear { selected = fixture.destination.id }
    }
}
