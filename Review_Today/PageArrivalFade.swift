import AppKit
import SwiftUI
import QuartzCore

/// A light arrival fade without retaining an outgoing page or animating its
/// layout. The content is already readable and interactive on the first frame.
struct PageArrivalFade: NSViewRepresentable {
    let page: SidebarItem
    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.scenePhase) private var phase

    func makeNSView(context: Context) -> Surface { Surface() }
    func updateNSView(_ view: Surface, context: Context) {
        view.update(page: page, color: NSColor(runway.canvas), enabled: !reduced && phase == .active)
    }
    static func dismantleNSView(_ view: Surface, coordinator: ()) { view.clear() }

    final class Surface: NSView {
        static let duration: TimeInterval = 0.12
        static let animationKey = "pageArrival"
        private var page: SidebarItem?
        private var lastChange: TimeInterval?
        private var inactiveObserver: NSObjectProtocol?

        override init(frame: NSRect) {
            super.init(frame: frame)
            wantsLayer = true
            layer?.opacity = 0
            setAccessibilityElement(false)
            setAccessibilityHidden(true)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override var acceptsFirstResponder: Bool { false }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let inactiveObserver { NotificationCenter.default.removeObserver(inactiveObserver) }
            inactiveObserver = nil
            clear()
            if let window {
                inactiveObserver = NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification,
                    object: window, queue: .main) { [weak self] _ in
                        MainActor.assumeIsolated { self?.clear() }
                    }
            }
        }
        deinit { if let inactiveObserver { NotificationCenter.default.removeObserver(inactiveObserver) } }

        func clear() { layer?.removeAnimation(forKey: Self.animationKey) }

        func update(page next: SidebarItem, color: NSColor, enabled: Bool) {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            layer?.backgroundColor = color.cgColor
            CATransaction.commit()
            let previous = page
            page = next
            guard enabled else { clear(); return }
            guard let previous, previous != next else { return }
            let now = ProcessInfo.processInfo.systemUptime
            let repeated = lastChange.map { now - $0 < Self.duration } ?? false
            lastChange = now
            clear()
            guard !repeated else { return }
            let animation = CABasicAnimation(keyPath: "opacity")
            animation.fromValue = 0.16
            animation.toValue = 0
            animation.duration = Self.duration
            animation.timingFunction = CAMediaTimingFunction(name: .easeOut)
            layer?.add(animation, forKey: Self.animationKey)
        }
    }
}
