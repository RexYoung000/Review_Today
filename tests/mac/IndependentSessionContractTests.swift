import Foundation
import SwiftData

@main
struct IndependentSessionContractTests {
    static func require(_ value: Bool) { precondition(value) }
    enum Disk: Error { case failed }
    @MainActor static func main() throws {
        let directory = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("review-today-independent-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("test.store")
        var ids: [UUID] = []
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let c = container.mainContext; c.autosaveEnabled = false
            let old = try AgentComposerStore.prepare(c)
            old.agentDraftText = "旧草稿完整保留"; old.agentDraftThinking = "deep"; try c.save()
            do { _ = try AgentComposerStore.preserveLandingDraft(context: c, save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
            precondition(old.agentDraftText == "旧草稿完整保留")
            let migrated = try AgentComposerStore.preserveLandingDraft(context: c)!
            precondition(migrated.composerDraft == "旧草稿完整保留" && migrated.thinkingStrength == "deep")
            require(try AgentComposerStore.preserveLandingDraft(context: c) == nil)
            let first = try AgentComposerStore.createSession(context: c)
            let second = try AgentComposerStore.createSession(context: c)
            ids = [migrated.id, first.id, second.id]
            precondition(Set(ids).count == 3)
            first.composerDraft = "A 未发送"; second.composerDraft = "B 未发送"; try c.save()
            require(try c.fetch(FetchDescriptor<AgentMessage>()).isEmpty)
            require(try c.fetch(FetchDescriptor<AgentRun>()).isEmpty)
            do { _ = try AgentComposerStore.createSession(context: c, save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
            require(try c.fetch(FetchDescriptor<AgentSession>()).count == 3)
        }
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let c = container.mainContext; c.autosaveEnabled = false
            let rows = try c.fetch(FetchDescriptor<AgentSession>())
            let first = rows.first { $0.id == ids[1] }!, second = rows.first { $0.id == ids[2] }!
            precondition(first.composerDraft == "A 未发送" && second.composerDraft == "B 未发送")
            do { _ = try AgentComposerStore.sendInitial("A 第一条消息", in: first, context: c, runtime: AppRuntime(mode: .normal), save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
            precondition(first.composerDraft == "A 未发送" && first.title == "新会话")
            require(try c.fetch(FetchDescriptor<AgentMessage>()).isEmpty)
            let message = try AgentComposerStore.sendInitial("A 第一条消息", in: first, context: c, runtime: AppRuntime(mode: .normal))
            precondition(message.sessionID == ids[1] && first.title == "A 第一条消息" && first.composerDraft.isEmpty)
            precondition(second.composerDraft == "B 未发送")
            require(try c.fetch(FetchDescriptor<AgentSession>()).count == 3)
            let impact = try SessionDeletion.impact([second.id], context: c)
            precondition(impact.cardIDs.isEmpty)
            require(try SessionDeletion.perform(impact, includeCards: false, context: c) == nil)
            require(try c.fetch(FetchDescriptor<AgentSession>()).count == 2)
            require(try AgentComposerStore.settings(c).agentDraftText.isEmpty)
            require(try SessionDeletion.contains(ids[2], context: c))
            let marker = try SessionDeletion.records(c).first { $0["session_id"] as? String == ids[2].uuidString.lowercased() }!
            precondition(marker["lifecycle_revision"] as? Int == 2, "active deletion reserves archive revision 1 then deletion revision 2")
            let populated = try SessionDeletion.impact([first.id], context: c)
            require(try SessionDeletion.perform(populated, includeCards: false, context: c) == nil)
            require(try c.fetch(FetchDescriptor<AgentMessage>()).isEmpty)
            require(try c.fetch(FetchDescriptor<AgentSession>()).first?.composerDraft == "旧草稿完整保留")
        }
        print("PASS: independent creation, legacy draft preservation/rollback, per-session disk persistence, no message/run on creation, creation/first-send failure, first-send identity, active empty/populated deletion and no draft resurrection")
    }
}
