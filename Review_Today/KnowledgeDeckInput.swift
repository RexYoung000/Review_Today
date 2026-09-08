import AppKit
import SwiftUI

struct KnowledgeDeckDragRegionKey: PreferenceKey {
    static var defaultValue: [Anchor<CGRect>] = []
    static func reduce(value: inout [Anchor<CGRect>], nextValue: () -> [Anchor<CGRect>]) {
        value.append(contentsOf: nextValue())
    }
}

extension View {
    /// Mark only non-selectable, control-free card areas, so native text selection
    /// and button gestures remain owned by their original views.
    func knowledgeDeckDragSurface() -> some View {
        anchorPreference(key: KnowledgeDeckDragRegionKey.self, value: .bounds) { [$0] }
            .help("左右拖动标题翻阅知识卡：左划下一张，右划上一张")
            .accessibilityHint("左划下一张，右划上一张，也可使用左右方向键或侧边定位条")
    }
}

struct KnowledgeDeckInputSurface: NSViewRepresentable {
    var cardFrame: CGRect
    var dragRegions: [CGRect]
    var canNavigate: Bool
    var begin: () -> Void
    var change: (CGFloat) -> Void
    var end: (CGFloat, CGFloat) -> Void
    var cancel: () -> Void
    var step: (Int) -> Void

    func makeNSView(context: Context) -> KnowledgeDeckInputView { KnowledgeDeckInputView() }

    func updateNSView(_ view: KnowledgeDeckInputView, context: Context) {
        view.cardFrame = cardFrame
        // Keep the resting title hit area while the surface is flying out. A new
        // gesture can interrupt the transition and starts from logical selection.
        if !dragRegions.isEmpty { view.dragRegions = dragRegions }
        view.canNavigate = canNavigate
        view.onBegin = begin
        view.onChange = change
        view.onEnd = end
        view.onCancel = cancel
        view.onStep = step
        view.window?.invalidateCursorRects(for: view)
    }

    static func dismantleNSView(_ view: KnowledgeDeckInputView, coordinator: ()) { view.dispose() }
}

/// Transparent, window-scoped event observer. Mouse drags must start in an
/// explicitly marked title area; wheel gestures must start inside the front card.
final class KnowledgeDeckInputView: NSView {
    var cardFrame = CGRect.zero
    var dragRegions: [CGRect] = []
    var canNavigate = false
    var onBegin: () -> Void = {}
    var onChange: (CGFloat) -> Void = { _ in }
    var onEnd: (CGFloat, CGFloat) -> Void = { _, _ in }
    var onCancel: () -> Void = {}
    var onStep: (Int) -> Void = { _ in }

    private var monitor: Any?
    private var lifecycleObservers: [NSObjectProtocol] = []
    private weak var observedWindow: NSWindow?
    private var mouseOrigin: CGPoint?
    private var mouseAxis: Axis = .undecided
    private var lastMouseTranslation: CGFloat = 0
    private var lastMouseTime: TimeInterval = 0
    private var mouseVelocity: CGFloat = 0
    private var wheelAxis: Axis = .undecided
    private var wheelTranslation: CGFloat = 0
    private var wheelY: CGFloat = 0
    private var wheelTime: TimeInterval = 0
    private var wheelLastMovementTime: TimeInterval = 0
    private var wheelVelocity: CGFloat = 0
    private var wheelHasPhase = false
    private var wheelFinish: DispatchWorkItem?
    private var swallowMomentum = false

