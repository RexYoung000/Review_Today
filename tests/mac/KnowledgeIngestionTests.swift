import Foundation
import SwiftData

@main struct KnowledgeIngestionTests {
    static func require(_ value: Bool, _ message: String = "") { precondition(value, message) }
    enum Disk: Error { case failed }
    @MainActor static func main() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ingestion-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("test.store")
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
        let c = container.mainContext; c.autosaveEnabled = false
        let session = AgentSession(title: "入库验收")
        c.insert(session)
        let message = AgentMessage(sessionID: session.id, role: "user", content: "保存", deliveryStatus: "accepted")
        let task = LearningTask(sessionID: session.id, inputMessageID: message.id)
        task.mode = "memory_organization"; task.status = "committing"
        c.insert(message); c.insert(task); try c.save()
        let state = KnowledgeIngestion()
        state.register(input: message.id, session: session.id, explicitSave: true, eligible: true, compact: false)
        var receipts = 0
        let observer = NotificationCenter.default.addObserver(forName: .knowledgeIngestionSaved, object: nil, queue: .main) { note in
            MainActor.assumeIsolated {
                guard let context = note.object as? ModelContext, context === c,
                      let receipt = note.userInfo?["receipt"] as? KnowledgeIngestionReceipt else { return }
                // A separate disk reader must see all cards at the event boundary.
                let reader = ModelContext(container)
                let savedIDs = Set((try! reader.fetch(FetchDescriptor<Knowledge>())).map(\.id))
                precondition(Set(receipt.knowledgeIDs).isSubset(of: savedIDs))
                precondition(task.memoryCommitted)
                receipts += 1
                state.receive(receipt, eligible: true, compact: false)
            }
        }
        defer { NotificationCenter.default.removeObserver(observer) }
        let ids = [UUID(), UUID()]
        let payload = try KnowledgeIngestionFixture.payload(ids)
        do {
            _ = try HarnessProcessor.persistMemory(payload, sourceText: "测试原文", task: task, context: c, save: { throw Disk.failed })
            preconditionFailure()
        } catch Disk.failed {}
        precondition(receipts == 0 && !task.memoryCommitted && task.sourceID == nil)
        require(try c.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        require(try c.fetch(FetchDescriptor<Source>()).isEmpty)
        require(try c.fetch(FetchDescriptor<Question>()).isEmpty)
        require(try c.fetch(FetchDescriptor<FsrsState>()).isEmpty)
        require(try c.fetch(FetchDescriptor<KnowledgeReference>()).isEmpty)
        precondition(state.outcome == "processing")
        _ = try HarnessProcessor.persistMemory(payload, sourceText: "测试原文", task: task, context: c)
        precondition(receipts == 1 && state.saved && state.knowledgeIDs.count == 2 && state.presented)
        let cards = try c.fetch(FetchDescriptor<Knowledge>())
        precondition(cards.allSatisfy { !$0.participatesInReview }, "saving alone does not enroll or certify learning")
        precondition(cards.allSatisfy { $0.originTaskID == task.id && $0.originSessionID == session.id })
        require(try c.fetch(FetchDescriptor<KnowledgeReference>()).count == 2)
        var changed = payload; changed.knowledge[0].title = "不应泄漏的失败修改"
        let priorTitles = cards.map(\.title)
        do {
            _ = try HarnessProcessor.persistMemory(changed, sourceText: "失败修改的原文", task: task, context: c, save: { throw Disk.failed })
            preconditionFailure()
        } catch Disk.failed {}
        precondition(cards.map(\.title) == priorTitles && task.memoryCommitted)
        try c.save() // Matches the processor's outer failure-status save.
        require(try ModelContext(container).fetch(FetchDescriptor<Source>()).first?.rawText == "测试原文")
        require(try ModelContext(container).fetch(FetchDescriptor<Knowledge>()).allSatisfy { !$0.title.contains("失败修改") })
        let signal = state.signalToken
        _ = try HarnessProcessor.persistMemory(payload, sourceText: "测试原文", task: task, context: c)
        precondition(state.signalToken == signal)
        require(try c.fetch(FetchDescriptor<Knowledge>()).count == 2)
        task.errorCode = "ACK_RETRY"; task.status = "retryable_failed"; try c.save()
        state.refresh(context: c, eligible: true, compact: false)
        precondition(state.saved, "ack failure never reverses persisted success")
        precondition(!state.finish(reduced: true, foreground: true))
        state.replay(); precondition(state.finish(reduced: false, foreground: true))
        precondition(!state.finish(reduced: false, foreground: true))
        require(try c.fetch(FetchDescriptor<Knowledge>()).count == 2, "replay is read-only")
        let receipt = KnowledgeIngestionReceipt(taskID: UUID(), inputID: UUID(), sessionID: session.id, knowledgeIDs: ids)
        let dismissed = KnowledgeIngestion()
        dismissed.register(input: receipt.inputID, session: session.id, explicitSave: true, eligible: true, compact: false)
        dismissed.dismiss(); dismissed.receive(receipt, eligible: true, compact: false)
        precondition(dismissed.saved && !dismissed.presented)
        precondition(!dismissed.finish(reduced: false, foreground: true))
        let history = KnowledgeIngestion()
        history.receive(receipt, eligible: true, compact: false)
        precondition(!history.presented && !history.saved)
        history.register(input: receipt.inputID, session: session.id, explicitSave: false, eligible: true, compact: false)
        history.receive(receipt, eligible: false, compact: false)
        history.receive(receipt, eligible: true, compact: false)
        precondition(!history.presented, "background/modal success is consumed, not queued")
        let navigated = KnowledgeIngestion()
        navigated.register(input: receipt.inputID, session: session.id, explicitSave: true, eligible: true, compact: false)
        navigated.leaveContext(); navigated.receive(receipt, eligible: true, compact: false)
        precondition(!navigated.presented && !navigated.saved)
        let failed = KnowledgeIngestion()
        failed.register(input: receipt.inputID, session: session.id, explicitSave: true, eligible: true, compact: false)
        failed.stop(input: receipt.inputID, cancelled: false)
        precondition(failed.outcome == "failed" && !failed.saved)
        failed.receive(receipt, eligible: true, compact: false)
        precondition(failed.saved, "a later actual automatic retry updates the open result")
        let natural = KnowledgeIngestion()
        task.errorCode = nil; task.memoryCommitted = false; task.status = "accepted"; try c.save()
        natural.register(input: message.id, session: session.id, explicitSave: false, eligible: true, compact: false)
        precondition(!natural.presented)
        natural.refresh(context: c, eligible: true, compact: false)
        precondition(!natural.presented, "ordinary organization stages never open an ingestion presentation")
        task.status = "needs_attention"; natural.refresh(context: c, eligible: true, compact: false)
        precondition(!natural.presented)
        let reopened = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
        require(try reopened.mainContext.fetch(FetchDescriptor<Knowledge>()).count == 2)
        require(try reopened.mainContext.fetch(FetchDescriptor<Source>()).first?.rawText == "测试原文")
        let enrolledContainer = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let ec = enrolledContainer.mainContext
        let es = AgentSession(title: "已学过后加入复习")
        let em = AgentMessage(sessionID: es.id, role: "user", content: "保存，并加入复习")
        em.reviewRequested = true
        let et = LearningTask(sessionID: es.id, inputMessageID: em.id)
        ec.insert(es); ec.insert(em); ec.insert(et); try ec.save()
        let start = Date.now
        _ = try HarnessProcessor.persistMemory(KnowledgeIngestionFixture.payload([UUID()]), sourceText: "合成资料", task: et, context: ec)
        let enrolled = try ec.fetch(FetchDescriptor<Knowledge>()).first!
        precondition(enrolled.participatesInReview && enrolled.studiedAt != nil && enrolled.dueAt.timeIntervalSince(start) >= 7200 && enrolled.dueAt.timeIntervalSince(start) < 7210)
        print("PASS: atomic disk save/rollback and post-save receipt; references/ownership; duplicate and ACK retry; immediate results; read-only replay; close/history/background/modal/navigation; failure/needs-attention; natural-message gating; first-full preference; reopened store")
    }
}
