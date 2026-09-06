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
    var title: String = ""
    var explanation: String = ""
    var lifecycle: String
    var createdAt: Date
    var dueAt: Date
    var forceDue: Bool
    var skipTwoHourWait: Bool
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
    var dailyReminderMinutes: Int
    var reviewLanguageOverride: String
    var developerMode: Bool
    var snoozeCount: Int
    var snoozeDay: String
    var skipToday: String
    var notificationGranted: Bool

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
    }
}
