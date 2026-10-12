import Foundation
import SwiftData

@MainActor
private final class SaveRecoveryFixture {
    let container: ModelContainer
    let context: ModelContext
    let session = AgentSession(title: "保存恢复隔离验证")
    let task: LearningTask
    let runID = UUID()
    let ids = [UUID(), UUID()]
    var remoteStatus = "committing"
    var stopped = false
    var failACK = false
    var stopDuringClaim = false
    var deliveredStopDuringClaim = false
    var commitRevision = 1
    var claimCount = 0
    var ackCount = 0
    var continuationFlags: [Bool] = []
    var releaseCount = 0
    var controls: [AgentRunControl] = []
    var paths: [String] = []

    init(_ directory: URL) throws {
        container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: directory.appendingPathComponent("store.sqlite")))
        context = container.mainContext
        context.autosaveEnabled = false
        let input = AgentMessage(sessionID: session.id, role: "user", content: "保存", deliveryStatus: "accepted")
        task = LearningTask(sessionID: session.id, inputMessageID: input.id, status: "committing")
        task.conversationManaged = true
        context.insert(session); context.insert(input); context.insert(task)
        let run = AgentRun(id: runID, sessionID: session.id)
        run.revision = 1; run.status = "completed"
        context.insert(run)
        try context.save()
    }

    func view() -> [String: Any] {
        ["task_id": task.id.uuidString.lowercased(), "session_id": session.id.uuidString.lowercased(),
         "client_message_id": task.inputMessageID.uuidString.lowercased(), "mode": "memory_organization",
         "status": remoteStatus, "stage": remoteStatus, "user_summary": remoteStatus,
         "retry_count": 0, "result_summary": "", "last_event_seq": 0, "last_acked_seq": 0,
         "memory_package": KnowledgeIngestionFixture.object(ids), "memory_source_text": "隔离测试原文",
         "commit_run_id": runID.uuidString.lowercased(), "commit_revision": commitRevision,
         "lifecycle_revision": 0]
    }

    func request(_ path: String, _ body: [String: Any]?) async throws -> [String: Any] {
        paths.append(path)
        if path.contains("/events?") {
            return ["task_id": task.id.uuidString.lowercased(), "events": [], "last_seq": 0]
        }
        if path.hasSuffix("/commit-claim") {
            claimCount += 1
            if stopped { throw HarnessAPIError.server(code: "RT.TASK.COMMIT_REVOKED", message: "已停止") }
            if stopDuringClaim {
                let control = AgentRunControl(runID: runID, sessionID: session.id, action: "stop")
                controls.append(control); context.insert(control); try context.save()
                stopped = true
                if deliveredStopDuringClaim {
                    control.sent = true
                    let run = try context.fetch(FetchDescriptor<AgentRun>()).first!
                    run.revision += 1; run.status = "completed"
                    try context.save()
                }
            }
            return view()
        }
        if path.hasSuffix("/commit-release") {
            releaseCount += 1
            precondition(stopped && !task.memoryCommitted)
            precondition(body?["run_id"] as? String == runID.uuidString.lowercased())
            precondition(body?["commit_revision"] as? Int == 1)
            remoteStatus = "awaiting_user"
            return view()
        }
        if path.hasSuffix("/ack") {
            ackCount += 1
            continuationFlags.append(body?["allow_continuation"] as? Bool ?? true)
            let reader = ModelContext(container)
            let saved = try reader.fetch(FetchDescriptor<Knowledge>())
            precondition(Set(body?["knowledge_ids"] as? [String] ?? []) == Set(ids.map { $0.uuidString.lowercased() }))
            precondition(Set(ids).isSubset(of: Set(saved.map(\.id))))
            let committedTasks = try reader.fetch(FetchDescriptor<LearningTask>())
            precondition(committedTasks.first?.memoryCommitted == true)
            if failACK { throw URLError(.timedOut) }
            remoteStatus = "completed"
            return view()
        }
        return view()
    }

    func synchronize() async {
        await HarnessProcessor.synchronize(task, context: context) { path, body in
            try await self.request(path, body)
        }
    }
}

@main
struct SaveRecoveryContractTests {
    static func require(_ value: Bool, _ message: String = "") { precondition(value, message) }
    @MainActor static func main() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("review-today-save-recovery-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        func fixture(_ name: String) throws -> SaveRecoveryFixture {
            let path = directory.appendingPathComponent(name)
            try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
            return try SaveRecoveryFixture(path)
        }

