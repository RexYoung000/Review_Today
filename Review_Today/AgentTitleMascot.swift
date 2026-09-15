import AppKit
import SwiftUI
import WebKit

/// Local presentation input only. Pointer updates bypass the learning view's state.
@MainActor
final class AgentTitleMascotDriver {
    weak var renderer: MascotWebSurface.Coordinator?
    weak var anchor: NSView?
    private var pendingPointer: [String: Any]?
    private var pendingAction: [String: Any]?
    private var sending = false
    private var scheduled: Task<Void, Never>?
    private var lastSend = -Double.infinity

    func preservesInputFocus(_ event: NSEvent) -> Bool {
        guard event.type == .leftMouseDown, let anchor, anchor.window === event.window,
              !anchor.isHiddenOrHasHiddenAncestor, renderer?.ready == true else { return false }
        let point = anchor.convert(event.locationInWindow, from: nil)
        guard anchor.visibleRect.contains(point) else { return false }
        let dx = (point.x - anchor.bounds.midX) / 38
        let dy = (point.y - anchor.bounds.midY) / 31
        return dx * dx + dy * dy <= 1
    }

    func pointer(_ point: NSPoint, in region: NSView) {
        guard let anchor, anchor.window === region.window else { return }
        let center = anchor.convert(NSPoint(x: anchor.bounds.midX, y: anchor.bounds.midY), to: region)
        let direction: CGFloat = region.isFlipped ? -1 : 1
        pendingPointer = ["type": "pointer", "x": max(-1, min(1, (point.x - center.x) / 220)),
                          "y": max(-1, min(1, (point.y - center.y) * direction / 160))]
        drain()
    }

    func action(_ type: String) {
        if type != "poke" { pendingPointer = nil }
        pendingAction = ["type": type]
        drain()
    }

    private func drain() {
        guard !sending, let renderer, renderer.ready, let web = renderer.webView else {
            if renderer?.ready != true { pendingPointer = nil; pendingAction = nil }
            return
        }
        guard let input = pendingAction ?? pendingPointer else { return }
        let delay = 1.0 / 60 - (ProcessInfo.processInfo.systemUptime - lastSend)
        if delay > 0 {
            if scheduled == nil {
                scheduled = Task { @MainActor [weak self] in
                    try? await Task.sleep(for: .seconds(delay))
                    guard !Task.isCancelled else { return }
                    self?.scheduled = nil; self?.drain()
                }
            }
            return
        }
        if pendingAction != nil { pendingAction = nil } else { pendingPointer = nil }
        sending = true
        lastSend = ProcessInfo.processInfo.systemUptime
        web.callAsyncJavaScript("window.mascotMotion.headerInput(input)", arguments: ["input": input], in: nil, in: .page) { [weak self] _ in
            guard let self else { return }
            self.sending = false
            self.drain()
        }
    }

    func detach() {
        scheduled?.cancel(); scheduled = nil
        pendingPointer = nil; pendingAction = nil
        renderer = nil; anchor = nil
    }
}

struct AgentLandingTitle: View {
    let driver: AgentTitleMascotDriver
    @Environment(\.runway) private var runway
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.brandReduceMotion) private var reduced
    @State private var ready = false
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 6) {
            ZStack {
                AgentTitleMascotRenderer(driver: driver, configuration: .init(
                    reduced: reduced, dark: colorScheme == .dark, header: true,
                    material: "graphite", palette: .theme(dark: colorScheme == .dark)
                ), onReady: { ready = $0 })
                .accessibilityHidden(true)
                Button { driver.action("poke") } label: {
                    Color.clear.contentShape(Ellipse())
                }
                .buttonStyle(TitleMascotButtonStyle())
                .frame(width: 76, height: 62)
                .focusable(interactions: .activate).focusEffectDisabled().focused($focused)
                .overlay {
                    if focused { RoundedRectangle(cornerRadius: 14).stroke(runway.ink.opacity(0.45), lineWidth: 2).allowsHitTesting(false) }
                }
                .disabled(!ready)
                .accessibilityLabel("和 Mr. B 打个招呼")
            }
            .frame(width: 92, height: 74)
            VStack(alignment: .center, spacing: 6) {
                Text("Review Today").font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(runway.ink).lineLimit(1).minimumScaleFactor(0.8)
                Text("从一个问题开始，把理解留住。").font(.callout).foregroundStyle(.secondary)
            }
            .layoutPriority(1)
            // Match the decoration's width so the text owns the content centerline.
            Color.clear.frame(width: 92, height: 1)
                .allowsHitTesting(false).accessibilityHidden(true)
        }
        .multilineTextAlignment(.center)
        .fixedSize(horizontal: false, vertical: true)
    }
}

