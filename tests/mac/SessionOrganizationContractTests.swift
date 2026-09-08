import Foundation
import SwiftData

@main
struct SessionOrganizationContractTests {
    enum Disk: Error { case failed }
    static func require(_ value: Bool, _ message: String = "Contract failed", file: StaticString = #filePath, line: UInt = #line) { precondition(value, message, file: file, line: line) }
    @MainActor static func main() throws {
        let directory = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("review-today-folders-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("test.store")
        var savedID: UUID!, savedFolder: UUID!
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let context = container.mainContext; context.autosaveEnabled = false
            let draft = try AgentComposerStore.prepare(context)
            let draftID = draft.agentDraftID
            draft.agentDraftText = "RAG 草稿"; try context.save()
            require(try AgentComposerStore.prepare(context).agentDraftID == draftID)
            require(try context.fetch(FetchDescriptor<AgentSession>()).isEmpty)
            do { _ = try AgentComposerStore.sendFirst("RAG", context: context, runtime: AppRuntime(mode: .normal), save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
            require(draft.agentDraftText == "RAG 草稿")
            let (session, _) = try AgentComposerStore.sendFirst("RAG 入门", context: context, runtime: AppRuntime(mode: .normal))
            savedID = session.id; require(savedID == draftID && session.folderID == nil)
            session.setManualTopicTags(["检索"])
            let folder = try SessionOrganization.create("  学习  ", moving: session, context: context)
            savedFolder = folder.id
            require(folder.name == "学习" && session.folderID == folder.id)
            do { _ = try SessionOrganization.create("学习", context: context); preconditionFailure() } catch SessionOrganization.Failure.duplicateName {}
            do { _ = try SessionOrganization.create("  ", context: context); preconditionFailure() } catch SessionOrganization.Failure.emptyName {}
            do { try SessionOrganization.move(session, to: nil, context: context, save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
            require(session.folderID == savedFolder)
            require(SessionOrganization.matches(session, query: "检索") && SessionOrganization.matches(session, query: "rag"))
            require(LearningSessionActions.archive(session, context: context))
            require(!SessionOrganization.matches(session, query: "") && SessionOrganization.matches(session, query: "检索", archived: true))
            require(session.folderID == savedFolder)
            require(LearningSessionActions.restore(session, context: context) && session.folderID == savedFolder)
        }
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let context = container.mainContext
            let session = try context.fetch(FetchDescriptor<AgentSession>()).first!
            let folder = try context.fetch(FetchDescriptor<SessionFolder>()).first!
            require(session.id == savedID && session.folderID == savedFolder && folder.id == savedFolder)
            try SessionOrganization.rename(folder, to: "资料", context: context)
            do { try SessionOrganization.remove(folder, context: context, save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
            require(session.folderID == savedFolder)
            try SessionOrganization.remove(folder, context: context)
            require(session.folderID == nil && session.title == "RAG 入门" && session.displayTopicTags == ["检索"])
            require(try context.fetch(FetchDescriptor<AgentMessage>()).count == 1)
            require(try context.fetch(FetchDescriptor<SessionFolder>()).isEmpty)
        }
        print("PASS: landing fallback stable first-send identity, save failure, folder validation/move/rollback, archive search scope, folder retention, disk reopen and non-destructive folder deletion")
    }
}
