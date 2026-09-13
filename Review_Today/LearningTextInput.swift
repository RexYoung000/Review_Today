import AppKit
import SwiftUI

struct EditorInsertion {
    let id = UUID()
    let text: String
    var templateID: String? = nil
    var appendToEnd = false
}

/// Native text and marked text share one layout manager, inset and paragraph.
struct LearningTextInput: NSViewRepresentable {
    @Binding var text: String
    @Binding var height: CGFloat
    @Binding var focused: Bool
    var focusRequest: Int
    var sessionID: UUID?
    var placeholder: String
    var ink: NSColor
    var insertion: EditorInsertion? = nil
    var editable = true
    var onInsertionApplied: ((String) -> Void)? = nil
    var onSubmit: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.hasHorizontalScroller = false
        let view = LearningEditor(frame: .zero)
        view.font = .systemFont(ofSize: 14)
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = 4
        view.defaultParagraphStyle = paragraph
        view.isRichText = false
        view.isAutomaticQuoteSubstitutionEnabled = false
        view.isAutomaticDashSubstitutionEnabled = false
        view.allowsUndo = true
        view.drawsBackground = false
        view.isVerticallyResizable = true
        view.isHorizontallyResizable = false
        view.autoresizingMask = [.width]
        view.textContainer?.widthTracksTextView = true
        view.textContainer?.lineFragmentPadding = 0
        view.textContainerInset = NSSize(width: 8, height: 8)
        view.minSize = NSSize(width: 0, height: 64)
        view.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        view.delegate = context.coordinator
        view.setAccessibilityLabel("学习输入")
        scroll.documentView = view
        context.coordinator.view = view
        view.onLayout = { [weak coordinator = context.coordinator] in coordinator?.measure() }
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? LearningEditor else { return }
        let coordinator = context.coordinator
        coordinator.parent = self
        view.onSubmit = onSubmit
        view.setEditingEnabled(editable)
        view.onInsertionApplied = onInsertionApplied
        view.onFocus = { [weak coordinator, weak view] value in
            guard let coordinator else { return }
            let owner = coordinator.sessionID
            DispatchQueue.main.async { [weak coordinator, weak view] in
                guard let coordinator, let view, coordinator.sessionID == owner,
                      !value || (view.window?.isKeyWindow == true && view.window?.firstResponder === view),
                      coordinator.parent.focused != value else { return }
                coordinator.parent.focused = value
            }
        }
        if view.placeholder != placeholder { view.placeholder = placeholder; view.needsDisplay = true }
        if coordinator.ink != ink {
            coordinator.ink = ink
            view.typingAttributes = [.font: NSFont.systemFont(ofSize: 14), .paragraphStyle: view.defaultParagraphStyle!, .foregroundColor: ink]
            view.textColor = ink
            view.insertionPointColor = ink
        }
        if coordinator.sessionID != sessionID {
            coordinator.sessionID = sessionID
            view.releaseFocus()
            view.unmarkText()
            view.undoManager?.removeAllActions()
            view.string = text
            coordinator.invalidateLayout()
            view.resetPrefill()
        } else if view.string != text && !view.hasMarkedText() {
            view.string = text
            coordinator.invalidateLayout()
            view.resetPrefill()
        }
        coordinator.measure()
        if let insertion, coordinator.lastInsertion != insertion.id {
            coordinator.lastInsertion = insertion.id
            view.queueInsertion(insertion)
        }
        if coordinator.focusRequest != focusRequest {
            coordinator.focusRequest = focusRequest
            let requested = focusRequest
            let requestedAt = NSApp.currentEvent?.timestamp ?? 0
            let revision = view.interactionRevision
            let owner = sessionID
            DispatchQueue.main.async { [weak view] in
                guard let view, coordinator.focusRequest == requested, coordinator.sessionID == owner,
                      revision == view.interactionRevision, view.isEditable,
                      FocusReturnPolicy.allows(since: requestedAt, current: NSApp.currentEvent) else { return }
                view.requestFocus()
            }
        }
    }

    static func dismantleNSView(_ scroll: NSScrollView, coordinator: Coordinator) {
        (scroll.documentView as? LearningEditor)?.disposeFocusTracking()
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: LearningTextInput
        weak var view: LearningEditor?
        var sessionID: UUID?
        var focusRequest: Int
        var lastInsertion: UUID?
        var ink: NSColor?
        private var measuredWidth: CGFloat?
        private var layoutInvalid = true
        private var measurementRevision = 0
        private(set) var layoutMeasurementCount = 0
        func invalidateLayout() { layoutInvalid = true }
        init(_ parent: LearningTextInput) { self.parent = parent; focusRequest = parent.focusRequest }
        func textDidChange(_ notification: Notification) {
            guard let view else { return }
            parent.text = view.string
            view.needsDisplay = true
            invalidateLayout()
            measure()
        }
        func measure() {
            guard let view, let container = view.textContainer, let layout = view.layoutManager else { return }
            let width = container.containerSize.width
            guard width > 0, layoutInvalid || measuredWidth != width else { return }
            measuredWidth = width; layoutInvalid = false
            measurementRevision += 1
            let revision = measurementRevision, owner = sessionID
            layoutMeasurementCount += 1
            layout.ensureLayout(for: container)
            let measured = min(160, max(64, ceil(layout.usedRect(for: container).height + 16)))
            guard abs(parent.height - measured) > 0.5 else { return }
            DispatchQueue.main.async { [weak self] in
                guard let self, self.measurementRevision == revision, self.sessionID == owner,
                      abs(self.parent.height - measured) > 0.5 else { return }
                self.parent.height = measured
            }
        }
    }
}

