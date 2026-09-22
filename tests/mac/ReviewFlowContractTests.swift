import Foundation
import SwiftData

@main struct ReviewFlowContractTests {
    @MainActor static func main() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        func knowledge(_ title: String) throws -> Knowledge {
            let item = Knowledge(learningGoal: title, knowledgeType: "concept", theme: "test", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "光能、水、二氧化碳生成有机物和氧气", evidenceLocator: "合成资料", createdAt: now.addingTimeInterval(-10000))
            context.insert(item)
            let spec = AgentAPI.ScoringSpec(learningGoal: title, mustCover: ["光能", "原料与产物"], acceptableParaphrases: [], commonMisconceptions: ["吸收氧气"], evidence: item.evidenceExcerpt, orderRules: "")
            for index in 0..<2 {
                let q = Question(variantIndex: index, promptText: "问题 \(index)", scoringSpecJSON: try ReviewLedger.encode(spec))
                q.knowledge = item; context.insert(q)
            }
            return item
        }
        func round(_ item: Knowledge, goal: String = "due") throws -> (ReviewSession, ReviewQueueEntry, ReviewAttempt) {
            let session = try ReviewLedger.start(items: [item], attempts: try context.fetch(FetchDescriptor<ReviewAttempt>()), goal: goal, value: 5, now: now)
            let entry = ReviewLedger.queue(session)[0]
            let attempt = ReviewAttempt(sessionId: session.id, knowledgeId: item.id, knowledgeVersion: item.version, questionId: entry.questionID, mode: "formal")
            attempt.attemptId = entry.attemptID; attempt.judgedAt = now
            context.insert(session); context.insert(attempt); try context.save()
            return (session, entry, attempt)
        }
        let first = try knowledge("光合作用")
        precondition(!ReviewQueue.isDue(first, developerMode: true, now: now), "reference material is never queued")
        first.setReviewParticipation(true, now: now)
        precondition(first.dueAt == now.addingTimeInterval(7200))
        first.dueAt = now.addingTimeInterval(-10)
        let (session, entry, attempt) = try round(first, goal: "minutes")
        session.activeSince = now.addingTimeInterval(-310); try context.save()
        try ReviewLedger.commit(entry: entry, item: first, attempt: attempt, session: session, grade: "good", context: context, now: now)
        precondition(attempt.acked && session.endedAt != nil && first.dueAt > now, "time limit cannot drop the current answer")
        let state = try context.fetch(FetchDescriptor<FsrsState>()).first { $0.knowledgeId == first.id }!
        precondition(state.algorithmVersion == "fsrs-6.0" && state.reps == 1)
        let after = state.schedulerJSON
        try ReviewLedger.commit(entry: entry, item: first, attempt: attempt, session: session, grade: "good", context: context, now: now)
        precondition(state.reps == 1 && state.schedulerJSON == after, "duplicate delivery must not count twice")
        try ReviewLedger.commit(entry: entry, item: first, attempt: attempt, session: session, grade: "again", context: context, correcting: true, now: now)
        precondition(state.reps == 1 && first.dueAt == now.addingTimeInterval(600), "correction recomputes from the pre-review state")
        precondition(attempt.correctionRevision == 1)
        let next = try ReviewLedger.start(items: [first], attempts: [attempt], goal: "due", value: 5, now: now)
        precondition(ReviewLedger.queue(next)[0].questionID != entry.questionID, "variants rotate")
        let second = try knowledge("RAG"); second.setReviewParticipation(true, now: now)
        let (skipSession, skipEntry, skipAttempt) = try round(second)
        let due = second.dueAt
        try ReviewLedger.commit(entry: skipEntry, item: second, attempt: skipAttempt, session: skipSession, grade: nil, context: context, now: now)
        precondition(!skipAttempt.acked && skipAttempt.reviewState == "skipped" && second.dueAt == due)
        let third = try knowledge("迁移"); third.reviewEnrollment = nil
        let legacy = FsrsState(knowledgeId: third.id, dueAt: now); legacy.stability = 900; context.insert(legacy)
        let (failedSession, failedEntry, failedAttempt) = try round(third)
        let oldDate = third.dueAt
        do {
            try ReviewLedger.commit(entry: failedEntry, item: third, attempt: failedAttempt, session: failedSession, grade: "good", context: context, now: now, save: { throw ReviewFlowError.saveFailed })
            preconditionFailure("expected save failure")
        } catch {}
        precondition(!failedAttempt.acked && legacy.reps == 0 && legacy.stability == 900 && third.dueAt == oldDate && failedSession.currentIndex == 0)
        try context.save()
        ReviewLedger.pause(failedSession, now: now)
        do { try ReviewLedger.commit(entry: failedEntry, item: third, attempt: failedAttempt, session: failedSession, grade: "good", context: context); preconditionFailure("late result") } catch {}
        ReviewLedger.resume(failedSession, now: now)
        third.version += 1
        do { try ReviewLedger.commit(entry: failedEntry, item: third, attempt: failedAttempt, session: failedSession, grade: "good", context: context); preconditionFailure("stale knowledge") } catch {}
        third.version -= 1
        try ReviewLedger.commit(entry: failedEntry, item: third, attempt: failedAttempt, session: failedSession, grade: "good", context: context, now: now)
        precondition(legacy.stability < 900 && legacy.algorithmVersion == "fsrs-6.0", "demo parameters are not imported as FSRS memory state")
        third.setReviewParticipation(false)
        precondition(third.lifecycle == "active" && !ReviewQueue.isDue(third, developerMode: true, now: now.addingTimeInterval(999999)))
        let retainedDue = third.dueAt
        third.setReviewParticipation(true, now: now.addingTimeInterval(999999))
        precondition(third.dueAt == retainedDue, "reenrollment preserves a legacy schedule")
        let timed = try ReviewLedger.start(items: [first, second], attempts: [], goal: "minutes", value: 5, now: now)
        let timedEntry = ReviewLedger.queue(timed)[0]
        let timedRow = ReviewAttempt(sessionId: timed.id, knowledgeId: first.id, knowledgeVersion: first.version, questionId: timedEntry.questionID, mode: "formal")
        timedRow.attemptId = timedEntry.attemptID
        context.insert(timed); context.insert(timedRow); try context.save()
        try ReviewLedger.commit(entry: timedEntry, item: first, attempt: timedRow, session: timed, grade: "good", context: context, now: now.addingTimeInterval(301))
        precondition(timed.currentIndex == 1 && timed.endReason == "time_limit" && timedRow.acked)
        let preview = try ReviewLedger.start(items: [second], attempts: [], goal: "due", value: 5, previewQuestionID: second.questions[0].id, now: now)
        let pe = ReviewLedger.queue(preview)[0]
        let pa = ReviewAttempt(sessionId: preview.id, knowledgeId: second.id, knowledgeVersion: second.version, questionId: pe.questionID, mode: "preview")
        pa.attemptId = pe.attemptID; context.insert(preview); context.insert(pa); try context.save()
        let previewDue = second.dueAt
        try ReviewLedger.commit(entry: pe, item: second, attempt: pa, session: preview, grade: "good", context: context, now: now)
        precondition(second.dueAt == previewDue && !pa.acked && pa.reviewState == "preview_completed")
        print("PASS: reference/enrollment, first due, FSRS6, rotation, deadline commit, skip, duplicate, correction, failed-save rollback, cancellation, version fences, legacy bootstrap")
    }
}
