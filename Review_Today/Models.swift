import Foundation
import SwiftData

@Model
final class Source {
    @Attribute(.unique) var id: UUID
    var createdAt: Date
    var inputType: String
    var rawText: String
    var url: String?
    var audioPath: String?
    var attribution: String
    @Relationship(deleteRule: .cascade, inverse: \Knowledge.source)
    var knowledgeItems: [Knowledge]
    @Relationship(deleteRule: .cascade, inverse: \CaptureTask.source)
    var tasks: [CaptureTask]

    init(
        id: UUID = UUID(),
        createdAt: Date = .now,
        inputType: String = "text",
        rawText: String,
        url: String? = nil,
        audioPath: String? = nil,
        attribution: String = "claim"
    ) {
        self.id = id
        self.createdAt = createdAt
        self.inputType = inputType
        self.rawText = rawText
        self.url = url
        self.audioPath = audioPath
        self.attribution = attribution
        self.knowledgeItems = []
        self.tasks = []
    }
}

@Model
final class Knowledge {
    @Attribute(.unique) var id: UUID
    var version: Int
    var learningGoal: String
    var knowledgeType: String
    var theme: String
    var contentLanguage: String
    var questionLanguage: String
    var answerLanguage: String
    var evidenceExcerpt: String
    var evidenceLocator: String
    var originSessionID: UUID?
    var originTaskID: UUID?
    var title: String = ""
    var explanation: String = ""
    var lifecycle: String
    var createdAt: Date
    var dueAt: Date
    var forceDue: Bool
    var skipTwoHourWait: Bool
    // nil is the legacy enrolled state. New saves explicitly start as reference material.
    var reviewEnrollment: String? = nil
    var studiedAt: Date? = nil
    var source: Source?
    @Relationship(deleteRule: .cascade, inverse: \Question.knowledge)
    var questions: [Question]

    init(
        id: UUID = UUID(),
        version: Int = 1,
        learningGoal: String,
        knowledgeType: String,
        theme: String,
        contentLanguage: String,
        questionLanguage: String,
        answerLanguage: String,
        evidenceExcerpt: String,
        evidenceLocator: String,
        title: String = "",
        explanation: String = "",
        lifecycle: String = "active",
        createdAt: Date = .now,
        dueAt: Date? = nil
    ) {
        self.id = id
        self.version = version
        self.learningGoal = learningGoal
        self.knowledgeType = knowledgeType
        self.theme = theme
        self.contentLanguage = contentLanguage
        self.questionLanguage = questionLanguage
        self.answerLanguage = answerLanguage
        self.evidenceExcerpt = evidenceExcerpt
        self.evidenceLocator = evidenceLocator
        self.title = title
        self.explanation = explanation
        self.lifecycle = lifecycle
        self.createdAt = createdAt
        self.dueAt = dueAt ?? createdAt.addingTimeInterval(2 * 60 * 60)
        self.forceDue = false
        self.skipTwoHourWait = false
        self.reviewEnrollment = "reference"
        self.questions = []
    }
}

@Model
final class Question {
    @Attribute(.unique) var id: UUID
    var knowledgeVersion: Int
    var variantIndex: Int
    var promptText: String
    var scoringSpecJSON: String
    var knowledge: Knowledge?

    init(
        id: UUID = UUID(),
        knowledgeVersion: Int = 1,
        variantIndex: Int,
        promptText: String,
        scoringSpecJSON: String
    ) {
        self.id = id
        self.knowledgeVersion = knowledgeVersion
        self.variantIndex = variantIndex
        self.promptText = promptText
        self.scoringSpecJSON = scoringSpecJSON
    }
}

@Model
final class CaptureTask {
    @Attribute(.unique) var id: UUID
    var status: String
    var userStatus: String
    var createdAt: Date
    var updatedAt: Date
    var retryCount: Int
    var errorCode: String?
    var receiptJSON: String?
    var payloadJSON: String?
    var eventsJSON: String?
    var statusTrailJSON: String?
    var intent: String?
    var localCommitDone: Bool
    var source: Source?

