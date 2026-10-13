import Foundation
import SwiftData

@main
struct ConversationSteeringTests {
    static func require(_ value: Bool) { precondition(value) }
    @MainActor final class Fixture {
        let container: ModelContainer
        let context: ModelContext
        let session = AgentSession()
        let run: AgentRun
        let answer: AgentMessage
        let supplement: AgentMessage
        let next = UUID()

        init() throws {
            container = try ModelContainer(for: M1DebugFixture.schema,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true))
            context = container.mainContext; context.autosaveEnabled = false
            run = AgentRun(id: UUID(), sessionID: session.id)
            run.status = "adjusting"; run.userSummary = "已收到补充，正在调整"
            answer = AgentMessage(sessionID: session.id, role: "assistant", content: "旧首段")
            answer.runID = run.id; answer.responseState = "interrupted"
            answer.responseRevision = 1; answer.responseChunkSeq = 1
            supplement = AgentMessage(sessionID: session.id, role: "user", content: "补充说明")
            context.insert(session); context.insert(run); context.insert(answer); context.insert(supplement)
            try context.save()
        }

        func admit(_ message: AgentMessage? = nil) throws {
            try ConversationProcessor.recordAcceptance(["run_id": next.uuidString, "status": "accepted", "revision": 1],
                                                       message: message ?? supplement, context: context)
        }

        func page(checkpointOnly: Bool = false, messageID: UUID? = nil, lifecycle: Int = 0) -> [String: Any] {
            let now = ISO8601DateFormatter().string(from: .now)
            let header: [String: Any] = ["session_id": session.id.uuidString, "run_id": run.id.uuidString,
                "revision": 1, "status": "completed", "stage": "completed", "updated_at": now,
                "user_summary": "已完整回应", "lifecycle_revision": 0]
            let body: [String: Any] = ["message_id": (messageID ?? answer.id).uuidString,
                "run_id": run.id.uuidString, "role": "coach", "content": "原回答已完整结束", "created_at": now]
            let event: [String: Any] = ["session_id": session.id.uuidString, "run_id": run.id.uuidString,
                "event_id": UUID().uuidString, "seq": 1, "revision": 1, "lifecycle_revision": 0,
                "stage": "response.completed", "occurred_at": now, "message": body,
                "payload": ["response": ["response_id": answer.id.uuidString, "revision": 1,
                                          "chunk_seq": 2, "status": "complete", "text": "原回答已完整结束"]]]
            let checkpoint: [String: Any] = ["session_id": session.id.uuidString, "lifecycle_revision": lifecycle,
                "events": [], "event_base_seq": 1, "messages": [body], "runs": [run.id.uuidString.lowercased(): header]]
            return ["session_id": session.id.uuidString, "runs": checkpointOnly ? [] : [header],
                    "events": checkpointOnly ? [] : [event], "paused": false,
                    "recovery": ["version": 1, "checkpoint": checkpoint]]
        }
        func persist(_ page: [String: Any]) throws {
            try ConversationProcessor.persist(page, session: session, context: context)
        }
        func empty() throws {
            try persist(["session_id": session.id.uuidString, "events": [], "runs": [], "paused": false])
        }
    }

    @MainActor static func main() throws {
        var passed = 0
        do {
            let f = try Fixture(); try f.admit(); try f.persist(f.page()); try f.persist(f.page())
            precondition(f.run.status == "completed" && f.answer.responseState == "complete")
            precondition(f.answer.content == "原回答已完整结束" && f.session.lastSessionEventSeq == 1)
            require(try f.context.fetch(FetchDescriptor<AgentMessage>()).count == 2)
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page())
            precondition(f.answer.content == "旧首段" && f.run.status == "adjusting")
            try f.admit(); try f.empty()
            precondition(f.answer.content == "原回答已完整结束" && f.answer.responseState == "complete")
            precondition(f.run.status == "completed" && f.session.lastSessionEventSeq == 1)
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page()); try f.empty()
            precondition(f.run.status == "adjusting" && f.answer.content == "旧首段")
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page())
            let later = AgentMessage(sessionID: f.session.id, role: "user", content: "再次补充")
            f.context.insert(later); try f.context.save(); try f.admit(); try f.empty()
            precondition(f.run.status == "adjusting" && f.answer.content == "旧首段")
            try f.admit(later); try f.empty()
            precondition(f.run.status == "completed" && f.answer.content == "原回答已完整结束")
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page()); try f.admit()
            let stop = AgentRunControl(runID: f.run.id, sessionID: f.session.id, action: "stop")
            f.context.insert(stop); try f.context.save(); try f.empty()
            precondition(f.answer.content == "旧首段" && f.answer.responseState == "interrupted")
            precondition(f.run.status == "stopping")
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page()); try f.admit()
            f.session.status = "archived"; f.session.lifecycleRevision = 1; try f.context.save(); try f.empty()
            precondition(f.answer.content == "旧首段" && f.session.status == "archived")
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page()); try f.admit()
            f.run.revision = 2; try f.context.save(); try f.empty()
            precondition(f.answer.content == "旧首段" && f.answer.responseState == "interrupted")
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page(messageID: UUID())); try f.admit(); try f.empty()
            precondition(f.answer.content == "旧首段" && f.answer.responseState == "interrupted")
            require(try f.context.fetch(FetchDescriptor<AgentMessage>()).count == 2)
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page()); try f.admit()
            f.run.memoryReferencesJSON = ConversationProcessor.json([["knowledge_id": UUID().uuidString, "content_version": 1]])
            try f.context.save(); try f.empty()
            precondition(f.answer.content == "旧首段" && f.answer.responseState == "interrupted")
            passed += 1
        }
        do {
            let f = try Fixture(); try f.persist(f.page(lifecycle: 1)); try f.admit()
            f.session.lifecycleRevision = 1; try f.context.save(); try f.empty()
            precondition(f.answer.content == "旧首段" && f.answer.responseState == "interrupted")
            passed += 1
        }
        print("PASS: \(passed) steering scenarios; receipt ordering, repeat, pending burst, stop/archive/version/identity/reference fences")
    }
}
