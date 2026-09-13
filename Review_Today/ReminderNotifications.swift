import Foundation
import UserNotifications

enum ReminderNotifications {
    static let category = "RT_DAILY_REVIEW"
    private static var requested = false

    static func request() {
        guard !requested, AppRuntime.current.mode == .normal else { return }
        requested = true
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        let start = UNNotificationAction(identifier: "start", title: String(localized: "现在开始"))
        let later15 = UNNotificationAction(identifier: "later15", title: String(localized: "15 分钟后"))
        let later60 = UNNotificationAction(identifier: "later60", title: String(localized: "1 小时后"))
        let skip = UNNotificationAction(identifier: "skip", title: String(localized: "今日跳过"))
        let category = UNNotificationCategory(
            identifier: Self.category,
            actions: [start, later15, later60, skip],
            intentIdentifiers: []
        )
        UNUserNotificationCenter.current().setNotificationCategories([category])
    }

    static func scheduleDaily(minuteOfDay: Int, hasDue: Bool, skippedToday: Bool) {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: ["rt.daily"])
        guard hasDue, !skippedToday else { return }
        var date = DateComponents()
        date.hour = minuteOfDay / 60
        date.minute = minuteOfDay % 60
        let content = UNMutableNotificationContent()
        content.title = String(localized: "Review Today")
        content.body = String(localized: "今天有到期的知识点可以复习。")
        content.categoryIdentifier = category
        let trigger = UNCalendarNotificationTrigger(dateMatching: date, repeats: true)
        let request = UNNotificationRequest(identifier: "rt.daily", content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(request)
    }

    static func snooze(minutes: Int) {
        let content = UNMutableNotificationContent()
        content.title = String(localized: "Review Today")
        content.body = String(localized: "可以开始复习了。")
        content.categoryIdentifier = category
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: TimeInterval(minutes * 60), repeats: false)
        let request = UNNotificationRequest(identifier: "rt.snooze.\(minutes)", content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(request)
    }
}
