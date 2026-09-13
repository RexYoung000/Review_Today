import Combine
import SwiftData
import SwiftUI

enum ReviewHistoryMaintenance {
    @discardableResult
    static func backfillDates(context: ModelContext) throws -> Int {
        let pending = try context.fetch(FetchDescriptor<ReviewAttempt>(predicate: #Predicate {
            $0.mode != "preview" && $0.acked && $0.effectiveGrade != "" && $0.completedAt == nil
        }))
        guard !pending.isEmpty else { return 0 }
        let reviews = Dictionary(try context.fetch(FetchDescriptor<ReviewSession>()).map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var changed: [ReviewAttempt] = []
        for row in pending {
            guard let review = reviews[row.sessionId] else { continue }
            row.completedAt = review.endedAt ?? review.startedAt
            changed.append(row)
        }
        if !changed.isEmpty {
            do { try context.save() }
            catch { for row in changed { row.completedAt = nil }; throw error }
        }
        return changed.count
    }
}

/// Root-owned work: changing pages neither re-requests permission nor rewrites
/// the same scheduled notification. The minute clock also notices due times.
struct ReviewMaintenance: View {
    @Environment(\.modelContext) private var context
    @Query private var settingsRows: [AppSettings]
    @Query private var knowledge: [Knowledge]
    @State private var now = Date.now
    private let minute = Timer.publish(every: 60, on: .main, in: .common).autoconnect()
    private struct Schedule: Equatable {
        let day: String
        let minute: Int
        let hasDue: Bool
        let skipped: Bool
    }
    private var schedule: Schedule {
        let settings = settingsRows.first
        let day = Calendar.current.startOfDay(for: now).description
        return Schedule(day: day, minute: settings?.dailyReminderMinutes ?? 1260,
            hasDue: knowledge.contains { ReviewQueue.isDue($0, developerMode: settings?.developerMode == true) },
            skipped: settings?.skipToday == TodayView.todayStamp())
    }
    var body: some View {
        Color.clear.frame(width: 0, height: 0).accessibilityHidden(true)
            .onReceive(minute) { now = $0 }
            .onReceive(NotificationCenter.default.publisher(for: .NSSystemTimeZoneDidChange)) { _ in now = .now }
            .onChange(of: schedule, initial: true) { _, value in
                guard AppRuntime.current.mode == .normal else { return }
                ReminderNotifications.request()
                ReminderNotifications.scheduleDaily(minuteOfDay: value.minute, hasDue: value.hasDue, skippedToday: value.skipped)
            }
            .task {
                await Task.yield()
                do { try ReviewHistoryMaintenance.backfillDates(context: context) }
                catch { NSLog("Review date backfill deferred: %@", String(describing: error)) }
            }
    }
}