    init(
        id: UUID = UUID(),
        status: String = "queued",
        userStatus: String = "已保存，等待处理",
        createdAt: Date = .now,
        retryCount: Int = 0
    ) {
        self.id = id
        self.status = status
        self.userStatus = userStatus
        self.createdAt = createdAt
        self.updatedAt = createdAt
        self.retryCount = retryCount
        self.localCommitDone = false
    }
}

@Model
final class AppSettings {
    var reviewGoal: String = "due"
    var reviewGoalValue: Int = 5
    var dailyReminderMinutes: Int
    var reviewLanguageOverride: String
    var developerMode: Bool
    var snoozeCount: Int
    var snoozeDay: String
    var skipToday: String
    var notificationGranted: Bool
    var agentDraftID: UUID?
    var agentDraftMessageID: UUID?
    var agentDraftText: String = ""
    var agentDraftMode: String = "auto"
    var agentDraftThinking: String = "smart"
    var lastThinkingStrength: String = "smart"
    var sessionDeletionsJSON: String = "[]"
    var localDataCleanupJSON: String = "[]"

    init(
        dailyReminderMinutes: Int = 21 * 60,
        reviewLanguageOverride: String = "system",
        developerMode: Bool = false
    ) {
        self.dailyReminderMinutes = dailyReminderMinutes
        self.reviewLanguageOverride = reviewLanguageOverride
        self.developerMode = developerMode
        self.snoozeCount = 0
        self.snoozeDay = ""
        self.skipToday = ""
        self.notificationGranted = false
    }
}

@Model
final class FsrsState {
    var schedulerJSON: String? = nil
    @Attribute(.unique) var knowledgeId: UUID
    var dueAt: Date
    var stability: Double
    var difficulty: Double
    var reps: Int
    var lapses: Int
    var algorithmVersion: String
    var parameterVersion: String
    var lastEffectiveGrade: String

    init(knowledgeId: UUID, dueAt: Date) {
        self.knowledgeId = knowledgeId
        self.dueAt = dueAt
        self.stability = 0.4
        self.difficulty = 5
        self.reps = 0
        self.lapses = 0
        self.algorithmVersion = "fsrs-4.5-demo"
        self.parameterVersion = "1"
        self.lastEffectiveGrade = ""
    }
}

@Model
final class ReviewSession {
    var protocolVersion: Int = 1
    var currentIndex: Int = 0
    var goal: String = "due"
    var goalValue: Int = 5
    var activeSeconds: Double = 0
    var activeSince: Date? = nil
    var revision: Int = 0
    var recordsJSON: String = "[]"
    @Attribute(.unique) var id: UUID
    var mode: String
    var startedAt: Date
    var windowStartedAt: Date
    var endedAt: Date?
    var endReason: String
    var snapshotJSON: String
    var paused: Bool

    init(mode: String, snapshotJSON: String) {
        self.id = UUID()
        self.mode = mode
        self.startedAt = .now
        self.windowStartedAt = .now
        self.endReason = ""
        self.snapshotJSON = snapshotJSON
        self.paused = false
    }
}

@Model
final class ReviewAttempt {
    var rubricJSON: String = ""
    var promptSnapshot: String = ""
    var rubricVersion: String = ""
    var originalAnswer: String = ""
    var correctedAnswer: String? = nil
    var independentGrade: String = ""
    var feedbackText: String = ""
    var assistanceJSON: String = "[]"
    var dialogJSON: String = "[]"
    var evaluationJSON: String = "{}"
    var schedulerBeforeJSON: String? = nil
    var schedulerAfterJSON: String? = nil
    var judgedAt: Date? = nil
    var correctionRevision: Int = 0
    var serviceCommitPending: Bool = false
    @Attribute(.unique) var attemptId: UUID
    var sessionId: UUID
    var knowledgeId: UUID
    var knowledgeVersion: Int
    var questionId: UUID
    var mode: String
    var agentGrade: String
    var effectiveGrade: String
    var pendingGrade: String = ""
    var reviewState: String = "grading"
    var reviewErrorCode: String?
    var reviewUserStatus: String = ""
    var hintUsed: Bool
    var transcriptRetryCount: Int
    var earlyReview: Bool
    var degradedPath: String
    var answerText: String
    var acked: Bool
    var createdAt: Date = Date.now
    var completedAt: Date?