        let saved = try fixture("saved")
        var receipts = 0
        let observer = NotificationCenter.default.addObserver(forName: .knowledgeIngestionSaved, object: nil, queue: .main) { note in
            MainActor.assumeIsolated {
                if let c = note.object as? ModelContext, c === saved.context { receipts += 1 }
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }
        saved.failACK = true
        await saved.synchronize()
        precondition(saved.task.memoryCommitted && saved.task.errorCode == "RT.HARNESS.SERVICE_UNAVAILABLE")
        precondition(saved.claimCount == 1 && saved.ackCount == 1 && receipts == 1)
        let reader = ModelContext(saved.container)
        let cards = try reader.fetch(FetchDescriptor<Knowledge>())
        precondition(cards.count == 2, "real disk commit precedes the failed receipt")
        let edited = try saved.context.fetch(FetchDescriptor<Knowledge>()).first!
        edited.title = "保存后用户编辑的标题"
        let editedID = edited.id
        let stop = AgentRunControl(runID: saved.runID, sessionID: saved.session.id, action: "stop")
        saved.context.insert(stop); try saved.context.save()
        saved.failACK = false; saved.stopped = true
        await saved.synchronize()
        await saved.synchronize()
        precondition(saved.task.status == "completed" && saved.claimCount == 1 && saved.releaseCount == 0)
        precondition(saved.ackCount == 2 && receipts == 1 && !stop.sent)
        precondition(saved.continuationFlags == [true, false], "receipt recovery cannot resume deferred teaching")
        require(try saved.context.fetch(FetchDescriptor<Knowledge>()).count == 2)
        require(try saved.context.fetch(FetchDescriptor<Knowledge>()).first { $0.id == editedID }?.title == "保存后用户编辑的标题",
                     "receipt recovery cannot rewrite or reannounce the card")

        let unsaved = try fixture("unsaved")
        unsaved.stopDuringClaim = true
        await unsaved.synchronize()
        precondition(!unsaved.task.memoryCommitted && unsaved.ackCount == 0)
        require(try unsaved.context.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        unsaved.controls.forEach { $0.sent = true }; try unsaved.context.save()
        await unsaved.synchronize()
        precondition(unsaved.remoteStatus == "awaiting_user" && unsaved.releaseCount == 1 && unsaved.ackCount == 0)
        require(try unsaved.context.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        // An explicit same-version retry obtains a fresh current claim.
        unsaved.stopped = false; unsaved.stopDuringClaim = false; unsaved.remoteStatus = "committing"
        await unsaved.synchronize()
        precondition(unsaved.task.memoryCommitted && unsaved.task.status == "completed" && unsaved.ackCount == 1)
        require(try unsaved.context.fetch(FetchDescriptor<Knowledge>()).count == 2)

        let delivered = try fixture("delivered-stop")
        delivered.stopDuringClaim = true; delivered.deliveredStopDuringClaim = true
        await delivered.synchronize()
        require(try delivered.context.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        precondition(delivered.ackCount == 0 && !delivered.task.memoryCommitted,
                     "a stop delivered while awaiting claim still blocks the obsolete result")
        await delivered.synchronize()
        precondition(delivered.releaseCount == 1 && delivered.remoteStatus == "awaiting_user")

        let invalid = try fixture("invalid")
        _ = try HarnessProcessor.persistMemory(KnowledgeIngestionFixture.payload(invalid.ids), sourceText: "合成内容", task: invalid.task, context: invalid.context)
        let ref = try invalid.context.fetch(FetchDescriptor<KnowledgeReference>()).first!
        invalid.context.delete(ref); try invalid.context.save()
        await invalid.synchronize()
        precondition(invalid.claimCount == 0 && invalid.ackCount == 0 && invalid.releaseCount == 0,
                     "an incomplete persisted receipt cannot authorize writing, ACK or release")

        let pending = try fixture("pending")
        pending.task.memoryCommitted = true
        let view = try JSONDecoder().decode(AgentAPI.LearningTaskView.self, from: JSONSerialization.data(withJSONObject: pending.view()))
        do {
            _ = try HarnessProcessor.committedKnowledgeIDs(view, task: pending.task, context: pending.context)
            preconditionFailure("unsaved in-memory flags cannot prove a committed receipt")
        } catch {}
        print("PASS: real SwiftData save/failed ACK/stop/recovery; no duplicate or rewrite; post-claim stop/zero writes/release/explicit retry; incomplete and unsaved receipt guards")
    }
}
