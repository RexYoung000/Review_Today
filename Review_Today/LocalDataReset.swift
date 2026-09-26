import Foundation
import SwiftData

extension Notification.Name {
    static let localDataWillReset = Notification.Name("ReviewToday.LocalDataWillReset")
    static let localDataDidReset = Notification.Name("ReviewToday.LocalDataDidReset")
}

enum LocalResetKind: String, Identifiable {
    case progress, all
    var id: String { rawValue }
    var title: String { self == .progress ? "重置复习进度" : "清空全部学习数据" }
}

struct LocalResetImpact: Identifiable, Equatable {
    let kind: LocalResetKind
    let signature: [String]
    let knowledge: Int
    let sessions: Int
    let attempts: Int
    let rounds: Int
    var id: String { kind.rawValue }
}

struct LocalCleanupJob: Codable, Equatable {
    var id = UUID()
    var reviewIDs: [UUID]
    var captureIDs: [UUID]
    var attemptIDs: [UUID]
    var localFiles: [String]? = nil
}

enum LocalResetError: LocalizedError {
    case busy, changed
    var errorDescription: String? {
        switch self {
        case .busy: "还有生成、入库或判题正在进行，请先停止或完成，再清理。"
        case .changed: "数据已变化，请关闭确认页，重新查看清理范围。"
        }
    }
}

@MainActor
enum LocalDataReset {
    static var generation = 0
    static func impact(_ kind: LocalResetKind, context: ModelContext) throws -> LocalResetImpact {
        let cards = try context.fetch(FetchDescriptor<Knowledge>())
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
        let rounds = try context.fetch(FetchDescriptor<ReviewSession>())
        var signature = cards.map { "k:\($0.id):\($0.version):\($0.reviewEnrollment ?? "legacy"):\($0.dueAt.timeIntervalSince1970)" }
        signature += attempts.map { "a:\($0.attemptId):\($0.correctionRevision):\($0.reviewState)" }
        signature += rounds.map { "r:\($0.id):\($0.revision)" }
        if kind == .all {
            signature += sessions.map { "s:\($0.id):\($0.lifecycleRevision):\($0.updatedAt.timeIntervalSince1970)" }
            signature += try context.fetch(FetchDescriptor<CaptureTask>()).map { "c:\($0.id):\($0.status)" }
            signature += try context.fetch(FetchDescriptor<Source>()).map { "source:\($0.id)" }
            signature += try context.fetch(FetchDescriptor<AgentMessage>()).map { "m:\($0.id):\($0.deliveryStatus):\($0.content.hashValue)" }
            signature += sessions.map { "draft:\($0.id):\($0.composerDraft.hashValue):\($0.composerImage?.hashValue ?? 0)" }
            signature += try context.fetch(FetchDescriptor<AppSettings>()).map { "landing:\($0.agentDraftText.hashValue):\($0.agentDraftImage?.hashValue ?? 0)" }
            signature += try context.fetch(FetchDescriptor<LearningTask>()).map { "t:\($0.id):\($0.updatedAt.timeIntervalSince1970)" }
        }
        return LocalResetImpact(kind: kind, signature: signature.sorted(), knowledge: cards.count,
                                sessions: sessions.count, attempts: attempts.count, rounds: rounds.count)
    }

    static func ensureIdle(_ context: ModelContext) throws {
        let runs = try context.fetch(FetchDescriptor<AgentRun>())
        let captures = try context.fetch(FetchDescriptor<CaptureTask>())
        let tasks = try context.fetch(FetchDescriptor<LearningTask>())
        let messages = try context.fetch(FetchDescriptor<AgentMessage>())
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
        let liveRounds = Set(try context.fetch(FetchDescriptor<ReviewSession>()).filter { !$0.paused && $0.endedAt == nil }.map(\.id))
        if runs.contains(where: { ["accepted", "running", "queued", "adjusting", "stopping", "resuming"].contains($0.status) })
            || captures.contains(where: { ["queued", "retryable_failed", "uploading", "processing", "committing"].contains($0.status) || ($0.status == "completed" && !$0.localCommitDone) })
            || tasks.contains(where: { ["accepted", "running", "committing"].contains($0.status) })
            || messages.contains(where: { $0.role == "user" && ["local", "sending"].contains($0.deliveryStatus) })
            || sessions.contains(where: { TopicCaptureOffer.read($0.captureOffersJSON).contains { $0.status == "saving" } })
            || attempts.contains(where: { liveRounds.contains($0.sessionId) && ["judging", "grading"].contains($0.reviewState) }) {
            throw LocalResetError.busy
        }
    }