    init(
        sessionId: UUID,
        knowledgeId: UUID,
        knowledgeVersion: Int,
        questionId: UUID,
        mode: String
    ) {
        self.attemptId = UUID()
        self.sessionId = sessionId
        self.knowledgeId = knowledgeId
        self.knowledgeVersion = knowledgeVersion
        self.questionId = questionId
        self.mode = mode
        self.agentGrade = ""
        self.effectiveGrade = ""
        self.pendingGrade = ""
        self.reviewState = "grading"
        self.reviewErrorCode = nil
        self.reviewUserStatus = "正在判断"
        self.hintUsed = false
        self.transcriptRetryCount = 0
        self.earlyReview = false
        self.degradedPath = "text"
        self.answerText = ""
        self.acked = false
        self.createdAt = .now
    }
}

// MARK: - Agent Harness V2

@Model
final class AgentSession {
    var folderID: UUID? = nil
    @Attribute(.unique) var id: UUID
    var title: String
    var modePreset: String
    var status: String
    var createdAt: Date
    var updatedAt: Date
    var archivedAt: Date?
    var summaryText: String
    var sourceSessionID: UUID?
    var lastSessionEventSeq: Int = 0
    var lifecycleRevision: Int = 0
    var lifecycleSyncedRevision: Int = 0
    var lifecycleActionsJSON: String = "[]"
    var checkpointJSON: String?
    var learningChecklistExpanded: Bool = false
    var runPaused: Bool = false
    var captureOffersJSON: String = "[]"
    var captureOffersRevision: Int = 0
    var pendingOperationJSON: String?
    var handoffID: String?
    var handoffJSON: String?
    var syncError: String?
    var composerDraft: String = ""
    var autoTopicTagsJSON: String = "[]"
    var manualTopicTagsJSON: String?
    var topicTagRevision: Int = 0
    var topicTagsUpdatedAt: Date?
    var memoryUseAllowed: Bool = true
    var memoryPolicyRevision: Int = 0
    var memoryContentRevision: Int = 0
    var memoryPolicySyncedRevision: Int = -1
    var memoryContentSyncedRevision: Int = -1
    var learningEvidenceJSON: String = "[]"
    var thinkingStrength: String = "smart"
    var contextCapacityJSON: String?

    init(
        id: UUID = UUID(),
        title: String = "新学习 Session",
        modePreset: String = "auto",
        status: String = "active",
        createdAt: Date = .now,
        sourceSessionID: UUID? = nil
    ) {
        self.id = id
        self.title = title
        self.modePreset = modePreset
        self.status = status
        self.createdAt = createdAt
        self.updatedAt = createdAt
        self.summaryText = ""
        self.sourceSessionID = sourceSessionID
    }
}

extension AgentSession {
    var automaticTopicTags: [String] { Self.decodeTags(autoTopicTagsJSON) }
    var manualTopicTags: [String]? { manualTopicTagsJSON.map(Self.decodeTags) }
    var displayTopicTags: [String] { manualTopicTags ?? automaticTopicTags }

    func setAutomaticTopicTags(_ tags: [String]) {
        let normalized = Self.normalizedTags(tags)
        guard !normalized.isEmpty, normalized != automaticTopicTags else { return }
        autoTopicTagsJSON = Self.encodeTags(normalized)
        topicTagRevision += 1
        topicTagsUpdatedAt = .now
    }

