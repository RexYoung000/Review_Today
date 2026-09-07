import SwiftUI

/// Opt-in from the standalone, memory-only preview. The daily app never enables it.
private struct GlassPreviewKey: EnvironmentKey {
    static let defaultValue = false
}
private struct GlassPreviewSolidKey: EnvironmentKey { static let defaultValue = false }
private struct GlassPreviewStillKey: EnvironmentKey { static let defaultValue = false }

extension EnvironmentValues {
    var glassPreview: Bool {
        get { self[GlassPreviewKey.self] }
        set { self[GlassPreviewKey.self] = newValue }
    }
    var glassPreviewReduceTransparency: Bool {
        get { self[GlassPreviewSolidKey.self] }
        set { self[GlassPreviewSolidKey.self] = newValue }
    }
    var glassPreviewReduceMotion: Bool {
        get { self[GlassPreviewStillKey.self] }
        set { self[GlassPreviewStillKey.self] = newValue }
    }
    var previewAwareReduceMotion: Bool { accessibilityReduceMotion || glassPreviewReduceMotion }
    var previewAwareReduceTransparency: Bool { accessibilityReduceTransparency || glassPreviewReduceTransparency }
}

extension RunwayPalette {
    static func glassPreview(dark: Bool) -> RunwayPalette {
        var palette = dark ? Self.dark : Self.light
        // Both accents now share the brand hue. The dark variant restores contrast.
        let accent = dark
            ? Color(red: 0.46, green: 0.76, blue: 0.70)
            : Color(red: 36 / 255, green: 108 / 255, blue: 99 / 255)
        palette.agent = accent
        palette.plus = accent
        palette.canvas = dark ? Color(white: 0.075) : Color(white: 0.965)
        palette.card = dark ? Color(white: 0.125) : .white
        palette.field = dark ? Color(white: 0.18) : Color(white: 0.935)
        palette.ink = dark ? Color(white: 0.96) : Color(white: 0.10)
        palette.copy = dark ? Color(white: 0.72) : Color(white: 0.38)
        palette.liftShadow = Color.black.opacity(dark ? 0.22 : 0.08)
        return palette
    }
}

private struct GlassOperationSurface: ViewModifier {
    var radius: CGFloat
    @Environment(\.glassPreview) private var enabled
    @Environment(\.previewAwareReduceTransparency) private var reduceTransparency
    @Environment(\.runway) private var runway

    @ViewBuilder func body(content: Content) -> some View {
        if enabled {
            if reduceTransparency {
                content.padding(4)
                    .background(runway.field, in: RoundedRectangle(cornerRadius: radius))
                    .overlay(RoundedRectangle(cornerRadius: radius)
                        .strokeBorder(runway.hairline, lineWidth: 1).allowsHitTesting(false))
            } else {
                content.padding(4)
                    .glassEffect(.regular, in: RoundedRectangle(cornerRadius: radius))
            }
        } else {
            content
        }
    }
}

extension View {
    /// One material per operation group; controls retain their own hover/focus feedback.
    func previewGlassOperations(radius: CGFloat = 14) -> some View {
        modifier(GlassOperationSurface(radius: radius))
    }
}
