import Foundation
import SwiftData

@main
struct ConversationControlTests {
    static func require(_ value: Bool) { precondition(value) }
    @MainActor static func main() async throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let c = container.mainContext
        c.autosaveEnabled = false
        let session = AgentSession()
        let run = AgentRun(id: UUID(), sessionID: session.id)
        run.status = "retryable_failed"
        run.errorCode = "RT.MODEL.SCHEMA"
        let original = AgentMessage(sessionID: session.id, role: "user", content: "读取这份资料")
        original.runID = run.id
        c.insert(session); c.insert(run); c.insert(original)
        try c.save()
        for _ in 0..<20 { precondition(ConversationProcessor.queueControl(run, action: "retry", context: c)) }
        let controls = try c.fetch(FetchDescriptor<AgentRunControl>())
        precondition(controls.count == 1 && run.status == "resuming")
        precondition(run.userSummary == "正在重试，等待服务确认")
        let control = controls[0]
        let actionID = control.id.uuidString.lowercased()
        var now: String { ISO8601DateFormatter().string(from: Date.now.addingTimeInterval(2)) }
        func receipt(_ status: String = "accepted", revision: Int = 2) -> [String: Any] {
            ["run_id": run.id.uuidString, "session_id": session.id.uuidString, "revision": revision,
             "status": status, "stage": status, "user_summary": "服务已确认", "updated_at": now,
             "lifecycle_revision": 0]
        }
        do {
            try await ConversationProcessor.deliverControl(control, context: c) { _, body in
                precondition(body?["action_id"] as? String == actionID)
                throw URLError(.timedOut)
            }
            preconditionFailure("uncertain request must remain pending")
        } catch {}
        precondition(!control.sent && session.lastSessionEventSeq == 0)
        try await ConversationProcessor.deliverControl(control, context: c) { _, body in
            precondition(body?["action_id"] as? String == actionID)
            return receipt()
        }
        precondition(control.sent && control.lastError == nil)
        precondition(run.status == "accepted" && run.revision == 2)
        precondition(!ConversationProcessor.queueControl(run, action: "retry", context: c))
        precondition(session.lastSessionEventSeq == 0, "control receipt cannot consume unseen messages")

        // An idle failed Session must be read again after an accepted control,
        // including when generation finishes before the POST returns. An older
        // in-flight feed cannot swallow the new subscription request.
        var subscriptions = ConversationEventSubscriptions()
        let oldVersion = subscriptions.version(session.id)
        subscriptions.finish(session.id, version: oldVersion)
        precondition(!subscriptions.needsRefresh(session.id))
        subscriptions.refresh(session.id)
        subscriptions.finish(session.id, version: oldVersion)
        precondition(subscriptions.needsRefresh(session.id))
        subscriptions.finish(session.id, version: subscriptions.version(session.id))
        precondition(!subscriptions.needsRefresh(session.id))

        let answerID = UUID()
        let message: [String: Any] = ["message_id": answerID.uuidString, "content": "请补充资料正文。", "created_at": now]
        let page: [String: Any] = ["session_id": session.id.uuidString, "runs": [receipt("completed")], "events": [
            ["session_id": session.id.uuidString, "run_id": run.id.uuidString, "event_id": UUID().uuidString,
             "seq": 1, "revision": 2, "stage": "awaiting_material", "occurred_at": now, "message": message]], "paused": false]
        try ConversationProcessor.persist(page, session: session, context: c)
        precondition(run.status == "completed" && session.lastSessionEventSeq == 1)
        let answers = try c.fetch(FetchDescriptor<AgentMessage>()).filter { $0.role == "assistant" }
        precondition(answers.count == 1 && answers[0].content == "请补充资料正文。")
        try ConversationProcessor.persist(page, session: session, context: c)
        require(try c.fetch(FetchDescriptor<AgentMessage>()).count == 2)

        // Legacy duplicated retries are rejected by the server. They must settle
        // without losing the rejection or starving the user's queued cancel.
        let stale1 = AgentRunControl(runID: run.id, sessionID: session.id, action: "retry")
        let stale2 = AgentRunControl(runID: run.id, sessionID: session.id, action: "retry")
        c.insert(stale1); c.insert(stale2); try c.save()
        precondition(ConversationProcessor.queueControl(run, action: "cancel_task", context: c))
        precondition(!ConversationProcessor.queueControl(run, action: "retry", context: c))
        let pending = try c.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { !$0.sent }, sortBy: [SortDescriptor(\.createdAt)]))
        var posts: [String] = []
        for queued in pending {
            try await ConversationProcessor.deliverControl(queued, context: c) { _, body in
                guard let body else { return receipt("completed") }
                let action = body["action"] as! String
                posts.append(action)
                if action == "retry" {
                    throw HarnessAPIError.server(code: "RT.RUN.NOT_RETRYABLE", message: "已结束")
                }
                return receipt("interrupted", revision: 3)
            }
        }
        precondition(posts == ["retry", "retry", "cancel_task"])
        precondition(pending.allSatisfy { $0.sent })
        precondition(stale1.lastError == "RT.RUN.NOT_RETRYABLE" && stale2.lastError == "RT.RUN.NOT_RETRYABLE")
        precondition(run.status == "interrupted" && run.revision == 3)

        // Reject an unrelated receipt; never remove an uncertain control.
        let invalid = AgentRunControl(runID: run.id, sessionID: session.id, action: "resume")
        c.insert(invalid); try c.save()
        do {
            try await ConversationProcessor.deliverControl(invalid, context: c) { _, _ in
                var other = receipt(); other["run_id"] = UUID().uuidString; return other
            }
            preconditionFailure("wrong Run receipt must not acknowledge control")
        } catch {}
        precondition(!invalid.sent && run.revision == 3)
        try await ConversationProcessor.deliverControl(invalid, context: c) { _, _ in receipt(revision: 2) }
        precondition(invalid.sent && run.revision == 3 && run.status == "interrupted")
        require(try c.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        print("PASS: immediate retry feedback, 20-click coalescing, stable ID after timeout, accepted state, fast completed reply delivery, subscription race, rejected legacy retries drain before cancel, wrong/stale receipts, no knowledge writes")
    }
}
