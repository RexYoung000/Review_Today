import SwiftUI

/// Keeps the native editor mounted while dictation owns the visible input area.
/// The caller locks editing separately; disabling this subtree would also block
/// the pending transcription from being applied and saved by the editor.
struct DictationComposerSurface<Editor: View, Status: View>: View {
    let active: Bool
    @ViewBuilder var editor: () -> Editor
    @ViewBuilder var status: () -> Status

    var body: some View {
        ZStack(alignment: .top) {
            editor()
                .frame(height: active ? 0 : nil)
                .clipped()
                .opacity(active ? 0 : 1)
                .allowsHitTesting(!active)
                .accessibilityHidden(active)
            if active { status() }
        }
    }
}
