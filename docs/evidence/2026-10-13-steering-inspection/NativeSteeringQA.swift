import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeSteeringQA: App {
    let container: ModelContainer
    let fixture: SteeringWindowFixture
    init() {
        precondition(AppRuntime.current.isPreview)
        container = try! ModelContainer(for: M1DebugFixture.schema,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        fixture = try! SteeringWindowFixture(container.mainContext)
    }
    var body: some Scene {
        WindowGroup("补充接收 · 隔离检查") {
            SteeringQARoot(fixture: fixture).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

@MainActor final class SteeringWindowFixture {
    let context: ModelContext
    let session: AgentSession
    let oldRun: AgentRun
    let oldAnswer: AgentMessage
    let supplement: AgentMessage
    let next = UUID()
    let nextAnswer = UUID()
    let now = ISO8601DateFormatter().string(from: .now)
    init(_ context: ModelContext) throws {
        self.context = context
        session = AgentSession(title: "补充接收 · 隔离检查")
        oldRun = AgentRun(id: UUID(), sessionID: session.id)
        oldRun.status = "adjusting"; oldRun.stage = "responding"
        oldRun.userSummary = "已收到补充，正在调整"
        let original = AgentMessage(sessionID: session.id, role: "user", content: "检索在 RAG 中有什么作用？")
        original.createdAt = .now.addingTimeInterval(-30)
        original.runID = oldRun.id; original.deliveryStatus = "accepted"
        oldAnswer = AgentMessage(sessionID: session.id, role: "assistant", content: "检索负责找到资料……")
        oldAnswer.runID = oldRun.id; oldAnswer.responseState = "interrupted"
        oldAnswer.createdAt = .now.addingTimeInterval(-20)
        oldAnswer.responseRevision = 1; oldAnswer.responseChunkSeq = 1
        supplement = AgentMessage(sessionID: session.id, role: "user", content: "请用一个简单例子补充说明。")
        supplement.createdAt = .now.addingTimeInterval(-10)
        context.insert(session); context.insert(oldRun); context.insert(original)
        context.insert(oldAnswer); context.insert(supplement); try context.save()
        try ConversationProcessor.persist(page(finished: false), session: session, context: context)
    }
    func bodyRecord(_ id: UUID, run: UUID, text: String) -> [String: Any] {
        ["message_id": id.uuidString, "run_id": run.uuidString, "role": "coach", "content": text, "created_at": now]
    }
    func header(_ id: UUID) -> [String: Any] {
        ["session_id": session.id.uuidString, "run_id": id.uuidString, "revision": 1, "status": "completed",
         "lifecycle_revision": 0, "stage": "completed", "user_summary": "本轮已回应", "updated_at": now]
    }
    func event(_ seq: Int, record: [String: Any]) -> [String: Any] {
        ["session_id": session.id.uuidString, "run_id": record["run_id"]!, "event_id": UUID().uuidString,
         "seq": seq, "revision": 1, "lifecycle_revision": 0, "stage": "response.completed", "occurred_at": now,
         "message": record, "payload": ["response": ["response_id": record["message_id"]!, "revision": 1,
               "chunk_seq": 2, "status": "complete", "text": record["content"]!]]]
    }
    func page(finished: Bool) -> [String: Any] {
        let old = bodyRecord(oldAnswer.id, run: oldRun.id,
            text: "检索负责从资料库中找出相关内容，再把这些内容交给模型生成回答。它提供回答依据，但不保证找到的资料一定正确或相关。")
        let fresh = bodyRecord(nextAnswer, run: next,
            text: "例如，你问公司报销规则：系统先找到相关制度片段，再让模型根据这些片段回答。这就是检索为生成提供依据。")
        var runs = [oldRun.id.uuidString.lowercased(): header(oldRun.id)]
        if finished { runs[next.uuidString.lowercased()] = header(next) }
        let checkpoint: [String: Any] = ["session_id": session.id.uuidString, "lifecycle_revision": 0,
            "event_base_seq": finished ? 2 : 1, "events": [], "runs": runs,
            "messages": finished ? [old, fresh] : [old]]
        return ["session_id": session.id.uuidString, "runs": Array(runs.values), "paused": false,
                "events": [event(finished ? 2 : 1, record: finished ? fresh : old)],
                "recovery": ["version": finished ? 2 : 1, "checkpoint": checkpoint]]
    }
    func finish() throws {
        try ConversationProcessor.recordAcceptance(["run_id": next.uuidString, "revision": 1, "status": "accepted"],
                                                   message: supplement, context: context)
        try ConversationProcessor.persist(page(finished: true), session: session, context: context)
        let report: [String: Any] = ["old_status": oldRun.status, "old_answer_state": oldAnswer.responseState,
            "old_answer_text": oldAnswer.content, "new_status": try context.fetch(FetchDescriptor<AgentRun>()).first(where: { $0.id == next })!.status,
            "active_count": try context.fetch(FetchDescriptor<AgentRun>()).filter { ["adjusting", "accepted", "running"].contains($0.status) }.count,
            "knowledge_count": try context.fetch(FetchDescriptor<Knowledge>()).count]
        let output = URL(fileURLWithPath: ProcessInfo.processInfo.environment["REVIEW_TODAY_QA_OUTPUT"]!)
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: output)
    }
}

struct SteeringQARoot: View {
    let fixture: SteeringWindowFixture
    @State private var selected: UUID?
    @State private var monitor = AgentServiceMonitor()
    @State private var finished = false
    @State private var dark = false
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("隔离检查 · 合成消息 · 实际原生投影 · 不调用模型").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark)
                Button(finished ? "已同步完成" : "模拟接收并同步完成") { try! fixture.finish(); finished = true }
                    .disabled(finished)
            }.controlSize(.small).padding(8)
            LearningWorkspace(monitor: monitor, selectedSessionID: $selected, onOpenKnowledge: { _ in })
        }.frame(minWidth: 760, minHeight: 620)
            .preferredColorScheme(dark ? .dark : .light)
            .onAppear { selected = fixture.session.id }
    }
}
