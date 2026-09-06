import Foundation
import SwiftData

@main
struct SessionDeletionContractTests {
    static func require(_ value: Bool, _ message: String = "") { precondition(value, message) }
    @MainActor static func main() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let c = container.mainContext
        let archived = AgentSession(title: "删除测试", status: "archived"), shared = AgentSession(title: "保留的会话")
        archived.composerDraft = "私密草稿"
        c.insert(archived); c.insert(shared)
        let settings = AppSettings(); c.insert(settings)
        func card(_ title: String, origin: UUID?) -> Knowledge {
            let value = Knowledge(learningGoal: title, knowledgeType: "concept", theme: "RAG", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: title, evidenceLocator: "1")
            value.originSessionID = origin; c.insert(value)
            c.insert(KnowledgeReference(sessionID: archived.id, knowledgeID: value.id))
            return value
        }
        let own = card("独有", origin: archived.id), used = card("共享", origin: archived.id), old = card("归属不明", origin: nil)
        c.insert(KnowledgeReference(sessionID: shared.id, knowledgeID: used.id))
        let preview = ReviewSession(mode: "preview", snapshotJSON: own.id.uuidString)
        let mixed = ReviewSession(mode: "formal", snapshotJSON: [own.id, old.id].map(\.uuidString).joined(separator: ","))
        c.insert(preview); c.insert(mixed)
        let review = ReviewAttempt(sessionId: preview.id, knowledgeId: own.id, knowledgeVersion: 1, questionId: UUID(), mode: "preview")
        c.insert(review)
        let run = AgentRun(id: UUID(), sessionID: archived.id); c.insert(run)
        try c.save()
        let impact = try SessionDeletion.impact([archived.id], context: c)
        require(impact.cardIDs == [own.id] && impact.retainedCardIDs == [used.id, old.id] && impact.attemptIDs == [review.attemptId])
        require(try c.fetch(FetchDescriptor<AgentSession>()).count == 2, "opening/cancelling preview cannot mutate data")
        do {
            _ = try SessionDeletion.perform(impact, includeCards: true, context: c, save: { throw CocoaError(.fileWriteUnknown) })
            preconditionFailure("save error must surface")
        } catch { }
        let fresh = ModelContext(container)
        require(try fresh.fetch(FetchDescriptor<AgentSession>()).count == 2)
        require(try fresh.fetch(FetchDescriptor<Knowledge>()).count == 3)
        // Use refetched objects after SwiftData rollback.
        let retried = try SessionDeletion.impact(impact.sessionIDs, context: fresh)
        let changedCard = try fresh.fetch(FetchDescriptor<Knowledge>()).first { $0.id == own.id }!
        fresh.insert(KnowledgeReference(sessionID: shared.id, knowledgeID: changedCard.id))
        try fresh.save()
        let changed = try SessionDeletion.perform(retried, includeCards: true, context: fresh)
        require(changed != nil && changed!.cardIDs.isEmpty, "expanded/changed scope requires review again")
        let all = try fresh.fetch(FetchDescriptor<AgentSession>())
        for session in all { session.status = "archived" }
        try fresh.save()
        let batch = try SessionDeletion.impact(Set(all.map(\.id)), context: fresh)
        require(batch.cardIDs == [own.id, used.id])
        require(try SessionDeletion.perform(batch, includeCards: true, context: fresh) == nil)
        require(try fresh.fetch(FetchDescriptor<AgentSession>()).isEmpty)
        require(try fresh.fetch(FetchDescriptor<Knowledge>()).map(\.id) == [old.id])
        require(try fresh.fetch(FetchDescriptor<ReviewAttempt>()).isEmpty)
        let remainingReviews = try fresh.fetch(FetchDescriptor<ReviewSession>())
        require(remainingReviews.count == 1 && remainingReviews[0].id == mixed.id && remainingReviews[0].snapshotJSON == old.id.uuidString,
                "remove orphan review sessions and only deleted cards from shared review snapshots")
        require(try SessionDeletion.contains(archived.id, context: fresh))
        let records = try SessionDeletion.records(fresh)
        require(records.count == 2 && !ConversationProcessor.json(records).contains("私密"))
        try LearningMemory.backfill(context: fresh)
        require(try fresh.fetch(FetchDescriptor<AgentSession>()).isEmpty)
        print("PASS: deletion preview, rollback, scope revalidation, shared/unknown protection, batch purge, preview removal, durable offline tombstones and no index resurrection")
    }
}
