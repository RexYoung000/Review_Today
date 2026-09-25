import Foundation
import SwiftData

@main struct LocalDataResetContractTests {
    static func require(_ value: Bool, _ message: String = "") { precondition(value, message) }
    @MainActor static func main() async throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        var c = container.mainContext
        let settings = AppSettings(dailyReminderMinutes: 123, reviewLanguageOverride: "zh", developerMode: true)
        settings.agentDraftText = "draft"; c.insert(settings)
        let source = Source(rawText: "original"); c.insert(source)
        let card = Knowledge(learningGoal: "concept", knowledgeType: "concept", theme: "test", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "evidence", evidenceLocator: "", explanation: "explanation")
        card.reviewEnrollment = "enrolled"; card.dueAt = Date(timeIntervalSince1970: 9999999999); card.source = source; c.insert(card)
        let reference = Knowledge(learningGoal: "reference", knowledgeType: "concept", theme: "test", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "reference", evidenceLocator: "")
        c.insert(reference)
        let session = AgentSession(title: "chat", status: "archived"); c.insert(session)
        let round = ReviewSession(mode: "formal", snapshotJSON: ""); round.endedAt = .now; c.insert(round)
        let attempt = ReviewAttempt(sessionId: round.id, knowledgeId: card.id, knowledgeVersion: 1, questionId: UUID(), mode: "formal")
        attempt.reviewState = "completed"; attempt.originalAnswer = "answer"; c.insert(attempt)
        c.insert(FsrsState(knowledgeId: card.id, dueAt: card.dueAt))
        try c.save()
        let approved = try LocalDataReset.impact(.progress, context: c)
        require(try c.fetch(FetchDescriptor<ReviewAttempt>()).count == 1, "preview must not delete")
        do { try LocalDataReset.perform(approved, context: c, save: { throw CocoaError(.fileWriteUnknown) }); preconditionFailure() } catch {}
        c = ModelContext(container)
        require(try c.fetch(FetchDescriptor<ReviewAttempt>()).count == 1, "failed save must rollback")
        require(try c.fetch(FetchDescriptor<FsrsState>()).count == 1)
        let now = Date(timeIntervalSince1970: 2000)
        try LocalDataReset.perform(try LocalDataReset.impact(.progress, context: c), context: c, now: now)
        let cards = try c.fetch(FetchDescriptor<Knowledge>())
        require(cards.count == 2 && cards.first { $0.id == card.id }!.explanation == "explanation")
        require(cards.first { $0.id == card.id }!.dueAt == now)
        require(cards.first { $0.id == reference.id }!.reviewEnrollment == "reference")
        require(try c.fetch(FetchDescriptor<ReviewAttempt>()).isEmpty)
        require(try c.fetch(FetchDescriptor<ReviewSession>()).isEmpty)
        require(try c.fetch(FetchDescriptor<FsrsState>()).isEmpty)
        require(try c.fetch(FetchDescriptor<AgentSession>()).count == 1)
        let stale = try LocalDataReset.impact(.all, context: c)
        c.insert(Source(rawText: "new source")); try c.save()
        do { try LocalDataReset.perform(stale, context: c); preconditionFailure() } catch LocalResetError.changed {}
        let run = AgentRun(id: UUID(), sessionID: session.id); run.status = "running"; c.insert(run); try c.save()
        do { try LocalDataReset.perform(try LocalDataReset.impact(.all, context: c), context: c); preconditionFailure() } catch LocalResetError.busy {}
        run.status = "completed"; try c.save()
        try LocalDataReset.perform(try LocalDataReset.impact(.all, context: c), context: c)
        let fresh = ModelContext(container)
        require(try fresh.fetch(FetchDescriptor<Knowledge>()).isEmpty)
        require(try fresh.fetch(FetchDescriptor<Source>()).isEmpty)
        require(try fresh.fetch(FetchDescriptor<AgentSession>()).isEmpty)
        require(try fresh.fetch(FetchDescriptor<AgentRun>()).isEmpty)
        let retained = try fresh.fetch(FetchDescriptor<AppSettings>()).first!
        require(retained.dailyReminderMinutes == 123 && retained.reviewLanguageOverride == "zh" && retained.developerMode)
        require(retained.agentDraftText.isEmpty)
        require(try SessionDeletion.contains(session.id, context: fresh), "late session results must be fenced")
        require(!LocalDataReset.cleanupJobs(retained).isEmpty, "offline cleanup must persist")
        require(!retained.localDataCleanupJSON.contains("answer") && !retained.sessionDeletionsJSON.contains("chat"))
        try LocalDataReset.perform(try LocalDataReset.impact(.all, context: fresh), context: fresh)
        require(try fresh.fetch(FetchDescriptor<Knowledge>()).isEmpty, "repeated empty cleanup remains safe")
        let pending = LocalDataReset.cleanupJobs(retained).count
        await LocalDataReset.cleanPending(context: fresh, send: { _, _ in throw URLError(.notConnectedToInternet) })
        require(LocalDataReset.cleanupJobs(retained).count == pending, "offline queue remains durable")
        await LocalDataReset.cleanPending(context: fresh, send: { _, _ in Data("{}".utf8) })
        require(LocalDataReset.cleanupJobs(retained).count == pending, "missing receipt is not success")
        await LocalDataReset.cleanPending(context: fresh, send: { path, body in
            require(path == "v2/local-data/cleanup" && body["review_ids"] != nil)
            return Data("{\"cleaned\":true}".utf8)
        })
        require(LocalDataReset.cleanupJobs(retained).isEmpty, "confirmed cleanup clears queue")
        let controller = ReviewController(); controller.session = ReviewSession(mode: "formal", snapshotJSON: "")
        controller.answer = "stale"; let generation = controller.generation
        controller.discardForDataReset()
        require(controller.session == nil && controller.answer.isEmpty && controller.generation > generation)
        print("PASS: reset preview, rollback, preserved knowledge/enrollment/preferences, immediate due, scope changes, busy rejection, full purge, tombstones, durable cleanup, duplicate execution and controller invalidation")
    }
}
