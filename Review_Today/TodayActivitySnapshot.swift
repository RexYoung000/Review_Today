import Foundation
import SwiftData
import Observation

struct TodayActivity: Identifiable, Equatable {
    let id: String
    let date: Date
    let kind: String
    let title: String
    var sessionID: UUID? = nil
    var knowledgeID: UUID? = nil

    static func kindLabel(_ kind: String) -> String {
        switch kind {
        case "lesson_step": return "资料学习"
        case "formal_review": return "正式复习"
        default: return "知识回答"
        }
    }

    static func project(runs: [AgentRun], attempts: [ReviewAttempt], sessions: [AgentSession], knowledge: [Knowledge]) -> [Self] {
        let sessionsByID = Dictionary(sessions.map { ($0.id, $0.title) }, uniquingKeysWith: { first, _ in first })
        let knowledgeByID = Dictionary(knowledge.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var titles: [UUID: String] = [:]
        var result = runs.compactMap { run -> Self? in
            guard run.status == "completed", let kind = run.activityKind, let date = run.completedAt else { return nil }
            return Self(id: "run-\(run.id)", date: date, kind: kind, title: sessionsByID[run.sessionID] ?? "学习会话", sessionID: run.sessionID)
        }
        for row in attempts where row.mode != "preview" && row.acked && !row.effectiveGrade.isEmpty {
            guard let date = row.completedAt else { continue }
            if titles[row.knowledgeId] == nil {
                titles[row.knowledgeId] = knowledgeByID[row.knowledgeId].map { KnowledgeLexicon.keyword(for: $0, clipped: false) } ?? "正式复习"
            }
            result.append(Self(id: "review-\(row.attemptId)", date: date, kind: "formal_review", title: titles[row.knowledgeId]!, knowledgeID: row.knowledgeId))
        }
        return result
    }
}

struct TodayActivitySnapshot {
    struct Day: Identifiable {
        var id: Date { date }
        let date: Date
        let count: Int
        let level: Int
        let future: Bool
        let help: String
    }
    let days: [Day]
    let months: [String?]
    let weekdayLabels: [String]
    let activitiesByDay: [Date: [TodayActivity]]
    let activeDays: Int
    let currentStreak: Int
    let longestStreak: Int
    var isEmpty: Bool { activitiesByDay.isEmpty }

    init(activities: [TodayActivity], calendar: Calendar, today: Date, locale: Locale) {
        let today = calendar.startOfDay(for: today)
        // Stable object IDs, not titles, define activity identity.
        var seen = Set<String>()
        let unique = activities.filter { seen.insert($0.id).inserted }
        activitiesByDay = Dictionary(grouping: unique) { calendar.startOfDay(for: $0.date) }
            .mapValues { $0.sorted { $0.date < $1.date } }
        let dates = Array(activitiesByDay.keys)
        activeDays = dates.count
        currentStreak = LearningActivityCalendar.currentStreak(dates, today: today, calendar: calendar)
        longestStreak = LearningActivityCalendar.longestStreak(dates, calendar: calendar)
        let offset = (calendar.component(.weekday, from: today) - calendar.firstWeekday + 7) % 7
        let week = calendar.date(byAdding: .day, value: -offset, to: today)!
        let start = calendar.date(byAdding: .weekOfYear, value: -25, to: week)!
        var dateStyle = Date.FormatStyle(date: .abbreviated, time: .omitted)
        dateStyle.calendar = calendar; dateStyle.locale = locale; dateStyle.timeZone = calendar.timeZone
        let formatter = DateFormatter()
        formatter.calendar = calendar; formatter.locale = locale; formatter.timeZone = calendar.timeZone
        let symbols = formatter.veryShortStandaloneWeekdaySymbols ?? ["日", "一", "二", "三", "四", "五", "六"]
        let first = max(0, min(6, calendar.firstWeekday - 1))
        weekdayLabels = Array(symbols[first...]) + Array(symbols[..<first])
        formatter.setLocalizedDateFormatFromTemplate("MMM")
        var monthLabels: [String?] = []
        var cells: [Day] = []
        for index in 0..<182 {
            let date = calendar.date(byAdding: .day, value: index, to: start)!
            let rows = activitiesByDay[date] ?? []
            let counts = Dictionary(grouping: rows, by: \.kind).mapValues(\.count)
            let details = counts.keys.sorted().map { "\(TodayActivity.kindLabel($0)) \(counts[$0]!)" }.joined(separator: "，")
            let help = "\(date.formatted(dateStyle))：\(rows.count) 次\(details.isEmpty ? "" : "（\(details)）")"
            cells.append(Day(date: date, count: rows.count, level: LearningActivityCalendar.intensity(rows.count), future: date > today, help: help))
            if index.isMultiple(of: 7) {
                let previous = calendar.date(byAdding: .day, value: -7, to: date)!
                monthLabels.append(index == 0 || calendar.component(.month, from: previous) != calendar.component(.month, from: date) ? formatter.string(from: date) : nil)
            }
        }
        days = cells; months = monthLabels
    }
}

/// One bounded, view-independent value snapshot survives Today unmounting. Model
/// values are read on the owning actor; no context or models cross an executor.
@Observable final class TodayActivityCache {
    var sourceActivities: [TodayActivity] = []
    @ObservationIgnored private var activities: [TodayActivity] = []
    @ObservationIgnored private var calendar: Calendar?
    @ObservationIgnored private var today: Date?
    @ObservationIgnored private var locale: Locale?
    @ObservationIgnored private var value: TodayActivitySnapshot?
    @ObservationIgnored private(set) var generation = 0
#if DEBUG || PERFORMANCE_QA
    @ObservationIgnored var sourceProjectionCount = 0
#endif

    func snapshot(activities: [TodayActivity], calendar: Calendar, now: Date, locale: Locale) -> TodayActivitySnapshot {
        let day = calendar.startOfDay(for: now)
        if let value, self.activities == activities, self.calendar == calendar, today == day, self.locale == locale { return value }
        let next = TodayActivitySnapshot(activities: activities, calendar: calendar, today: day, locale: locale)
        self.activities = activities; self.calendar = calendar; today = day; self.locale = locale; value = next
        generation += 1
        return next
    }
}