private struct TitleMascotButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.background(Ellipse().fill(Color.primary.opacity(configuration.isPressed ? 0.07 : 0)))
    }
}

private struct AgentTitleMascotRenderer: NSViewRepresentable {
    let driver: AgentTitleMascotDriver
    let configuration: MascotMotionConfiguration
    var onReady: (Bool) -> Void
    func makeCoordinator() -> MascotWebSurface.Coordinator { .init(onReady: onReady) }
    func makeNSView(context: Context) -> PassiveMascotWebView {
        let view = context.coordinator.makeView(configuration: configuration)
        driver.renderer = context.coordinator; driver.anchor = view
        return view
    }
    func updateNSView(_ view: PassiveMascotWebView, context: Context) {
        context.coordinator.onReady = onReady
        context.coordinator.configuration = configuration
        context.coordinator.send()
    }
    static func dismantleNSView(_ view: PassiveMascotWebView, coordinator: MascotWebSurface.Coordinator) {
        coordinator.release(view)
    }
}

/// The tracking rectangle is the main content region, excluding the sidebar.
/// Never consumes events, requests global input access, or reads typed text.
struct AgentTitlePointerRegion: NSViewRepresentable {
    let driver: AgentTitleMascotDriver
    func makeNSView(context: Context) -> RegionView { RegionView(driver: driver) }
    func updateNSView(_ view: RegionView, context: Context) {}
    static func dismantleNSView(_ view: RegionView, coordinator: ()) { view.dispose(); view.driver.detach() }

    final class RegionView: NSView {
        let driver: AgentTitleMascotDriver
        private var tracking: NSTrackingArea?
        private var monitor: Any?
        private weak var trackedWindow: NSWindow?
        private var previousMouseMoved = false
        private var observers: [NSObjectProtocol] = []
        init(driver: AgentTitleMascotDriver) { self.driver = driver; super.init(frame: .zero) }
        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override var acceptsFirstResponder: Bool { false }
        override func updateTrackingAreas() {
            super.updateTrackingAreas()
            if let tracking { removeTrackingArea(tracking) }
            let area = NSTrackingArea(rect: .zero, options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect], owner: self)
            addTrackingArea(area); tracking = area
        }
        override func mouseExited(with event: NSEvent) { driver.action("quiet") }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow(); dispose()
            guard let window else { return }
            trackedWindow = window
            previousMouseMoved = window.acceptsMouseMovedEvents
            window.acceptsMouseMovedEvents = true
            monitor = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .keyDown]) { [weak self] event in
                MainActor.assumeIsolated { self?.observe(event) }
                return event
            }
            for name in [NSWindow.didResignKeyNotification, NSWindow.didResizeNotification,
                         NSWindow.didMiniaturizeNotification, NSApplication.didResignActiveNotification] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                    MainActor.assumeIsolated {
                        guard let self else { return }
                        if let changed = note.object as? NSWindow, changed !== self.window { return }
                        self.driver.action("reset")
                    }
                })
            }
        }
        private func observe(_ event: NSEvent) {
            guard let window, window === event.window, window.isKeyWindow, NSApp.isActive,
                  window.attachedSheet == nil, !isHiddenOrHasHiddenAncestor else { return }
            if event.type == .keyDown {
                if window.firstResponder is NSTextView { driver.action("quiet") }
                return
            }
            let point = convert(event.locationInWindow, from: nil)
            if visibleRect.contains(point) { driver.pointer(point, in: self) }
            else { driver.action("quiet") }
        }
        func dispose() {
            if let trackedWindow { trackedWindow.acceptsMouseMovedEvents = previousMouseMoved }
            trackedWindow = nil
            if let monitor { NSEvent.removeMonitor(monitor); self.monitor = nil }
            observers.forEach(NotificationCenter.default.removeObserver); observers.removeAll()
            driver.action("reset")
        }
    }
}