final class LearningEditor: NSTextView {
    var placeholder = ""
    var onSubmit: (() -> Void)?
    var onFocus: ((Bool) -> Void)?
    var onLayout: (() -> Void)?
    var onInsertionApplied: ((String) -> Void)?
    private var prefill = QuickStartPrefill()
    private var applyingTemplate = false
    private var pendingInsertion: EditorInsertion?
    private var insertionTime: TimeInterval = 0
    private var insertionRevision = 0
    private var focusAfterUnlock: Int?
    private(set) var interactionRevision = 0
    private var intentionalFocus = false
    private var publishedFocus: Bool?
    private var eventMonitor: Any?
    private var focusObservers: [NSObjectProtocol] = []

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        disposeFocusTracking()
        guard let window else { publishFocus(); return }
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { [weak self] event in
            self?.observeInteraction(event)
            return event
        }
        for name in [NSWindow.didBecomeKeyNotification, NSWindow.didResignKeyNotification] {
            focusObservers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.publishFocus() }
            })
        }
        publishFocus()
    }

    func disposeFocusTracking() {
        if let eventMonitor { NSEvent.removeMonitor(eventMonitor) }
        eventMonitor = nil
        focusObservers.forEach(NotificationCenter.default.removeObserver)
        focusObservers.removeAll()
    }

    private func containsPointer(_ event: NSEvent) -> Bool {
        guard event.window === window else { return false }
        let target: NSView = enclosingScrollView?.contentView ?? self
        return target.bounds.contains(target.convert(event.locationInWindow, from: nil))
    }

    func observeInteraction(_ event: NSEvent) {
        interactionRevision += 1
        if [.leftMouseDown, .rightMouseDown].contains(event.type), event.window === window, !containsPointer(event) {
            releaseFocus()
        }
    }

    func requestFocus() {
        guard isEditable else { return }
        intentionalFocus = true
        window?.makeFirstResponder(self)
        intentionalFocus = false
    }

    func releaseFocus() {
        if window?.firstResponder === self { window?.makeFirstResponder(nil) }
        publishFocus()
    }

    func setEditingEnabled(_ enabled: Bool) {
        guard isEditable != enabled else { return }
        isEditable = enabled
        if !enabled { releaseFocus() }
        else if let revision = focusAfterUnlock {
            focusAfterUnlock = nil
            if revision == interactionRevision { requestFocus() }
        }
    }

    private func publishFocus() {
        let value = isEditable && window?.isKeyWindow == true && window?.firstResponder === self
        guard publishedFocus != value else { return }
        publishedFocus = value
        onFocus?(value)
        needsDisplay = true
    }

    func resetPrefill() {
        prefill = QuickStartPrefill()
        pendingInsertion = nil
        focusAfterUnlock = nil
    }

    func queueInsertion(_ insertion: EditorInsertion) {
        pendingInsertion = insertion
        insertionTime = NSApp.currentEvent?.timestamp ?? 0
        insertionRevision = interactionRevision
        scheduleInsertion()
    }

    private func scheduleInsertion() {
        DispatchQueue.main.async { [weak self] in self?.applyPendingInsertion() }
    }

    /// Read the latest pending operation *at application time*. A stale dispatch
    /// cannot overwrite a newer card selection or text from a different Session.
    func applyPendingInsertion() {
        guard !hasMarkedText(), let insertion = pendingInsertion, !applyingTemplate else { return }
        pendingInsertion = nil
        if insertion.appendToEnd {
            let wasEditable = isEditable
            isEditable = true
            breakUndoCoalescing()
            insertText((string.isEmpty ? "" : "\n") + insertion.text, replacementRange: NSRange(location: (string as NSString).length, length: 0))
            breakUndoCoalescing()
            isEditable = wasEditable
            onInsertionApplied?(string)
        } else if let id = insertion.templateID {
            guard let next = prefill.apply(id: id, prompt: insertion.text, to: string) else { return }
            applyingTemplate = true
            insertText(next, replacementRange: NSRange(location: 0, length: (string as NSString).length))
            applyingTemplate = false
        } else {
            insertText(insertion.text, replacementRange: selectedRange())
        }
        if insertionRevision == interactionRevision && FocusReturnPolicy.allows(since: insertionTime, current: NSApp.currentEvent) {
            if isEditable { requestFocus() }
            else { focusAfterUnlock = interactionRevision }
        }
    }

    override func didChangeText() {
        if !applyingTemplate { prefill.userEdited() }
        super.didChangeText()
        if pendingInsertion != nil { scheduleInsertion() }
    }

    override func unmarkText() {
        super.unmarkText()
        if pendingInsertion != nil { scheduleInsertion() }
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 48 && !hasMarkedText() && event.modifierFlags.intersection([.command, .control, .option]).isEmpty {
            if event.modifierFlags.contains(.shift) { window?.selectPreviousKeyView(self) }
            else { window?.selectNextKeyView(self) }
            return
        }
        if event.keyCode == 36 || event.keyCode == 76 {
            if hasMarkedText() { super.keyDown(with: event); return }
            let modifiers = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            if modifiers.contains(.shift) { insertNewline(nil); return }
            if modifiers.intersection([.control, .option]).isEmpty {
                if !event.isARepeat && !string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { onSubmit?() }
                return
            }
        }
        super.keyDown(with: event)
    }

    private var permitsFocus: Bool {
        let event = NSApp.currentEvent
        let pointer = event.map { [.leftMouseDown, .rightMouseDown].contains($0.type) && containsPointer($0) } ?? false
        let keyboard = event?.type == .keyDown && event?.keyCode == 48
        return isEditable && (intentionalFocus || pointer || keyboard)
    }
    override var acceptsFirstResponder: Bool { permitsFocus }
    override func setAccessibilityFocused(_ focused: Bool) {
        intentionalFocus = focused && isEditable
        super.setAccessibilityFocused(focused)
        if focused { requestFocus() } else { releaseFocus() }
        intentionalFocus = false
    }
    override func becomeFirstResponder() -> Bool {
        guard permitsFocus else { return false }
        let result = super.becomeFirstResponder()
        publishFocus()
        return result
    }
    override func resignFirstResponder() -> Bool {
        let result = super.resignFirstResponder()
        if result { publishedFocus = false; onFocus?(false) }
        return result
    }
    override func layout() { super.layout(); onLayout?() }
    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard string.isEmpty else { return }
        var attributes = typingAttributes
        attributes[.foregroundColor] = NSColor.placeholderTextColor
        let bounds = NSRect(x: textContainerOrigin.x, y: textContainerOrigin.y,
                            width: max(0, self.bounds.width - textContainerInset.width * 2), height: self.bounds.height - 16)
        (placeholder as NSString).draw(with: bounds, options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: attributes)
    }
}
