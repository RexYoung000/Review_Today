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
    var activityKind: String?
    var completedAt: Date?

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

enum LearningActivityCalendar {
    static func uniqueDays(_ dates: [Date], calendar: Calendar = .current) -> [Date] {
        Array(Set(dates.map { calendar.startOfDay(for: $0) })).sorted()
    }

    static func intensity(_ count: Int) -> Int {
        switch count {
        case 0: return 0
        case 1: return 1
        case 2: return 2
        case 3 ... 4: return 3
        default: return 4
        }
    }

    static func currentStreak(_ dates: [Date], today: Date = .now, calendar: Calendar = .current) -> Int {
        let days = Set(uniqueDays(dates, calendar: calendar))
        var cursor = calendar.startOfDay(for: today)
        if !days.contains(cursor), let yesterday = calendar.date(byAdding: .day, value: -1, to: cursor) {
            cursor = yesterday
        }
        var count = 0
        while days.contains(cursor) {
            count += 1
            guard let previous = calendar.date(byAdding: .day, value: -1, to: cursor) else { break }
            cursor = previous
        }
        return count
    }

    static func longestStreak(_ dates: [Date], calendar: Calendar = .current) -> Int {
        let days = uniqueDays(dates, calendar: calendar)
        guard !days.isEmpty else { return 0 }
        var best = 1
        var current = 1
        for index in 1 ..< days.count {
            if calendar.dateComponents([.day], from: days[index - 1], to: days[index]).day == 1 {
                current += 1
                best = max(best, current)
            } else {
                current = 1
            }
        }
        return best
    }
}