    /// No suspension between scope revalidation and the single atomic save.
    static func perform(_ approved: LocalResetImpact, context: ModelContext, now: Date = .now,
                        save: (() throws -> Void)? = nil) throws {
        try ensureIdle(context)
        guard try impact(approved.kind, context: context) == approved else { throw LocalResetError.changed }
        generation += 1
        NotificationCenter.default.post(name: .localDataWillReset, object: approved.kind)
        do {
            let settings = try AgentComposerStore.settings(context)
            let rounds = try context.fetch(FetchDescriptor<ReviewSession>())
            let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
            let sessions = try context.fetch(FetchDescriptor<AgentSession>())
            let captures = try context.fetch(FetchDescriptor<CaptureTask>())
            let sources = try context.fetch(FetchDescriptor<Source>())
            let sessionIDs = Set(sessions.map(\.id))
            var files = approved.kind == .all ? sources.compactMap(\.audioPath).filter(isOwnedCaptureFile) : []
            if approved.kind == .all {
                files += sessionIDs.flatMap { [DictationFiles.audio($0).path, DictationFiles.result($0).path] }
            }
            var jobs = cleanupJobs(settings)
            jobs.append(LocalCleanupJob(reviewIDs: rounds.map(\.id), captureIDs: approved.kind == .all ? captures.map(\.id) : [], attemptIDs: attempts.map(\.attemptId), localFiles: files))
            settings.localDataCleanupJSON = String(decoding: try JSONEncoder().encode(jobs), as: UTF8.self)
            for row in rounds { context.delete(row) }
            for row in attempts { context.delete(row) }
            try remove(FsrsState.self, context)
            let cards = try context.fetch(FetchDescriptor<Knowledge>())
            if approved.kind == .progress {
                for card in cards {
                    card.forceDue = false; card.skipTwoHourWait = false
                    if card.participatesInReview { card.dueAt = now }
                }
            } else {
                var markers = try SessionDeletion.records(context)
                for session in sessions {
                    markers.append(["session_id": session.id.uuidString.lowercased(), "action_id": UUID().uuidString.lowercased(),
                                    "archive_action_id": UUID().uuidString.lowercased(), "action": "delete",
                                    "lifecycle_revision": session.lifecycleRevision + (session.status == "active" ? 2 : 1),
                                    "deleted_at": now.ISO8601Format(), "cleaned": false])
                }
                settings.sessionDeletionsJSON = ConversationProcessor.json(markers)
                try remove(AgentMessage.self, context); try remove(AgentRunControl.self, context)
                try remove(SessionEventRecord.self, context); try remove(AgentRun.self, context)
                try remove(TaskEventRecord.self, context); try remove(LearningTask.self, context)
                try remove(SourceReference.self, context); try remove(KnowledgeReference.self, context)
                try remove(SessionSummaryRecord.self, context); try remove(SessionFolder.self, context)
                try remove(AgentSession.self, context); try remove(CaptureTask.self, context)
                try remove(Question.self, context); try remove(Knowledge.self, context); try remove(Source.self, context)
                settings.agentDraftID = nil; settings.agentDraftMessageID = nil; settings.agentDraftText = ""
                settings.agentDraftImage = nil
            }
            settings.skipToday = ""; settings.snoozeDay = ""; settings.snoozeCount = 0
            if let save { try save() } else { try context.save() }
            if approved.kind == .all {
                NotificationCenter.default.post(name: .dictationSessionsDeleted, object: sessionIDs)
            }
            NotificationCenter.default.post(name: .localDataDidReset, object: approved.kind)
            ConversationSync.wake()
        } catch { context.rollback(); throw error }
    }
    private static func remove<T: PersistentModel>(_ type: T.Type, _ context: ModelContext) throws {
        for row in try context.fetch(FetchDescriptor<T>()) { context.delete(row) }
    }
    static func cleanupJobs(_ settings: AppSettings) -> [LocalCleanupJob] {
        (try? JSONDecoder().decode([LocalCleanupJob].self, from: Data(settings.localDataCleanupJSON.utf8))) ?? []
    }
    private static func isOwnedCaptureFile(_ path: String) -> Bool {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].standardizedFileURL
        return url.deletingLastPathComponent() == root && url.lastPathComponent.hasPrefix("capture-") && url.pathExtension == "m4a"
    }
    static func cleanPending(context: ModelContext, send: @MainActor (String, [String: Any]) async throws -> Data = ReviewAPI.send) async {
        guard let settings = try? context.fetch(FetchDescriptor<AppSettings>()).first else { return }
        for job in cleanupJobs(settings) {
            do {
                for path in job.localFiles ?? [] {
                    let url = URL(fileURLWithPath: path).standardizedFileURL
                    let dictation = url.deletingLastPathComponent() == DictationFiles.root.standardizedFileURL && ["wav", "json"].contains(url.pathExtension)
                    guard dictation || isOwnedCaptureFile(path) else { continue }
                    if FileManager.default.fileExists(atPath: path) { try FileManager.default.removeItem(at: url) }
                }
                let data = try await send("v2/local-data/cleanup", [
                    "review_ids": job.reviewIDs.map { $0.uuidString.lowercased() },
                    "capture_ids": job.captureIDs.map { $0.uuidString.lowercased() },
                    "attempt_ids": job.attemptIDs.map { $0.uuidString.lowercased() }])
                guard let result = try JSONSerialization.jsonObject(with: data) as? [String: Any], result["cleaned"] as? Bool == true else { return }
                let remaining = cleanupJobs(settings).filter { $0.id != job.id }
                settings.localDataCleanupJSON = String(decoding: try JSONEncoder().encode(remaining), as: UTF8.self)
                try context.save()
            } catch { return }
        }
    }
}
