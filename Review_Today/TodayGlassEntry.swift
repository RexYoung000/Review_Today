import SwiftUI

/// Shared native glass for Today's live entries and the isolated design comparison.
struct TodayGlassEntry: View {
    let title: String
    let detail: String
    let symbol: String
    var previewPoint: UnitPoint? = nil
    let action: () -> Void
    @Environment(\.runway) private var palette
    @Environment(\.colorScheme) private var scheme
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.accessibilityReduceTransparency) private var opaque
    @Environment(\.controlActiveState) private var controlState
    @Environment(\.isEnabled) private var enabled
    @ObservedObject private var input = InteractionInputMode.shared
    @FocusState private var focused: Bool
    @State private var hovering = false
    @State private var pointer = UnitPoint(x: 0.5, y: 0.3)
    @State private var entrySize = CGSize(width: 400, height: 84)
    @State private var enteredAt = Date.now

    private var shape: RoundedRectangle { .init(cornerRadius: Runway.chipRadius, style: .continuous) }
    private var keyboard: Bool { focused && input.keyboardNavigation }
    private var selected: Bool { enabled && ((controlState == .key && (hovering || keyboard)) || previewPoint != nil) }
    private var activePoint: UnitPoint { reduced || keyboard ? .init(x: 0.28, y: 0.24) : hovering ? pointer : previewPoint ?? pointer }
    private var dark: Bool { scheme == .dark }
    private var flowing: Bool { hovering && selected && !keyboard && !reduced && !opaque }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: symbol).font(.system(size: 19, weight: .medium)).frame(width: 26)
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.headline).underline(keyboard)
                    Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: "arrow.up.right").font(.system(size: 12, weight: selected ? .bold : .medium))
                    .foregroundStyle(palette.ink.opacity(selected ? 0.9 : 0.5))
                    .frame(width: 26, height: 26)
                    .background(.white.opacity(selected ? (dark ? 0.12 : 0.6) : 0), in: Circle())
                    .offset(x: selected && !reduced ? 2 : 0, y: selected && !reduced ? -2 : 0)
            }
            .padding(.horizontal, 22).padding(.vertical, 19)
            .frame(maxWidth: .infinity, minHeight: 84, alignment: .leading)
            .background { glass }
            .contentShape(shape)
            .animation(reduced ? nil : .easeOut(duration: 0.16), value: selected)
        }
        .buttonStyle(TodayGlassPressStyle(reduced: reduced))
        .focusable(enabled).focusEffectDisabled().focused($focused)
        .onKeyPress(keys: [.return, .space], phases: .down) { _ in
            guard focused && enabled else { return .ignored }; action(); return .handled
        }
        .onContinuousHover { phase in
            switch phase {
            case .active(let location):
                hovering = true
                if !reduced {
                    pointer = .init(x: min(1, max(0, location.x / max(1, entrySize.width))),
                                    y: min(1, max(0, location.y / max(1, entrySize.height))))
                }
            case .ended: hovering = false
            }
        }
        .onGeometryChange(for: CGSize.self) { $0.size } action: { entrySize = $0 }
        .onChange(of: flowing) { _, active in if active { enteredAt = .now } }
        .onChange(of: controlState) { _, value in if value != .key { hovering = false } }
        .onDisappear { hovering = false }
    }

    private var glass: some View {
        ZStack {
            if opaque {
                shape.fill(palette.card)
            } else {
                shape.fill(.clear).glassEffect(.regular, in: shape)
                // Neutral silver gives the localized specular light contrast on bright paper.
                if !dark { shape.fill(Color(white: 0.82).opacity(0.22)) }
            }
            if selected && !opaque {
                RadialGradient(colors: [
                    .white.opacity(dark ? 0.27 : 0.74),
                    .white.opacity(dark ? 0.09 : 0.19),
                    .clear
                ], center: activePoint, startRadius: 0, endRadius: 195)
                .blendMode(.screen)
            }
            shape.inset(by: 0.7)
                .strokeBorder(dark ? .white.opacity(0.18) : Color(white: 0.68).opacity(0.18), lineWidth: 0.8)
            if selected {
                let edgeLight = RadialGradient(colors: [.white, .white.opacity(0.55), .clear],
                                               center: activePoint, startRadius: 0, endRadius: 165)
                shape.inset(by: 1.2)
                    .strokeBorder(.white.opacity(dark ? 0.72 : 1), lineWidth: 1.6)
                    .mask(edgeLight)
                if !opaque {
                    shape.inset(by: 5)
                        .strokeBorder(.white.opacity(dark ? 0.28 : 0.7), lineWidth: 0.9)
                        .mask(edgeLight)
                }
            }
            if flowing {
                TimelineView(.animation(minimumInterval: 1 / 30)) { clock in
                    GlassEdgeFlow(elapsed: max(0, clock.date.timeIntervalSince(enteredAt)), dark: dark)
                }
            }
        }
        .clipShape(shape)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Inspired by StarBorder's opposing top and bottom radial sweeps. The streaks
/// stay on the glass edge; they never fill the card or orbit the full perimeter.
private struct GlassEdgeFlow: View {
    let elapsed: Double
    let dark: Bool

    var body: some View {
        GeometryReader { geometry in
            let phase = elapsed.truncatingRemainder(dividingBy: 5.4) / 5.4
            let travel = phase < 0.5 ? phase * 2 : (1 - phase) * 2
            let fade = 0.25 + 0.75 * sin(.pi * travel)
            let streakWidth = min(240, geometry.size.width * 0.49)
            ZStack {
                streak(width: streakWidth)
                    .position(x: geometry.size.width * (-0.18 + 1.36 * travel), y: 1.6)
                streak(width: streakWidth)
                    .position(x: geometry.size.width * (1.18 - 1.36 * travel), y: geometry.size.height - 1.6)
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .opacity(fade)
            .clipShape(RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
        }.accessibilityHidden(true)
    }

    private func streak(width: CGFloat) -> some View {
        let core = dark ? Color.white : Color(white: 0.36)
        return ZStack {
            Capsule()
                .fill(LinearGradient(colors: [.clear, .white.opacity(dark ? 0.72 : 0.9), .clear],
                                     startPoint: .leading, endPoint: .trailing))
                .frame(width: width, height: 16)
                .blur(radius: 6)
            Capsule()
                .fill(LinearGradient(colors: [.clear, core.opacity(dark ? 0.38 : 0.4),
                                               core.opacity(dark ? 1 : 0.98),
                                               core.opacity(dark ? 0.38 : 0.4), .clear],
                                     startPoint: .leading, endPoint: .trailing))
                .frame(width: width * 0.86, height: dark ? 3.2 : 4.2)
        }
    }
}

private struct TodayGlassPressStyle: ButtonStyle {
    let reduced: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed && !reduced ? 0.992 : 1)
            .animation(reduced ? nil : .easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