    func setManualTopicTags(_ tags: [String]) {
        manualTopicTagsJSON = Self.encodeTags(Self.normalizedTags(tags))
        topicTagRevision += 1
        topicTagsUpdatedAt = .now
    }

    func restoreAutomaticTopicTags() {
        manualTopicTagsJSON = nil
        topicTagRevision += 1
        topicTagsUpdatedAt = .now
    }

    private static func normalizedTags(_ tags: [String]) -> [String] {
        var seen = Set<String>()
        return tags.compactMap { raw in
            let tag = String(raw.trimmingCharacters(in: .whitespacesAndNewlines).prefix(18))
            guard !tag.isEmpty, seen.insert(tag.lowercased()).inserted else { return nil }
            return tag
        }.prefix(5).map { $0 }
    }

    private static func encodeTags(_ tags: [String]) -> String {
        guard let data = try? JSONEncoder().encode(tags) else { return "[]" }
        return String(decoding: data, as: UTF8.self)
    }

    private static func decodeTags(_ raw: String) -> [String] {
        (try? JSONDecoder().decode([String].self, from: Data(raw.utf8))) ?? []
    }
}

@Model
final class AgentMessage {
    var reviewRequested: Bool = false
    @Attribute(.unique) var id: UUID
    var clientMessageID: UUID?
    var sessionID: UUID
    var taskID: UUID?
    var role: String
    var content: String
    var contentType: String
    var createdAt: Date
    var deliveryStatus: String
    var runID: UUID?
    var deliveryMode: String = "steer"
    var operationJSON: String?
    var lastDeliveryError: String?
    var responseState: String = "complete"
    var responseRevision: Int = 0
    var responseChunkSeq: Int = 0
    var firstDisplayedAt: Date?
    var firstReceivedAt: Date?
    var localEchoMS: Int?
    var localSavedMS: Int?

    init(
        id: UUID = UUID(),
        clientMessageID: UUID? = nil,
        sessionID: UUID,
        taskID: UUID? = nil,
        role: String,
        content: String,
        contentType: String = "text",
        createdAt: Date = .now,
        deliveryStatus: String = "local"
    ) {
        self.id = id
        self.clientMessageID = clientMessageID
        self.sessionID = sessionID
        self.taskID = taskID
        self.role = role
        self.content = content
        self.contentType = contentType
        self.createdAt = createdAt
        self.deliveryStatus = deliveryStatus
    }
}

@Model
final class LearningTask {
    @Attribute(.unique) var id: UUID
    var sessionID: UUID
    var inputMessageID: UUID
    var mode: String
    var status: String
    var stage: String
    var userSummary: String
    var createdAt: Date
    var updatedAt: Date
    var retryCount: Int
    var errorCode: String?
    var requiredActionType: String?
    var requiredActionPrompt: String?
    var requiredActionOptionsJSON: String?
    var lastEventSeq: Int
    var lastAckedSeq: Int
    var resultSummary: String
    var pendingActionID: UUID?
    var pendingActionType: String?
    var pendingActionContent: String?
    var sourceID: UUID?
    var memoryCommitted: Bool
    var conversationManaged: Bool = false
    var understanding: String = "unknown"
    var lifecycleRevision: Int = 0
    var goalOwnershipJSON: String?
    var learningPlanJSON: String?
    var learningOutcomeJSON: String?
    var sourcesJSON: String?
    var draftTargetID: String?
    var memoryReferencesJSON: String = "[]"

