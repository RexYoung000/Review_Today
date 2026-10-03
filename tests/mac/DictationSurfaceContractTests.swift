import AppKit
import Observation
import SwiftUI

@Observable private final class DictationSurfaceState {
    var active = false
    var draft = "录音前的原稿"
    var insertion: EditorInsertion?
    var saved: [String] = []
    var submitted = 0
    let sessionID = UUID()
}

private struct DictationSurfaceHost: View {
    let state: DictationSurfaceState

    var body: some View {
        DictationComposerSurface(active: state.active) {
            LearningComposerInput(
                text: Binding(get: { state.draft }, set: { state.draft = $0 }),
                focusRequest: 0, sessionID: state.sessionID, placeholder: "输入草稿",
                insertion: state.insertion, editable: !state.active,
                onInsertionApplied: { state.saved.append($0) },
                onSubmit: { state.submitted += 1 }
            ) {
                Button("发送") { state.submitted += 1 }
            }
        } status: {
            Text("正在听写")
                .frame(maxWidth: .infinity)
                .frame(height: 84)
                .accessibilityIdentifier("dictation-visible-status")
        }
        .environment(\.runway, .light)
    }
}

@main
struct DictationSurfaceContractTests {
    @MainActor static func main() {
        _ = NSApplication.shared
        let state = DictationSurfaceState()
        let host = NSHostingView(rootView: DictationSurfaceHost(state: state))
        host.frame = NSRect(x: 0, y: 0, width: 480, height: 220)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        defer { window.close() }

        func settle() {
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date.now.addingTimeInterval(0.04))
            host.layoutSubtreeIfNeeded()
        }
        func editor(in view: NSView) -> LearningEditor? {
            if let editor = view as? LearningEditor { return editor }
            return view.subviews.lazy.compactMap { editor(in: $0) }.first
        }
        settle()
        guard let input = editor(in: host) else { preconditionFailure("the real native composer must be mounted") }
        let original = state.draft
        let selection = NSRange(location: 2, length: 2)
        input.setSelectedRange(selection)
        input.requestFocus()
        precondition(window.firstResponder === input, "the visible editor accepts explicit focus")
        let idleHeight = host.fittingSize.height

        state.active = true
        settle()
        precondition(editor(in: host) === input, "dictation must retain the same native text view")
        precondition(state.draft == original && input.string == original && input.selectedRange() == selection)
        precondition(abs(host.fittingSize.height - 84) < 1 && idleHeight > 84,
                     "the hidden composer must not contribute its height to the status surface")
        precondition(!input.isEditable && window.firstResponder !== input,
                     "entering dictation must release editing focus")
        for y in stride(from: 1.0, to: host.bounds.height, by: 12) {
            for x in stride(from: 1.0, to: host.bounds.width, by: 12) {
                if let hit = host.hitTest(NSPoint(x: x, y: y)) {
                    precondition(hit !== input && !hit.isDescendant(of: input),
                                 "the hidden editor must not receive native pointer hits")
                }
            }
        }
        input.requestFocus()
        input.setAccessibilityFocused(true)
        precondition(window.firstResponder !== input && !input.becomeFirstResponder(),
                     "the hidden editor cannot take keyboard or accessibility focus")

        // Cancelling performs no insertion, preserving both text and selection.
        state.active = false
        settle()
        precondition(editor(in: host) === input && input.isEditable)
        precondition(state.draft == original && input.string == original && input.selectedRange() == selection)
        precondition(state.saved.isEmpty && state.submitted == 0)

        // The processing surface remains active until the editor has saved the
        // append. Exercise the representable update, not a direct editor call.
        state.active = true
        settle()
        state.insertion = EditorInsertion(text: "听写内容", appendToEnd: true)
        settle()
        let appended = original + "\n听写内容"
        precondition(editor(in: host) === input && !input.isEditable)
        precondition(input.string == appended && state.draft == appended && state.saved == [appended],
                     "the hidden mounted editor must apply and save the pending transcription once")
        precondition(window.firstResponder !== input && state.submitted == 0,
                     "processing may append but must not focus or send")

        state.insertion = nil
        state.active = false
        settle()
        precondition(editor(in: host) === input && input.isEditable && input.string == appended)
        precondition(state.saved == [appended], "restoring the composer must not duplicate insertion")
        precondition(input.undoManager?.canUndo == true, "native undo history must survive dictation")
        input.undoManager?.undo()
        settle()
        precondition(input.string == original && state.draft == original,
                     "one native undo must remove the complete dictation append")
        precondition(state.submitted == 0)
        print("PASS: real hosted composer identity, hidden geometry/hit testing/focus, cancel draft/selection, processing insertion/save, no auto-send, single native undo")
    }
}
