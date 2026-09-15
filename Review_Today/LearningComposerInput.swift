import AppKit
import SwiftUI

/// Focus and text measurement redraw this input surface, without rebuilding the
/// transcript or its task history when the window becomes key.
struct LearningComposerInput<Controls: View>: View {
    @Binding var text: String
    let focusRequest: Int
    let sessionID: UUID?
    let placeholder: String
    let insertion: EditorInsertion?
    let editable: Bool
    let onInsertionApplied: (String) -> Void
    let onSubmit: () -> Void
    var preservesFocusOnClick: ((NSEvent) -> Bool)? = nil
    @ViewBuilder var controls: () -> Controls
    @State private var inputHeight: CGFloat = 64
    @State private var inputFocused = false
    @Environment(\.runway) private var runway

    var body: some View {
        VStack(spacing: 4) {
            LearningTextInput(text: $text, height: $inputHeight, focused: $inputFocused,
                focusRequest: focusRequest, sessionID: sessionID, placeholder: placeholder,
                ink: NSColor(runway.ink), insertion: insertion, editable: editable,
                onInsertionApplied: onInsertionApplied, preservesFocusOnClick: preservesFocusOnClick, onSubmit: onSubmit)
                .frame(height: inputHeight)
            controls()
        }
        .padding(10)
        .background(runway.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .strokeBorder(inputFocused ? (runway.monochrome ? runway.agent : runway.agent.opacity(0.65)) : runway.controlBorder,
                          lineWidth: inputFocused ? 1.5 : 1))
    }
}
