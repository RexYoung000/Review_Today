import AppKit
import SwiftUI
import SwiftData
import Observation

@Observable private final class NavigationState { var page = 0 }
private struct ActivitySourceHost: View {
    let state: NavigationState
    let cache: TodayActivityCache
    var body: some View {
        Text("Page \(state.page)")
            .background(TodayActivitySource(cache: cache))
    }
}

@main
struct NavigationRenderContractTests {
    @MainActor static func main() throws {
        _ = NSApplication.shared
        let calendar = Calendar(identifier: .gregorian)
        let today = calendar.startOfDay(for: .now)
        let item = TodayActivity(id: "run-A", date: today, kind: "lesson_step", title: "A")
        let snapshot = TodayActivitySnapshot(activities: [item], calendar: calendar, today: today, locale: Locale(identifier: "zh_CN"))
        let view = ActivityDayGrid.Grid()
        var selected: Date?
        let colors: [NSColor] = [.white, .gray, .darkGray, .black, .blue]
        view.update(days: snapshot.days, size: 16, spacing: 5, colors: colors, border: .gray) { selected = $0 }
        precondition(view.buttons.count == 182)
        precondition(view.buttons[7].frame.origin == NSPoint(x: 21, y: 0))
        precondition(view.buttons[6].frame.origin == NSPoint(x: 0, y: 126))
        let index = snapshot.days.firstIndex { $0.date == today }!
        let button = view.buttons[index]
        precondition(button.isEnabled && button.accessibilityRole() == .button)
        precondition(button.toolTip == snapshot.days[index].help && button.accessibilityLabel() == snapshot.days[index].help)
        button.performClick(nil)
        precondition(selected == today, "date activation must preserve the precise source date")
        selected = nil
        let empty = view.buttons.first { !$0.isEnabled }!
        empty.performClick(nil)
        precondition(selected == nil, "empty dates cannot open details")
        let other = calendar.date(byAdding: .day, value: -1, to: today)!
        let next = TodayActivitySnapshot(activities: [TodayActivity(id: "run-B", date: other, kind: "knowledge_answer", title: "B")], calendar: calendar, today: today, locale: Locale(identifier: "en_US"))
        view.update(days: next.days, size: 12, spacing: 4, colors: Array(colors.reversed()), border: .black) { selected = $0 }
        precondition(view.buttons[index] === button && !button.isEnabled)
        precondition(view.buttons[7].frame.origin == NSPoint(x: 16, y: 0))
        let nextButton = view.buttons[next.days.firstIndex { $0.date == other }!]
        nextButton.performClick(nil)
        precondition(selected == other && nextButton.toolTip!.contains("知识回答 1"), "reused buttons cannot retain old dates or tooltips")
        let sizes = [CGSize(width: 160, height: 24), CGSize(width: 28, height: 28)]
        precondition(ComposerControlsLayout.size(sizes, available: 192) == CGSize(width: 192, height: 28))
        precondition(ComposerControlsLayout.size(sizes, available: 180) == CGSize(width: 160, height: 54))
        try activityObservation()
        print("PASS: native date buttons, exact actions, disabled/future accessibility, compact geometry, reused targets, single-set composer layout")
    }

    @MainActor static func activityObservation() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let session = AgentSession(title: "Before")
        context.insert(session); try context.save()
        let cache = TodayActivityCache(), state = NavigationState()
        let host = NSHostingView(rootView: ActivitySourceHost(state: state, cache: cache).modelContainer(container))
        host.frame = NSRect(x: 0, y: 0, width: 320, height: 100)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host
        defer { window.close() }
        func settle() {
            let deadline = Date.now.addingTimeInterval(0.2)
            while Date.now < deadline {
                host.layoutSubtreeIfNeeded()
                RunLoop.main.run(until: Date.now.addingTimeInterval(0.01))
            }
        }
        settle()
        let before = cache.sourceProjectionCount
        precondition(before > 0)
        for index in 1...10 { state.page = index; settle() }
        precondition(cache.sourceProjectionCount == before, "parent navigation must not re-read all activity models")
        session.composerDraft = "Unrelated draft"; try context.save(); settle()
        precondition(cache.sourceProjectionCount == before, "draft-only saves must not re-read activity")
        let run = AgentRun(id: UUID(), sessionID: session.id)
        run.status = "completed"; run.activityKind = "lesson_step"; run.completedAt = .now
        context.insert(run); try context.save(); settle()
        precondition(cache.sourceActivities.count == 1 && cache.sourceActivities[0].title == "Before", "source must observe inserted activity")
        session.title = "After"; try context.save(); settle()
        precondition(cache.sourceActivities.first?.title == "After", "source must observe model edits without navigation")
        context.delete(run); try context.save(); settle()
        precondition(cache.sourceActivities.isEmpty, "source must observe activity deletion")
        let pending = AgentRun(id: UUID(), sessionID: session.id)
        pending.status = "running"; context.insert(pending); try context.save(); settle()
        precondition(cache.sourceActivities.isEmpty)
        pending.status = "completed"; pending.activityKind = "knowledge_answer"; pending.completedAt = .now
        try context.save(); settle()
        precondition(cache.sourceActivities.count == 1, "a newly eligible run must enter the source")
        let projected = cache.sourceProjectionCount
        session.composerDraft = "Another draft"; try context.save(); settle()
        precondition(cache.sourceProjectionCount == projected, "draft-only save must not refresh a populated source")
        context.autosaveEnabled = false
        let savedTitle = session.title
        session.title = "Unsaved title"; settle()
        precondition(cache.sourceActivities.first?.title == "Unsaved title", "relevant live model edits must still refresh")
        precondition(context.hasChanges, "rollback fixture must retain an unsaved edit")
        // SwiftData rollback does not restore already observed model fields.
        // Match the app's transaction recovery: roll back and restore the value.
        context.rollback(); session.title = savedTitle; settle()
        precondition(cache.sourceActivities.first?.title == savedTitle, "explicit recovery of model fields must refresh the projection")
        print("PASS: real SwiftUI navigation and draft saves skip projection; insert, rename, delete, completion and explicit recovery still refresh")
    }
}
