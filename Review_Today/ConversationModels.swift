import Foundation
import SwiftData

@Model
final class AgentRun {
    @Attribute(.unique) var id: UUID
    var sessionID: UUID
    var taskID: UUID?
    var inputMessageIDsJSON: String
    var status: String
    var stage: String
    var userSummary: String
    var revision: Int
    var attempt: Int
    var errorCode: String?
    var createdAt: Date
    var updatedAt: Date
    var startedAt: Date?
    var elapsedMS: Int = 0
    var firstTextMS: Int?
    var attemptDurationsJSON: String = "[]"
    var transport: String = ""

    init(id: UUID, sessionID: UUID) {
        self.id = id
        self.sessionID = sessionID
        inputMessageIDsJSON = "[]"
        status = "accepted"
        stage = "received"
        userSummary = "已保存"
        revision = 1
        attempt = 0
        createdAt = .now
        updatedAt = .now
    }
}

@Model
final class SessionEventRecord {
    @Attribute(.unique) var id: UUID
    var sessionID: UUID
    var runID: UUID
    var seq: Int
    var stage: String
    var summary: String
    var detail: String
    var model: String
    var attempt: Int
    var durationMS: Int?
    var errorCode: String?
    var payloadJSON: String
    var occurredAt: Date

    init(id: UUID, sessionID: UUID, runID: UUID, seq: Int) {
        self.id = id
        self.sessionID = sessionID
        self.runID = runID
        self.seq = seq
        stage = "received"
        summary = "已保存"
        detail = ""
        model = ""
        attempt = 0
        payloadJSON = "{}"
        occurredAt = .now
    }
}

@Model
final class AgentRunControl {
    @Attribute(.unique) var id: UUID
    var runID: UUID
    var sessionID: UUID
    var action: String
    var mode: String?
    var createdAt: Date
    var sent: Bool
    var lastError: String?

    init(runID: UUID, sessionID: UUID, action: String, mode: String? = nil) {
        id = UUID()
        self.runID = runID
        self.sessionID = sessionID
        self.action = action
        self.mode = mode
        createdAt = .now
        sent = false
    }
}
