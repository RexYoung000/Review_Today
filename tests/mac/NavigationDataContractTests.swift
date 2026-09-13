import Foundation
import SwiftData
import SwiftUI

@main
struct NavigationDataContractTests {
    enum Disk: Error { case failed }
    @MainActor static func main() throws {
        try drafts()
        try historyAndWork()
        calendar()
        print("PASS: unchanged/failed/retried/deleted drafts, date backfill, scoped sync work, activity identity/history/DST/timezone/cache invalidation")
    }
    static func require(_ value: @autoclosure () throws -> Bool) rethrows { let result = try value(); precondition(result) }
    @MainActor static func drafts() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let settings = try AgentComposerStore.prepare(context)
        let a = AgentSession(title: "A"), b = AgentSession(title: "B")
        context.insert(a); context.insert(b); try context.save()
        let store = LearningDraftStore()
        var saves = 0
        let save = { saves += 1; try context.save() }
        try store.save("", sessionID: nil, context: context, save: save)
        try store.save("", sessionID: a.id, context: context, save: save)
        precondition(saves == 0, "visiting unchanged editors must not commit the context")
        do { try store.save("中文预输入后保留的草稿", sessionID: a.id, context: context, save: { throw Disk.failed }); preconditionFailure() }
        catch Disk.failed {}
        precondition(store.unsavedText(sessionID: a.id) == "中文预输入后保留的草稿")
        try store.save("B 草稿", sessionID: b.id, context: context, save: save)
        try store.save("中文预输入后保留的草稿", sessionID: a.id, context: context, save: save)
        precondition(saves == 2 && store.unsavedText(sessionID: a.id) == nil)
        let fresh = ModelContext(container)
        try require(fresh.fetch(FetchDescriptor<AgentSession>()).contains { $0.id == a.id && $0.composerDraft == "中文预输入后保留的草稿" })
        try store.save("起始页草稿", sessionID: nil, context: context, save: save)
        precondition(settings.agentDraftText == "起始页草稿" && b.composerDraft == "B 草稿")
        let deleted = a.id; context.delete(a); try context.save()
        try require(!store.save("迟到的旧稿", sessionID: deleted, context: context, save: save))
        precondition(settings.agentDraftText == "起始页草稿")
    }
    @MainActor static func historyAndWork() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let c = container.mainContext
        let empty = AgentSession(title: "empty"), active = AgentSession(title: "active")
        c.insert(empty); c.insert(active)
        let message = AgentMessage(sessionID: active.id, role: "user", content: "本地待发")
        c.insert(message)
        let run = AgentRun(id: UUID(), sessionID: active.id); c.insert(run)
        let control = AgentRunControl(runID: run.id, sessionID: active.id, action: "stop"); c.insert(control)
        let review = ReviewSession(mode: "formal", snapshotJSON: "[]"); c.insert(review)
        let attempt = ReviewAttempt(sessionId: review.id, knowledgeId: UUID(), knowledgeVersion: 1, questionId: UUID(), mode: "formal")
        attempt.acked = true; attempt.effectiveGrade = "good"; c.insert(attempt)
        try c.save()
        let work = try ConversationWorkSnapshot(context: c)
        precondition(!work.hasWorkHistory(empty) && !work.needsControl(empty))
        precondition(work.needsControl(active) && work.messagesBySession[active.id]?.first?.id == message.id)
        precondition(work.controlsBySession[empty.id] == nil && work.runsBySession[active.id]?.first?.id == run.id)
        try require(ReviewHistoryMaintenance.backfillDates(context: c) == 1)
        precondition(attempt.completedAt == review.startedAt)
        try require(ReviewHistoryMaintenance.backfillDates(context: c) == 0)
    }
    static func calendar() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/Los_Angeles")!; cal.firstWeekday = 2
        let now = cal.date(from: DateComponents(year: 2026, month: 3, day: 9, hour: 12))!
        let yesterday = cal.date(byAdding: .day, value: -1, to: now)!
        let older = cal.date(byAdding: .day, value: -250, to: now)!
        let rows = [TodayActivity(id: "1", date: now, kind: "lesson_step", title: "今天"),
                    TodayActivity(id: "2", date: yesterday, kind: "formal_review", title: "昨天"),
                    TodayActivity(id: "3", date: older, kind: "knowledge_answer", title: "旧历史")]
        let cache = TodayActivityCache(), locale = Locale(identifier: "zh_CN")
        let first = cache.snapshot(activities: rows + [rows[0]], calendar: cal, now: now, locale: locale)
        precondition(first.days.count == 182 && first.months.count == 26)
        precondition(first.activeDays == 3 && first.currentStreak == 2 && first.longestStreak == 2)
        precondition(first.days.reduce(0) { $0 + $1.count } == 2, "all-time history is distinct from 26-week display")
        precondition(Set(first.days.map(\.date)).count == 182, "DST cannot duplicate or lose a day")
        precondition(first.days.first { $0.date == cal.startOfDay(for: now) }!.help.contains("资料学习 1"))
        _ = cache.snapshot(activities: rows + [rows[0]], calendar: cal, now: now.addingTimeInterval(1), locale: locale)
        precondition(cache.generation == 1)
        _ = cache.snapshot(activities: rows, calendar: cal, now: cal.date(byAdding: .day, value: 1, to: now)!, locale: locale)
        precondition(cache.generation == 2)
        cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        _ = cache.snapshot(activities: rows, calendar: cal, now: now, locale: locale)
        precondition(cache.generation == 3)
        let renamed = rows.dropLast() + [TodayActivity(id: "3", date: older, kind: "knowledge_answer", title: "重命名")]
        let changed = cache.snapshot(activities: Array(renamed), calendar: cal, now: now, locale: locale)
        precondition(changed.activitiesByDay[cal.startOfDay(for: older)]!.first!.title == "重命名")
    }
}
