import AppKit
import SwiftUI
import os

/// Handler entry -> native draw. Does not measure physical display scanout or
/// time spent delivering an OS/AX input event. Compiled out of the daily app.
@MainActor
enum NavigationPerformance {
#if PERFORMANCE_QA
    static let navigate = Notification.Name("ReviewTodayPerformanceNavigation")
    static let menu = Notification.Name("ReviewTodayPerformanceMenu")
    static var rows: [[String: Any]] = []
    static var pending: (id: String, start: TimeInterval, feedback: Double?, page: Double?)?
    static var completed = 0
    static var activationRows: [[String: Any]] = []
    private static let log = OSLog(subsystem: "ReviewToday.PerformanceQA", category: .pointsOfInterest)
    static func begin(_ id: String) {
        pending = (id, ProcessInfo.processInfo.systemUptime, nil, nil)
        os_signpost(.begin, log: log, name: "Navigation", "%{public}s", id)
    }
    static func painted(_ id: String, stage: String) {
        guard var p = pending, p.id == id else { return }
        let ms = (ProcessInfo.processInfo.systemUptime - p.start) * 1000
        if stage == "feedback" { p.feedback = p.feedback ?? ms } else { p.page = p.page ?? ms }
        pending = p
        guard let page = p.page, p.feedback != nil || id.hasPrefix("menu:") else { return }
        rows.append(["destination": id, "page_draw_ms": page, "feedback_draw_ms": p.feedback.map { $0 as Any } ?? NSNull(),
                     "app_active": NSApp.isActive, "time": Date.now.timeIntervalSince1970])
        pending = nil
        completed += 1
        os_signpost(.end, log: log, name: "Navigation")
    }
#else
    static func begin(_ id: String) {}
#endif
}

extension View {
    @ViewBuilder func navigationPaintProbe(_ id: String, stage: String) -> some View {
#if PERFORMANCE_QA
        background(NavigationPaintProbe(id: id, stage: stage).allowsHitTesting(false).accessibilityHidden(true))
#else
        self
#endif
    }
}

#if PERFORMANCE_QA
/// A separate window probe records activation notification -> next native draw.
/// This is not the OS app-switch event delivery or full display scanout time.
struct ActivationPaintProbe: NSViewRepresentable {
    func makeNSView(context: Context) -> Probe { Probe() }
    func updateNSView(_ view: Probe, context: Context) {}
    final class Probe: NSView {
        private var observer: NSObjectProtocol?
        private var started: TimeInterval?
        override init(frame: NSRect) {
            super.init(frame: frame)
            observer = NotificationCenter.default.addObserver(forName: NSApplication.didBecomeActiveNotification,
                object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated {
                    self?.started = ProcessInfo.processInfo.systemUptime
                    self?.needsDisplay = true
                }
            }
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
        deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func draw(_ dirtyRect: NSRect) {
            guard let started else { return }
            NavigationPerformance.activationRows.append(["activation_draw_ms": (ProcessInfo.processInfo.systemUptime - started) * 1000,
                "app_active": NSApp.isActive, "time": Date.now.timeIntervalSince1970])
            self.started = nil
        }
    }
}

private struct NavigationPaintProbe: NSViewRepresentable {
    let id: String
    let stage: String
    func makeNSView(context: Context) -> Probe { Probe() }
    func updateNSView(_ view: Probe, context: Context) {
        view.identity = id; view.stage = stage; view.needsDisplay = true
    }
    final class Probe: NSView {
        var identity = ""
        var stage = ""
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func draw(_ dirtyRect: NSRect) { NavigationPerformance.painted(identity, stage: stage) }
    }
}
#endif