    init(
        id: UUID = UUID(),
        sessionID: UUID,
        inputMessageID: UUID,
        mode: String = "auto",
        status: String = "accepted",
        stage: String = "accepted",
        userSummary: String = "已保存，准备处理",
        createdAt: Date = .now,
        sourceID: UUID? = nil
    ) {
        self.id = id
        self.sessionID = sessionID
        self.inputMessageID = inputMessageID
        self.mode = mode
        self.status = status
        self.stage = stage
        self.userSummary = userSummary
        self.createdAt = createdAt
        self.updatedAt = createdAt
        self.retryCount = 0
        self.lastEventSeq = 0
        self.lastAckedSeq = 0
        self.resultSummary = ""
        self.sourceID = sourceID
        self.memoryCommitted = false
    }
}

@Model
final class TaskEventRecord {
    @Attribute(.unique) var eventID: UUID
    var sessionID: UUID
    var taskID: UUID
    var seq: Int
    var occurredAt: Date
    var stage: String
    var state: String
    var node: String
    var userSummary: String
    var detailSummary: String
    var attempt: Int
    var durationMS: Int?
    var errorCode: String?
    var recoveryAction: String?
    var requiredActionJSON: String?
    var messageID: UUID?

    init(
        eventID: UUID,
        sessionID: UUID,
        taskID: UUID,
        seq: Int,
        occurredAt: Date,
        stage: String,
        state: String,
        node: String,
        userSummary: String,
        detailSummary: String,
        attempt: Int,
        durationMS: Int? = nil,
        errorCode: String? = nil,
        recoveryAction: String? = nil,
        requiredActionJSON: String? = nil,
        messageID: UUID? = nil
    ) {
        self.eventID = eventID
        self.sessionID = sessionID
        self.taskID = taskID
        self.seq = seq
        self.occurredAt = occurredAt
        self.stage = stage
        self.state = state
        self.node = node
        self.userSummary = userSummary
        self.detailSummary = detailSummary
        self.attempt = attempt
        self.durationMS = durationMS
        self.errorCode = errorCode
        self.recoveryAction = recoveryAction
        self.requiredActionJSON = requiredActionJSON
        self.messageID = messageID
    }
}

@Model
final class SourceReference {
    @Attribute(.unique) var id: UUID
    var sessionID: UUID
    var taskID: UUID?
    var url: String
    var title: String
    var evidenceState: String
    var locator: String
    var createdAt: Date
    var sourceType: String = "public_source"
    var sourceVersion: Int = 1
    var fetchedAt: Date?
    var contentSnapshot: String = ""
    var versionHistoryJSON: String = "[]"

    init(sessionID: UUID, taskID: UUID? = nil, url: String, title: String, evidenceState: String = "unverified", locator: String = "") {
        self.id = UUID()
        self.sessionID = sessionID
        self.taskID = taskID
        self.url = url
        self.title = title
        self.evidenceState = evidenceState
        self.locator = locator
        self.createdAt = .now
    }
}

@Model
final class KnowledgeReference {
    @Attribute(.unique) var id: UUID
    var sessionID: UUID
    var taskID: UUID?
    var knowledgeID: UUID
    var relation: String
    var createdAt: Date

    init(sessionID: UUID, taskID: UUID? = nil, knowledgeID: UUID, relation: String = "related") {
        self.id = UUID()
        self.sessionID = sessionID
        self.taskID = taskID
        self.knowledgeID = knowledgeID
        self.relation = relation
        self.createdAt = .now
    }
}

@Model
final class SessionSummaryRecord {
    @Attribute(.unique) var id: UUID
    var sessionID: UUID
    var version: Int
    var goal: String
    var confirmedDecisionsJSON: String
    var sourceRefsJSON: String
    var knowledgeRefsJSON: String
    var openQuestionsJSON: String
    var updatedAt: Date

    init(sessionID: UUID, version: Int = 1, goal: String = "") {
        self.id = UUID()
        self.sessionID = sessionID
        self.version = version
        self.goal = goal
        self.confirmedDecisionsJSON = "[]"
        self.sourceRefsJSON = "[]"
        self.knowledgeRefsJSON = "[]"
        self.openQuestionsJSON = "[]"
        self.updatedAt = .now
    }
}
