import AppKit
import SwiftUI
import SwiftData
import Observation
import QuartzCore

@Observable private final class NavigationState {
    var page = 0
    var archived = false
    var sessionID = UUID()
}
private struct SessionStatusHost: View {
    let state: NavigationState
    var body: some View {
        HStack {
            Text("Page \(state.page)")
            SessionActivityStatus(sessionID: state.sessionID, archived: state.archived)
        }
    }
}
private struct PageArrivalHost: View {
    let state: NavigationState
    var body: some View {
        // Keep the surface outside the changing page, as in ContentView.
        ZStack {
            if state.page == 0 { Text("今天") }
            else { Button("Agent 输入可用") {} }
        }
        .overlay(PageArrivalFade(page: state.page == 0 ? .today : .learning)
            .allowsHitTesting(false).accessibilityHidden(true))
        .environment(\.scenePhase, .active)
        .environment(\.brandTrialStill, state.archived)
    }
}
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
        try sessionStatusObservation()
        try pageArrival()
        try pageArrivalHosting()
        print("PASS: native date buttons, exact actions, disabled/future accessibility, compact geometry, reused targets, single-set composer layout")
    }

    @MainActor static func pageArrivalHosting() throws {
        let state = NavigationState()
        let host = NSHostingView(rootView: PageArrivalHost(state: state))
        host.frame = NSRect(x: 0, y: 0, width: 320, height: 100)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = host
        defer { window.close() }
        func settle() {
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date.now.addingTimeInterval(0.025))
            host.layoutSubtreeIfNeeded()
        }
        func surface(_ view: NSView) -> PageArrivalFade.Surface? {
            if let view = view as? PageArrivalFade.Surface { return view }
            return view.subviews.lazy.compactMap { surface($0) }.first
        }
        settle()
        let fade = surface(host)!
        let key = PageArrivalFade.Surface.animationKey
        precondition(fade.layer?.animation(forKey: key) == nil)
        state.page = 1; settle()
        precondition(surface(host) === fade, "the arrival surface must survive replacement of the business page")
        precondition(fade.layer?.animation(forKey: key) != nil, "real SwiftUI navigation must start the fade")
        state.archived = true; settle()
        precondition(fade.layer?.animation(forKey: key) == nil, "live Reduce Motion changes must cancel the fade")
        state.page = 0; settle()
        precondition(surface(host) === fade && fade.layer?.animation(forKey: key) == nil)
        print("PASS: real SwiftUI page replacement retains one fade surface and respects live Reduce Motion")
    }

    @MainActor static func pageArrival() throws {
        let base = NSView(frame: NSRect(x: 0, y: 0, width: 320, height: 100))
        let button = NSButton(frame: NSRect(x: 20, y: 20, width: 100, height: 30))
        button.title = "立即操作"
        base.addSubview(button)
        let fade = PageArrivalFade.Surface(frame: base.bounds)
        base.addSubview(fade)
        let window = NSWindow(contentRect: base.bounds, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.contentView = base
        defer { window.close() }
        let key = PageArrivalFade.Surface.animationKey
        fade.update(page: .today, color: .white, enabled: true)
        precondition(fade.layer?.animation(forKey: key) == nil, "initial display must not fade")
        fade.update(page: .learning, color: .white, enabled: true)
        let animation = fade.layer?.animation(forKey: key) as? CABasicAnimation
        precondition(animation?.duration == 0.12 && animation?.keyPath == "opacity")
        precondition(fade.layer?.opacity == 0, "final model opacity must never obscure the page")
        precondition(fade.hitTest(NSPoint(x: 30, y: 30)) == nil && !fade.acceptsFirstResponder)
        precondition(base.hitTest(NSPoint(x: 30, y: 30)) === button, "input must reach the underlying control during the fade")
        precondition(!fade.isAccessibilityElement(), "decorative arrival layer must not create a focus stop")
        fade.update(page: .library, color: .white, enabled: true)
        precondition(fade.layer?.animation(forKey: key) == nil, "rapid navigation must stop rather than queue the previous animation")
        fade.update(page: .inbox, color: .black, enabled: false)
        precondition(fade.layer?.animation(forKey: key) == nil)
        fade.update(page: .inbox, color: .black, enabled: true)
        precondition(fade.layer?.animation(forKey: key) == nil, "restoring motion or foreground must not replay the page")
        RunLoop.main.run(until: Date.now.addingTimeInterval(0.15))
        fade.update(page: .today, color: .black, enabled: true)
        precondition(fade.layer?.animation(forKey: key) != nil)
        NotificationCenter.default.post(name: NSWindow.didResignKeyNotification, object: window)
        precondition(fade.layer?.animation(forKey: key) == nil, "window deactivation must settle immediately")
        precondition(fade.layer?.opacity == 0 && base.subviews.count == 2)
        print("PASS: arrival fade, no initial/same-page replay, direct hit testing, rapid interruption, reduced motion, dark canvas and window deactivation")
    }

    @MainActor static func sessionStatusObservation() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let state = NavigationState()
        let session = AgentSession(title: "Status fixture")
        state.sessionID = session.id
        context.insert(session); try context.save()
        var renders = 0
        var symbol = "", label = ""
        SessionStatusDiagnostics.didRender = { _, nextSymbol, nextLabel in
            renders += 1; symbol = nextSymbol; label = nextLabel
        }
        defer { SessionStatusDiagnostics.didRender = nil }
        let host = NSHostingView(rootView: SessionStatusHost(state: state).modelContainer(container))
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
        precondition(renders > 0 && label == "尚未运行")
        let before = renders
        for index in 1...10 { state.page = index; settle() }
        precondition(renders == before, "navigation identity changes must not read status queries")
        let run = AgentRun(id: UUID(), sessionID: session.id)
        run.status = "running"; run.userSummary = "Working"
        context.insert(run); try context.save(); settle()
        precondition(symbol == "circle.dotted" && label == "Working", "inserted run must appear through the stable identity boundary")
        run.status = "retryable_failed"; try context.save(); settle()
        precondition(symbol == "exclamationmark.triangle", "existing run edits must independently refresh")
        run.status = "completed"
        let task = LearningTask(sessionID: session.id, inputMessageID: UUID())
        task.status = "awaiting_user"; task.requiredActionType = "submit_answer"
        context.insert(task); try context.save(); settle()
        precondition(symbol == "bubble.left" && label == "等待作答")
        task.requiredActionType = "continue"; try context.save(); settle()
        precondition(label == "可继续学习")
        let newer = AgentRun(id: UUID(), sessionID: session.id)
        newer.status = "cancelled"; newer.updatedAt = run.updatedAt.addingTimeInterval(10)
        context.insert(newer); try context.save(); settle()
        precondition(symbol == "pause.circle", "newest record must replace the previous one")
        run.updatedAt = newer.updatedAt.addingTimeInterval(10)
        run.status = "running"; try context.save(); settle()
        precondition(symbol == "circle.dotted", "updated ordering must change the displayed latest run")
        context.delete(run); try context.save(); settle()
        precondition(symbol == "pause.circle", "deleting the latest record must reveal its predecessor")
        state.archived = true; settle()
        precondition(symbol == "archivebox")
        state.archived = false; state.sessionID = UUID(); settle()
        precondition(label == "尚未运行", "a reused row must not retain another session's status")
        print("PASS: navigation skips status queries; inserts, edits, task actions, ordering, deletion, archive and session changes remain live")
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
