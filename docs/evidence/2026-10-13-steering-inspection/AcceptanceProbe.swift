import Foundation
import SwiftData
@testable import ReviewTodayContractSupport

/// Controlled local/server timing: old response completed before supplement admission.
/// Runs production acceptance and projection; no App launch, network or card writes.
@main
struct AcceptanceProbe {
    @MainActor static func main() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        context.autosaveEnabled = false
        let session = AgentSession()
        let oldRun = AgentRun(id: UUID(), sessionID: session.id)
        oldRun.status = "adjusting" // Actual optimistic send state in LearningWorkspace.
        oldRun.userSummary = "已收到补充，正在调整"
        let oldInput = AgentMessage(sessionID: session.id, role: "user", content: "解释检索的作用")
        oldInput.runID = oldRun.id; oldInput.deliveryStatus = "accepted"
        let oldAnswer = AgentMessage(sessionID: session.id, role: "assistant", content: "已显示的旧回答首段")
        oldAnswer.runID = oldRun.id; oldAnswer.responseState = "interrupted"
        oldAnswer.responseRevision = 1; oldAnswer.responseChunkSeq = 1
        let supplement = AgentMessage(sessionID: session.id, role: "user", content: "请补充一个例子")
        supplement.deliveryMode = "steer"
        context.insert(session); context.insert(oldRun); context.insert(oldInput)
        context.insert(oldAnswer); context.insert(supplement)
        try context.save()

        // Server has already completed oldRun, so it admits a new Run.
        let newRunID = UUID()
        try ConversationProcessor.recordAcceptance([
            "run_id": newRunID.uuidString, "status": "accepted", "revision": 1
        ], message: supplement, context: context)
        let afterAcceptance = oldRun.status
        let now = ISO8601DateFormatter().string(from: .now)
        func runHeader(_ id: UUID) -> [String: Any] {
            ["session_id": session.id.uuidString, "run_id": id.uuidString,
             "revision": 1, "status": "completed", "stage": "completed", "updated_at": now]
        }
        func completed(_ seq: Int, _ runID: UUID, _ answerID: UUID, _ text: String) -> [String: Any] {
            ["session_id": session.id.uuidString, "run_id": runID.uuidString,
             "event_id": UUID().uuidString, "seq": seq, "revision": 1,
             "stage": "response.completed", "occurred_at": now,
             "message": ["message_id": answerID.uuidString, "content": text, "created_at": now],
             "payload": ["response": ["response_id": answerID.uuidString, "revision": 1,
                           "chunk_seq": 2, "status": "complete", "text": text]]]
        }
        let newAnswerID = UUID()
        let page: [String: Any] = ["session_id": session.id.uuidString,
            "runs": [runHeader(oldRun.id), runHeader(newRunID)], "paused": false,
            "events": [completed(1, oldRun.id, oldAnswer.id, "旧回答已经完整结束"),
                       completed(2, newRunID, newAnswerID, "追加信息已正常回应")]]
        try ConversationProcessor.persist(page, session: session, context: context)
        try ConversationProcessor.persist(page, session: session, context: context) // repeated delivery
        let runs = try context.fetch(FetchDescriptor<AgentRun>())
        let messages = try context.fetch(FetchDescriptor<AgentMessage>())
        let active = runs.filter { ["accepted", "running", "stopping", "adjusting", "resuming"].contains($0.status) }
        let report: [String: Any] = ["kind": "controlled_native_acceptance_projection",
            "old_run_after_acceptance": afterAcceptance, "old_run_after_server_completion": oldRun.status,
            "old_answer_state": oldAnswer.responseState, "old_answer_text": oldAnswer.content,
            "new_run_status": runs.first(where: { $0.id == newRunID })?.status ?? "missing",
            "new_answer_text": messages.first(where: { $0.id == newAnswerID })?.content ?? "missing",
            "supplement_bound_to_new_run": supplement.runID == newRunID,
            "local_active_run_count_after_both_completed": active.count,
            "cursor": session.lastSessionEventSeq,
            "knowledge_count": try context.fetch(FetchDescriptor<Knowledge>()).count,
            "review_count": try context.fetch(FetchDescriptor<ReviewAttempt>()).count]
        print(String(data: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]),
                     encoding: .utf8)!)
        if CommandLine.arguments.contains("--expect-fixed") {
            precondition(oldRun.status == "completed" && oldAnswer.content == "旧回答已经完整结束")
            precondition(oldAnswer.responseState == "complete" && active.isEmpty)
        } else {
            precondition(oldRun.status == "adjusting", "baseline probe expects the stale optimistic state")
            precondition(oldAnswer.content == "已显示的旧回答首段" && active.count == 1)
        }
        precondition(supplement.runID == newRunID)
    }
}
