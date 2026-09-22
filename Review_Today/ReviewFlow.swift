import Foundation
import SwiftData
import CryptoKit

enum ReviewFlowError: Error, LocalizedError {
    case invalidResult, stale, saveFailed, noQuestion
    var errorDescription: String? {
        switch self {
        case .invalidResult: "判断结果不完整，本题尚未计入复习。"
        case .stale: "这次回答对应的内容或复习状态已变化，结果没有写入。"
        case .saveFailed: "本机保存未完成，请重试。"
        case .noQuestion: "这条知识暂时没有有效的复习题。"
        }
    }
}

struct ReviewQueueEntry: Codable, Identifiable {
    var id: UUID { attemptID }
    var attemptID: UUID
    var knowledgeID: UUID
    var knowledgeVersion: Int
    var questionID: UUID
    var title: String
    var prompt: String
    var rubricJSON: String
    var rubricVersion: String
    static func version(_ raw: String) -> String {
        SHA256.hash(data: Data(raw.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func validate(_ item: Knowledge, preview: Bool = false) throws {
        guard item.id == knowledgeID, item.version == knowledgeVersion, item.lifecycle == "active",
              preview || item.participatesInReview,
              let question = item.questions.first(where: { $0.id == questionID }),
              question.knowledgeVersion == knowledgeVersion, question.promptText == prompt,
              question.scoringSpecJSON == rubricJSON else { throw ReviewFlowError.stale }
    }
}

struct ReviewDialogLine: Codable, Identifiable {
    var id: UUID = UUID()
    var role: String
    var text: String
    var kind: String = "dialogue"
    var date: Date = .now
}

struct ReviewScheduleSnapshot: Codable {
    var dueAt: Date
    var itemDueAt: Date
    var stability: Double
    var difficulty: Double
    var reps: Int
    var lapses: Int
    var algorithmVersion: String
    var parameterVersion: String
    var lastEffectiveGrade: String
    var schedulerJSON: String?
    var forceDue: Bool
    init(_ state: FsrsState, item: Knowledge) {
        dueAt = state.dueAt; itemDueAt = item.dueAt
        stability = state.stability; difficulty = state.difficulty; reps = state.reps; lapses = state.lapses
        algorithmVersion = state.algorithmVersion; parameterVersion = state.parameterVersion
        lastEffectiveGrade = state.lastEffectiveGrade; schedulerJSON = state.schedulerJSON; forceDue = item.forceDue
    }
    func restore(_ state: FsrsState, item: Knowledge) {
        state.dueAt = dueAt; item.dueAt = itemDueAt; state.stability = stability; state.difficulty = difficulty
        state.reps = reps; state.lapses = lapses; state.algorithmVersion = algorithmVersion
        state.parameterVersion = parameterVersion; state.lastEffectiveGrade = lastEffectiveGrade
        state.schedulerJSON = schedulerJSON; item.forceDue = forceDue
    }
}

enum ReviewLedger {
    static func encode<T: Encodable>(_ value: T) throws -> String {
        String(decoding: try JSONEncoder().encode(value), as: UTF8.self)
    }
    static func queue(_ session: ReviewSession) -> [ReviewQueueEntry] {
        (try? JSONDecoder().decode([ReviewQueueEntry].self, from: Data(session.snapshotJSON.utf8))) ?? []
    }
    static func start(items: [Knowledge], attempts: [ReviewAttempt], goal: String, value: Int,
                      previewQuestionID: UUID? = nil, now: Date = .now) throws -> ReviewSession {
        let selected = goal == "count" ? Array(items.prefix(max(1, min(value, 100)))) : items
        let entries = try selected.map { item -> ReviewQueueEntry in
            let variants = item.questions.filter { $0.knowledgeVersion == item.version }.sorted { $0.variantIndex < $1.variantIndex }
            let count = attempts.filter { $0.knowledgeId == item.id && $0.acked && $0.mode == "formal" }.count
            guard let q = previewQuestionID.flatMap({ id in variants.first { $0.id == id } }) ?? (variants.isEmpty ? nil : variants[count % variants.count]),
                  let data = q.scoringSpecJSON.data(using: .utf8),
                  let spec = try? JSONDecoder().decode(AgentAPI.ScoringSpec.self, from: data),
                  !spec.mustCover.isEmpty, !spec.evidence.isEmpty else { throw ReviewFlowError.noQuestion }
            return ReviewQueueEntry(attemptID: UUID(), knowledgeID: item.id, knowledgeVersion: item.version,
                                    questionID: q.id, title: item.learningGoal, prompt: q.promptText,
                                    rubricJSON: q.scoringSpecJSON, rubricVersion: ReviewQueueEntry.version(q.scoringSpecJSON))
        }
        let session = ReviewSession(mode: previewQuestionID == nil ? "formal" : "preview", snapshotJSON: try encode(entries))
        session.protocolVersion = 2; session.goal = goal; session.goalValue = max(1, min(value, 100))
        session.activeSince = now; session.startedAt = now
        return session
    }
    static func elapsed(_ session: ReviewSession, now: Date = .now) -> Double {
        session.activeSeconds + (session.activeSince.map { max(0, now.timeIntervalSince($0)) } ?? 0)
    }
    static func pause(_ session: ReviewSession, now: Date = .now) {
        session.activeSeconds = elapsed(session, now: now); session.activeSince = nil
        session.paused = true; session.revision += 1; session.endReason = "paused"
    }
    static func checkpoint(_ session: ReviewSession, now: Date = .now) {
        guard !session.paused, session.endedAt == nil else { return }
        session.activeSeconds = elapsed(session, now: now); session.activeSince = now
    }
    static func resume(_ session: ReviewSession, now: Date = .now) {
        session.paused = false; session.activeSince = now; session.revision += 1; session.endReason = ""
    }
    static func advance(_ session: ReviewSession, now: Date = .now) {
        session.currentIndex += 1; session.revision += 1
        if session.currentIndex >= queue(session).count || (session.goal == "minutes" && elapsed(session, now: now) >= Double(session.goalValue) * 60) {
            session.activeSeconds = elapsed(session, now: now); session.activeSince = nil
            session.endedAt = now; session.endReason = session.currentIndex >= queue(session).count ? "queue_finished" : "time_limit"
        }
    }

    /// Schedule + result + cursor are one local transaction. Service delivery is an outbox.
    static func commit(entry: ReviewQueueEntry, item: Knowledge, attempt: ReviewAttempt, session: ReviewSession,
                       grade: String?, context: ModelContext, correcting: Bool = false,
                       now: Date = .now, save: (() throws -> Void)? = nil) throws {
        guard attempt.attemptId == entry.attemptID, attempt.sessionId == session.id else { throw ReviewFlowError.stale }
        if !correcting, ["completed", "skipped", "preview_completed"].contains(attempt.reviewState) {
            guard attempt.effectiveGrade == (grade ?? "") else { throw ReviewFlowError.stale }
            return
        }
        try entry.validate(item, preview: session.mode == "preview")
        guard !session.paused, correcting || session.endedAt == nil else { throw ReviewFlowError.stale }
        if !correcting {
            guard queue(session).indices.contains(session.currentIndex), queue(session)[session.currentIndex].attemptID == entry.attemptID else { throw ReviewFlowError.stale }
        }
        guard grade == nil || ["again", "hard", "good", "easy"].contains(grade!) else { throw ReviewFlowError.invalidResult }
        let all = try context.fetch(FetchDescriptor<ReviewAttempt>())
        if correcting, all.contains(where: { $0.knowledgeId == item.id && $0.acked && $0.attemptId != attempt.attemptId && ($0.completedAt ?? .distantPast) > (attempt.completedAt ?? .distantPast) }) { throw ReviewFlowError.stale }
        let states = try context.fetch(FetchDescriptor<FsrsState>())
        let priorState = states.first { $0.knowledgeId == item.id }
        let state = priorState ?? FsrsState(knowledgeId: item.id, dueAt: item.dueAt)
        let before = ReviewScheduleSnapshot(state, item: item)
        let oldCursor = session.currentIndex, oldRevision = session.revision
        let oldEnd = session.endedAt, oldReason = session.endReason, oldActive = session.activeSeconds, oldSince = session.activeSince
        let oldGrade = attempt.effectiveGrade, oldState = attempt.reviewState, oldAck = attempt.acked
        let oldCompleted = attempt.completedAt, oldBefore = attempt.schedulerBeforeJSON, oldAfter = attempt.schedulerAfterJSON
        let oldCorrection = attempt.correctionRevision, oldPending = attempt.serviceCommitPending
        do {
            if let grade, session.mode != "preview" {
                if priorState == nil { context.insert(state) }
                if correcting {
                    guard let raw = attempt.schedulerBeforeJSON else { throw ReviewFlowError.stale }
                    try JSONDecoder().decode(ReviewScheduleSnapshot.self, from: Data(raw.utf8)).restore(state, item: item)
                } else { attempt.schedulerBeforeJSON = try encode(before) }
                try Fsrs.apply(grade: grade, to: state, now: attempt.judgedAt ?? now)
                item.dueAt = state.dueAt; item.forceDue = false
                attempt.schedulerAfterJSON = try encode(ReviewScheduleSnapshot(state, item: item))
            }
            attempt.effectiveGrade = grade ?? ""; attempt.pendingGrade = ""
            attempt.acked = grade != nil && session.mode != "preview"
            attempt.reviewState = grade == nil ? "skipped" : session.mode == "preview" ? "preview_completed" : "completed"
            attempt.completedAt = correcting ? oldCompleted : now
            attempt.serviceCommitPending = true
            if correcting { attempt.correctionRevision += 1; session.revision += 1 } else { advance(session, now: now) }
            try (save ?? { try context.save() })()
        } catch {
            context.rollback()
            before.restore(state, item: item)
            session.currentIndex = oldCursor; session.revision = oldRevision; session.endedAt = oldEnd
            session.endReason = oldReason; session.activeSeconds = oldActive; session.activeSince = oldSince
            attempt.effectiveGrade = oldGrade; attempt.reviewState = oldState; attempt.acked = oldAck
            attempt.completedAt = oldCompleted; attempt.schedulerBeforeJSON = oldBefore; attempt.schedulerAfterJSON = oldAfter
            attempt.correctionRevision = oldCorrection; attempt.serviceCommitPending = oldPending
            throw error
        }
    }
}