    private enum Axis { case undecided, horizontal, vertical }
    override var isFlipped: Bool { true }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    override func resetCursorRects() {
        guard canNavigate else { return }
        for region in dragRegions { addCursorRect(region, cursor: .openHand) }
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if observedWindow != nil, observedWindow !== window { cancelInput(deferCallback: true) }
        removeMonitor()
        removeLifecycleObservers()
        guard window != nil else { return }
        observedWindow = window
        lifecycleObservers = [
            NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification, object: window, queue: .main) { [weak self] _ in
                self?.cancelInput()
            },
            NotificationCenter.default.addObserver(forName: NSApplication.didResignActiveNotification, object: NSApplication.shared, queue: .main) { [weak self] _ in
                self?.cancelInput()
            }
        ]
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp, .scrollWheel, .keyDown]) { [weak self] event in
            guard let self else { return event }
            return self.handle(event)
        }
    }

    func dispose() {
        cancelInput(deferCallback: true)
        removeMonitor()
        removeLifecycleObservers()
    }

    override func viewDidHide() {
        super.viewDidHide()
        cancelInput(deferCallback: true)
    }

    private func cancelInput(deferCallback: Bool = false) {
        let wasInteracting = mouseOrigin != nil || wheelAxis == .horizontal
        wheelFinish?.cancel()
        wheelFinish = nil
        mouseOrigin = nil
        mouseAxis = .undecided
        lastMouseTranslation = 0
        lastMouseTime = 0
        mouseVelocity = 0
        resetWheel()
        swallowMomentum = false
        guard wasInteracting else { return }
        NSCursor.arrow.set()
        if deferCallback {
            // Teardown and visibility changes may occur inside a SwiftUI update.
            // Clear native input immediately; reconcile view state on the next turn.
            let cancel = onCancel
            DispatchQueue.main.async(execute: cancel)
        } else {
            onCancel()
        }
    }

    private func removeLifecycleObservers() {
        lifecycleObservers.forEach { NotificationCenter.default.removeObserver($0) }
        lifecycleObservers = []
        observedWindow = nil
    }

    private func removeMonitor() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
    }

    func handle(_ event: NSEvent) -> NSEvent? {
        guard canNavigate, let window, event.window === window,
              !isHiddenOrHasHiddenAncestor, window.attachedSheet == nil else { return event }

        if event.type == .keyDown {
            guard window.isKeyWindow,
                  event.modifierFlags.intersection([.command, .control, .option]).isEmpty,
                  !(window.firstResponder is NSTextView), !(window.firstResponder is NSTextField)
            else { return event }
            if event.keyCode == 123 { onStep(-1); return nil }
            if event.keyCode == 124 { onStep(1); return nil }
            return event
        }

        let point = convert(event.locationInWindow, from: nil)
        switch event.type {
        case .leftMouseDown:
            guard dragRegions.contains(where: { $0.contains(point) }) else { return event }
            mouseOrigin = point
            mouseAxis = .undecided
            lastMouseTranslation = 0
            mouseVelocity = 0
            lastMouseTime = event.timestamp
            return event
        case .leftMouseDragged:
            guard let mouseOrigin else { return event }
            let x = point.x - mouseOrigin.x
            let y = point.y - mouseOrigin.y
            if mouseAxis == .undecided, max(abs(x), abs(y)) >= 12 {
                mouseAxis = abs(x) > abs(y) * 1.25 ? .horizontal : .vertical
                if mouseAxis == .horizontal { onBegin(); NSCursor.closedHand.set() }
            }
            guard mouseAxis == .horizontal else { return event }
            mouseVelocity = (x - lastMouseTranslation) / max(0.001, event.timestamp - lastMouseTime)
            lastMouseTranslation = x
            lastMouseTime = event.timestamp
            onChange(x)
            return nil
        case .leftMouseUp:
            guard let mouseOrigin else { return event }
            self.mouseOrigin = nil
            guard mouseAxis == .horizontal else { return event }
            let velocity = event.timestamp - lastMouseTime > 0.1 ? 0 : mouseVelocity
            onEnd(point.x - mouseOrigin.x, velocity)
            mouseAxis = .undecided
            NSCursor.openHand.set()
            return nil
        case .scrollWheel:
            let beginsGesture = event.phase.contains(.began) || event.phase.contains(.mayBegin)
            if !cardFrame.contains(point) {
                // A horizontal gesture is owned by its start point. Its terminal
                // event may arrive after the pointer leaves the card; losing that
                // event would leave the deck suspended in its dragging state.
                guard wheelAxis == .horizontal, !beginsGesture else {
                    if wheelAxis == .horizontal { cancelInput() }
                    return event
                }
            }
            return handleWheel(event)
        default:
            return event
        }
    }

    private func handleWheel(_ event: NSEvent) -> NSEvent? {
        if !event.momentumPhase.isEmpty {
            // Momentum belongs to the already completed gesture, never a second card.
            return swallowMomentum ? nil : event
        }
        if event.phase.contains(.began) || event.phase.contains(.mayBegin) {
            finishWheel(at: event.timestamp)
            resetWheel()
            swallowMomentum = false
        }
        if !event.phase.isEmpty { wheelHasPhase = true }
        let multiplier: CGFloat = event.hasPreciseScrollingDeltas ? 2 : 24
        let x = event.scrollingDeltaX * multiplier
        let y = event.scrollingDeltaY * multiplier
        wheelTranslation += x
        wheelY += y
        if wheelAxis == .undecided, max(abs(wheelTranslation), abs(wheelY)) >= 6 {
            wheelAxis = abs(wheelTranslation) > abs(wheelY) * 1.25 ? .horizontal : .vertical
            if wheelAxis == .horizontal { onBegin() }
        }
        if wheelAxis == .horizontal {
            if x != 0 {
                let interval = wheelTime > 0 ? max(0.008, event.timestamp - wheelTime) : 0.016
                wheelVelocity = x / interval
                wheelLastMovementTime = event.timestamp
            }
            onChange(wheelTranslation)
        }
        wheelTime = event.timestamp
        let consumed = wheelAxis == .horizontal
        wheelFinish?.cancel()
        if event.phase.contains(.ended) || event.phase.contains(.cancelled) {
            swallowMomentum = consumed
            if event.phase.contains(.cancelled) { wheelTranslation = 0; wheelVelocity = 0 }
            finishWheel(at: event.timestamp)
        } else if !wheelHasPhase {
            // A finger can pause without ending a trackpad gesture. Only devices
            // that provide no phase need a debounce to identify their release.
            let finish = DispatchWorkItem { [weak self] in
                guard let self else { return }
                self.finishWheel(at: self.wheelTime + 0.16)
            }
            wheelFinish = finish
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.16, execute: finish)
        }
        return consumed ? nil : event
    }

    private func finishWheel(at timestamp: TimeInterval) {
        wheelFinish?.cancel()
        wheelFinish = nil
        if wheelAxis == .horizontal {
            let velocity = timestamp - wheelLastMovementTime > 0.1 ? 0 : wheelVelocity
            onEnd(wheelTranslation, velocity)
        }
        resetWheel()
    }

    private func resetWheel() {
        wheelAxis = .undecided
        wheelTranslation = 0
        wheelY = 0
        wheelTime = 0
        wheelLastMovementTime = 0
        wheelVelocity = 0
        wheelHasPhase = false
    }
}
