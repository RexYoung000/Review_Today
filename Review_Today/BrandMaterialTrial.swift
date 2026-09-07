import SwiftUI

private struct BrandMaterialTrialKey: EnvironmentKey { static let defaultValue = false }
private struct BrandMaterialPreviewKey: EnvironmentKey { static let defaultValue = false }
private struct BrandTrialStillKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    var brandMaterialPreview: Bool {
        get { self[BrandMaterialPreviewKey.self] }
        set { self[BrandMaterialPreviewKey.self] = newValue }
    }
    var brandMaterialTrial: Bool {
        get { self[BrandMaterialTrialKey.self] }
        set { self[BrandMaterialTrialKey.self] = newValue }
    }
    var brandTrialStill: Bool {
        get { self[BrandTrialStillKey.self] }
        set { self[BrandTrialStillKey.self] = newValue }
    }
    var brandReduceMotion: Bool { accessibilityReduceMotion || brandTrialStill }
}

extension RunwayPalette {
    /// The opt-in trial keeps current layout and solid surfaces.
    static func monochromeTrial(dark: Bool) -> RunwayPalette {
        var p = dark ? Self.dark : Self.light
        p.monochrome = true
        p.canvas = Color(white: dark ? 0.075 : 0.965)
        p.card = Color(white: dark ? 0.125 : 1)
        p.field = Color(white: dark ? 0.18 : 0.935)
        p.ink = Color(white: dark ? 0.96 : 0.10)
        p.copy = Color(white: dark ? 0.72 : 0.38)
        p.agent = p.ink
        p.plus = p.ink
        p.action = p.ink
        p.onAction = Color(white: dark ? 0.10 : 1)
        p.liftShadow = Color.black.opacity(dark ? 0.22 : 0.08)
        return p
    }
    var information: Color { monochrome ? ink : agent }
    var secondaryInformation: Color { monochrome ? copy : agent }
    var addition: Color { monochrome ? ink : plus }
    var decorativeAccent: Color { monochrome ? copy : agent }
    var history: Color { monochrome ? ink : agent }
    var hoverWash: Color { monochrome ? ink : agent }
    var controlBorder: Color { monochrome ? copy : hairline }
}

struct MascotMaterialPalette: Codable, Equatable {
    var accent: [Int]
    var wave: [Int]
    static func theme(dark: Bool) -> Self {
        Self(accent: dark ? [238,238,238] : [38,38,38], wave: dark ? [142,142,142] : [104,104,104])
    }
}

/// The rounded AppKit field otherwise keeps the system blue focus ring.
/// Current appearance uses the same standard style; the trial owns its border.
struct BrandMaterialTextFieldStyle: TextFieldStyle {
    @Environment(\.runway) private var palette
    @FocusState private var focused: Bool
    func _body(configuration: TextField<Self._Label>) -> some View {
        if palette.monochrome {
            configuration.textFieldStyle(.plain)
                .padding(6)
                .background(palette.field, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(focused ? palette.ink : palette.controlBorder, lineWidth: focused ? 1.5 : 1))
                .focused($focused)
                .focusEffectDisabled()
        } else {
            configuration.textFieldStyle(.roundedBorder)
        }
    }
}
