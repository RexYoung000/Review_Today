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
        view.isEditable = editable
        view.onInsertionApplied = onInsertionApplied
        view.onFocus = { value in DispatchQueue.main.async { coordinator.parent.focused = value } }
        view.placeholder = placeholder
        view.font = .systemFont(ofSize: 14)
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = 4
        view.defaultParagraphStyle = paragraph
        view.typingAttributes = [.font: NSFont.systemFont(ofSize: 14), .paragraphStyle: paragraph, .foregroundColor: ink]
        view.textColor = ink
        view.insertionPointColor = ink
        if coordinator.sessionID != sessionID {
            coordinator.sessionID = sessionID
            view.unmarkText()
            view.undoManager?.removeAllActions()
            view.string = text
            view.resetPrefill()
        } else if view.string != text && !view.hasMarkedText() {
            view.string = text
            view.resetPrefill()
        }
        view.needsDisplay = true
        coordinator.measure()
        if let insertion, coordinator.lastInsertion != insertion.id {
            coordinator.lastInsertion = insertion.id
            view.queueInsertion(insertion)
        }
        if coordinator.focusRequest != focusRequest {
            coordinator.focusRequest = focusRequest
            let requested = focusRequest
            let requestedAt = NSApp.currentEvent?.timestamp ?? 0
            DispatchQueue.main.async { [weak view] in
                guard let view, coordinator.focusRequest == requested,
                      FocusReturnPolicy.allows(since: requestedAt, current: NSApp.currentEvent) else { return }
                view.window?.makeFirstResponder(view)
            }
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: LearningTextInput
        weak var view: LearningEditor?
        var sessionID: UUID?
        var focusRequest = -1
        var lastInsertion: UUID?
        init(_ parent: LearningTextInput) { self.parent = parent }
        func textDidChange(_ notification: Notification) {
            guard let view else { return }
            parent.text = view.string
            view.needsDisplay = true
            measure()
        }
        func measure() {
            guard let view, let container = view.textContainer, let layout = view.layoutManager else { return }
            layout.ensureLayout(for: container)
            let measured = min(160, max(64, ceil(layout.usedRect(for: container).height + 16)))
            guard abs(parent.height - measured) > 0.5 else { return }
            DispatchQueue.main.async { [weak self] in
                guard let self, self.parent.height != measured else { return }
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

    func resetPrefill() {
        prefill = QuickStartPrefill()
        pendingInsertion = nil
    }

    func queueInsertion(_ insertion: EditorInsertion) {
        pendingInsertion = insertion
        insertionTime = NSApp.currentEvent?.timestamp ?? 0
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
        if FocusReturnPolicy.allows(since: insertionTime, current: NSApp.currentEvent) { window?.makeFirstResponder(self) }
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

    override func becomeFirstResponder() -> Bool {
        let result = super.becomeFirstResponder()
        if result { onFocus?(true) }
        return result
    }
    override func resignFirstResponder() -> Bool {
        let result = super.resignFirstResponder()
        if result { onFocus?(false) }
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
