import Foundation
import SwiftData

@main struct ReviewUIIntegrationContracts {
    @MainActor static func main() async throws {
        let db = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = db.mainContext
        let now = Date.now
        let item = Knowledge(learningGoal: "解释光合作用", knowledgeType: "concept", theme: "植物", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "利用光能", evidenceLocator: "合成")
        context.insert(item)
        let spec = AgentAPI.ScoringSpec(learningGoal: item.learningGoal, mustCover: ["光能"], acceptableParaphrases: [], commonMisconceptions: [], evidence: "利用光能", orderRules: "")
        let q = Question(variantIndex: 0, promptText: "利用什么能量？", scoringSpecJSON: try ReviewLedger.encode(spec))
        q.knowledge = item; context.insert(q)
        precondition(TodayReviewProjection(knowledge: [], sessions: [], developerMode: false).kind == .empty)
        precondition(TodayReviewProjection(knowledge: [item], sessions: [], developerMode: false).kind == .unenrolled)
        item.reviewEnrollment = "enrolled"; item.dueAt = now.addingTimeInterval(3600)
        precondition(TodayReviewProjection(knowledge: [item], sessions: [], developerMode: false, now: now).kind == .scheduled)
        item.dueAt = now.addingTimeInterval(-3600)
        precondition(TodayReviewProjection(knowledge: [item], sessions: [], developerMode: false, now: now).kind == .due)
        let coordinator = ReviewCoordinator(), controller = ReviewController()
        controller.syncSession = { _ in }; controller.confirmAttempt = { _, _ in }
        controller.requestTurn = { _, entry, _, _, _, id, _ in
            (ReviewJudgment(intent: "answer", grade: "good", feedback: "独立回忆正确", coverage: [], misconceptions: [], clarificationRevealsAnswer: false, eventId: id, attemptId: entry.id, specVersion: entry.rubricVersion, model: "synthetic", ruleVersion: "test", durationMs: 1, actualCalls: 0, answerRevealed: false), "{}")
        }
        try context.save()
        controller.configure(context, coordinator: coordinator); controller.start(usingVoice: false)
        let ended = controller.session!
        controller.submit("光能")
        for _ in 0..<100 where controller.busy { try await Task.sleep(for: .milliseconds(10)) }
        precondition(controller.phase == "summary" && controller.savedFeedback == "独立回忆正确")
        precondition(controller.savedReaction == "reaction_approve")
        let summary = ReviewRoundSummary(session: ended, attempts: controller.attempts)
        precondition(summary.full && summary.completed == 1 && summary.unfinished == 0 && summary.rows[0].dueAt != nil)
        precondition(TodayReviewProjection(knowledge: [item], sessions: [ended], developerMode: false).kind == .finished)
        let reps = try context.fetch(FetchDescriptor<FsrsState>()).first!.reps
        // Looking at a prior round must never replace an in-progress queue or count a new review.
        item.dueAt = now.addingTimeInterval(-60)
        controller.configure(context, coordinator: coordinator); controller.start(usingVoice: false); controller.pause()
        let active = controller.session!, queue = controller.entries.map(\.id), revision = active.revision
        coordinator.showSummary(sessionID: ended.id); controller.configure(context, coordinator: coordinator)
        precondition(controller.viewingHistory && controller.phase == "summary" && controller.session?.id == ended.id)
        precondition(active.endedAt == nil && active.revision == revision && controller.resumable?.id == active.id)
        precondition(TodayReviewProjection(knowledge: [item], sessions: [ended, active], developerMode: false).kind == .paused)
        precondition((try? context.fetch(FetchDescriptor<FsrsState>()).first?.reps) == reps)
        coordinator.startFormal(knowledgeIDs: [item.id]); controller.configure(context, coordinator: coordinator)
        precondition(coordinator.summarySessionID == nil && !controller.viewingHistory)
        controller.start(usingVoice: false, resume: true)
        precondition(controller.session?.id == active.id && controller.entries.map(\.id) == queue)
        let generation = controller.generation
        controller.phase = "connecting"; controller.useText()
        precondition(controller.phase == "asking" && !controller.voice.connected && controller.generation > generation)
        precondition(controller.entry?.id == queue.first && controller.completed.isEmpty)
        controller.skipOrContinue()
        let skipped = ReviewRoundSummary(session: active, attempts: controller.attempts)
        precondition(!skipped.full && skipped.skipped == 1 && skipped.completed == 0 && skipped.rows[0].dueAt == nil)
        precondition((try? context.fetch(FetchDescriptor<FsrsState>()).first?.reps) == reps)
        // Other rounds and previews do not contaminate a summary or the Today card.
        let preview = ReviewSession(mode: "preview", snapshotJSON: active.snapshotJSON)
        preview.protocolVersion = 2; preview.endedAt = now.addingTimeInterval(20)
        precondition(TodayReviewProjection(knowledge: [item], sessions: [active, preview], developerMode: false).latest?.id == active.id)
        precondition(ReviewRoundSummary(session: preview, attempts: controller.attempts).unfinished == 1)
        coordinator.showSummary(sessionID: UUID()); controller.configure(context, coordinator: coordinator)
        precondition(controller.phase == "setup" && controller.errorText != nil && controller.session == nil)
        preview.endedAt = nil; context.insert(preview); try context.save()
        coordinator.startPreview(knowledgeID: item.id, questionID: UUID()); controller.configure(context, coordinator: coordinator)
        precondition(controller.resumable == nil, "preview for a different question must not resume another queue")
        coordinator.startPreview(knowledgeID: item.id, questionID: q.id); controller.configure(context, coordinator: coordinator)
        precondition(controller.resumable?.id == preview.id)
        print("PASS: six Today states, honest saved/skip/unfinished metrics, saved feedback, history without replacing paused round, fixed resume, connecting-to-text cancellation, missing summary, preview isolation")
    }
}
