import Foundation
import SwiftData

@main
struct ConversationReplayTests {
    @MainActor static func main() async throws {
        let recoveryID = UUID()
        let full: [String: Any] = ["version": 1, "checkpoint": ["session_id": recoveryID.uuidString,
            "event_base_seq": 1, "events": [], "runs": ["r": ["text": "中文"]], "pending": NSNull()]]
        let base = try ConversationCheckpoint.merge(full, into: nil, sessionID: recoveryID, cursor: 1)
        let delta: [String: Any] = ["version": 2, "deltas": [["base_version": 1, "version": 2, "changes": [
            ["op": "append", "path": ["runs", "r", "text"], "value": "😀"],
            ["op": "set", "path": ["event_base_seq"], "value": 2]]]]]
        let caughtUp = try ConversationCheckpoint.merge(delta, into: base, sessionID: recoveryID, cursor: 2)
        precondition(ConversationCheckpoint.version(caughtUp) == 2)
        precondition(caughtUp.contains("中文😀"))
        let repeated = try ConversationCheckpoint.merge(delta, into: caughtUp, sessionID: recoveryID, cursor: 2)
        precondition(ConversationCheckpoint.version(repeated) == 2)
        do {
            _ = try ConversationCheckpoint.merge(delta, into: nil, sessionID: recoveryID, cursor: 2)
            preconditionFailure("delta must not silently skip its base checkpoint")
        } catch {}
        do {
            _ = try ConversationCheckpoint.merge(full, into: caughtUp, sessionID: recoveryID, cursor: 2)
            preconditionFailure("background snapshot cannot overtake or lag saved cursor")
        } catch {}
        let schema = Schema([Source.self, Knowledge.self, Question.self, CaptureTask.self, AppSettings.self,
                             FsrsState.self, ReviewSession.self, ReviewAttempt.self, AgentSession.self,
                             AgentMessage.self, LearningTask.self, TaskEventRecord.self, SourceReference.self,
                             KnowledgeReference.self, SessionSummaryRecord.self, AgentRun.self,
                             AgentRunControl.self, SessionEventRecord.self])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let session = AgentSession(), other = AgentSession()
        context.insert(session); context.insert(other)
        try context.save()
        let runID = UUID(), responseID = UUID()
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let now = formatter.string(from: .now)

        func event(_ seq: Int, text: String, chunk: Int, revision: Int = 1, state: String = "streaming", id: UUID? = nil) -> [String: Any] {
            let response: [String: Any] = ["response_id": (id ?? responseID).uuidString, "text": text, "chunk_seq": chunk, "revision": revision, "status": state]
            var event: [String: Any] = ["session_id": session.id.uuidString, "event_id": UUID().uuidString, "run_id": runID.uuidString,
                                        "seq": seq, "revision": revision, "stage": state == "complete" ? "response.completed" : "response.delta",
                                        "occurred_at": now, "payload": ["response": response]]
            if state == "complete" { event["message"] = ["message_id": (id ?? responseID).uuidString, "content": text, "created_at": now] }
            return event
        }
        func page(_ events: [[String: Any]], revision: Int = 1) -> [String: Any] {
            ["session_id": session.id.uuidString, "events": events, "paused": false, "mode": "auto",
             "runs": [["session_id": session.id.uuidString, "run_id": runID.uuidString, "revision": revision, "status": "running", "updated_at": now]]]
        }
        let start = ContinuousClock.now
        try ConversationProcessor.persist(page([event(1, text: "中", chunk: 1)]), session: session, context: context)
        try ConversationProcessor.persist(page([event(3, text: "中文😀 **尚未闭合", chunk: 3), event(2, text: "中文", chunk: 2)]), session: session, context: context)
        let rows = try context.fetch(FetchDescriptor<AgentMessage>())
        precondition(rows.count == 1 && rows[0].content == "中文😀 **尚未闭合")
        precondition(rows[0].responseChunkSeq == 3 && session.lastSessionEventSeq == 3)
        // Duplicate delivery is harmless even when the event ID differs.
        try ConversationProcessor.persist(page([event(3, text: "不应覆盖", chunk: 3)]), session: session, context: context)
        precondition(rows[0].content == "中文😀 **尚未闭合")
        do {
            try ConversationProcessor.persist(page([event(5, text: "缺失 4", chunk: 5)]), session: session, context: context)
            preconditionFailure("gap must fail before advancing cursor")
        } catch { context.rollback() }
        precondition(session.lastSessionEventSeq == 3)
        try ConversationProcessor.persist(page([event(4, text: "中文😀 **已闭合**", chunk: 4, state: "complete")]), session: session, context: context)
        let finalized = try context.fetch(FetchDescriptor<AgentMessage>())
        precondition(finalized.count == 1)
        precondition(rows[0].responseState == "complete")

        let secondResponse = UUID()
        try ConversationProcessor.persist(page([event(5, text: "新回复的首段", chunk: 1, id: secondResponse)]), session: session, context: context)
        let run = try context.fetch(FetchDescriptor<AgentRun>()).first!
        let stopStart = ContinuousClock.now
        ConversationProcessor.queueControl(run, action: "stop", context: context)
        let stopTime = stopStart.duration(to: .now)
        precondition(stopTime < .milliseconds(100))
        try ConversationProcessor.persist(page([event(6, text: "停止后的迟到内容", chunk: 2, id: secondResponse)]), session: session, context: context)
        let partial = try context.fetch(FetchDescriptor<AgentMessage>()).first(where: { $0.id == secondResponse })!
        precondition(partial.content == "新回复的首段" && partial.responseState == "interrupted")
        precondition(session.lastSessionEventSeq == 6 && run.status == "stopping")
        let controls = try context.fetch(FetchDescriptor<AgentRunControl>())
        controls[0].sent = true
        try context.save()
        try ConversationProcessor.persist(page([event(7, text: "旧版本不覆盖", chunk: 3, id: secondResponse)], revision: 2), session: session, context: context)
        precondition(partial.content == "新回复的首段")
        let resumed = UUID()
        try ConversationProcessor.persist(page([event(8, text: "重试中的新回答", chunk: 1, revision: 2, id: resumed)], revision: 2), session: session, context: context)
        let resumedMessages = try context.fetch(FetchDescriptor<AgentMessage>())
        precondition(resumedMessages.first(where: { $0.id == resumed })?.content == "重试中的新回答")
        var tagPage = page([], revision: 2)
        tagPage["runs"] = [["session_id": session.id.uuidString, "run_id": runID.uuidString, "revision": 2,
                            "status": "completed", "updated_at": now, "activity_kind": "knowledge_answer", "completed_at": now]]
        tagPage["events"] = [["session_id": session.id.uuidString, "event_id": UUID().uuidString,
                              "run_id": runID.uuidString, "seq": 9, "revision": 2, "stage": "intent_decided",
                              "occurred_at": now, "payload": ["intent": ["session_tags": ["RAG", "面试"]]]]]
        try ConversationProcessor.persist(tagPage, session: session, context: context)
        precondition(session.displayTopicTags == ["RAG", "面试"])
        precondition(run.activityKind == "knowledge_answer" && run.completedAt != nil)
        session.setManualTopicTags(["自定义"])
        precondition(session.displayTopicTags == ["自定义"])

        // Once archived, audit sequence may advance but an in-flight response,
        // automatic tag suggestion, pending action, or mode may not revive UI state.
        session.status = "archived"
        session.modePreset = "problem_solving"
        session.pendingOperationJSON = nil
        try context.save()
        let archivedResponse = UUID()
        var archivedEvent = event(10, text: "归档后的迟到回答", chunk: 1, revision: 2, id: archivedResponse)
        archivedEvent["payload"] = [
            "response": ["response_id": archivedResponse.uuidString, "text": "归档后的迟到回答", "chunk_seq": 1,
                         "revision": 2, "status": "streaming"],
            "intent": ["session_tags": ["不应覆盖"]]
        ]
        var archivedPage = page([archivedEvent], revision: 2)
        archivedPage["mode"] = "auto"
        archivedPage["pending"] = ["kind": "confirm_memory"]
        try ConversationProcessor.persist(archivedPage, session: session, context: context)
        let afterArchiveMessages = try context.fetch(FetchDescriptor<AgentMessage>())
        precondition(afterArchiveMessages.allSatisfy { $0.id != archivedResponse })
        precondition(session.lastSessionEventSeq == 10)
        precondition(session.displayTopicTags == ["自定义"] && session.modePreset == "problem_solving")
        precondition(session.pendingOperationJSON == nil)
        session.status = "active"
        session.lifecycleRevision = 2
        session.runPaused = true
        var lateRestorePage = page([])
        lateRestorePage["pending"] = ["kind": "save", "target_id": "old", "version": 1]
        lateRestorePage["mode"] = "auto"
        try ConversationProcessor.persist(lateRestorePage, session: session, context: context)
        precondition(session.pendingOperationJSON == nil && session.modePreset == "problem_solving" && session.runPaused)
        session.status = "archived"
        try context.save()
        do {
            try ConversationProcessor.persist(page([]), session: other, context: context)
            preconditionFailure("cross-Session events must be rejected")
        } catch { context.rollback() }
        let reopened = ModelContext(container)
        let recoveredSession = try reopened.fetch(FetchDescriptor<AgentSession>()).first(where: { $0.id == session.id })!
        let recoveredPartial = try reopened.fetch(FetchDescriptor<AgentMessage>()).first(where: { $0.id == secondResponse })!
        precondition(recoveredSession.lastSessionEventSeq == 10 && recoveredPartial.responseState == "interrupted")
        let knowledge = try reopened.fetch(FetchDescriptor<Knowledge>())
        let reviews = try reopened.fetch(FetchDescriptor<ReviewAttempt>())
        precondition(knowledge.isEmpty && reviews.isEmpty)
        print("PASS: ordered/repeated/gapped replay, stable final ID, stop/archive and revision fencing, Session tags/activity, atomic cursor recovery, Session isolation, no knowledge/review writes")
        print("Controlled stop save: \(stopTime); full replay suite: \(start.duration(to: .now))")
        if let endpoint = CommandLine.arguments.dropFirst().first.flatMap(URL.init(string:)) {
            var received: [Date] = []
            var delays: [Double] = []
            try await AgentAPI.consumeSessionEvents(UUID(), after: 0, endpoint: endpoint) { value in
                precondition(value["sample"] as? String == "中文😀 **未闭合")
                received.append(.now)
                delays.append(Date.now.timeIntervalSince1970 - (value["sent_at"] as! Double))
            }
            FileHandle.standardError.write(Data("SSE frames: \(received.count), span: \(received.last?.timeIntervalSince(received.first ?? .now) ?? 0), delays: \(delays)\n".utf8))
            precondition(received.count == 3 && received.last!.timeIntervalSince(received.first!) > 0.3,
                         "real events must arrive before the entire response ends")
            precondition(delays.max()! < 0.2, "received events must not queue behind display animation")
            print("PASS: real SSE Unicode transport, incremental delivery, max controlled receive delay \(Int(delays.max()! * 1000)) ms")
        }
    }
}
