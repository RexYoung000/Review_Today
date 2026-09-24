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
    @State private var iconBurst = false
    @State private var iconBurstTask: Task<Void, Never>?

    private var shape: RoundedRectangle { .init(cornerRadius: Runway.chipRadius, style: .continuous) }
    private var keyboard: Bool { focused && input.keyboardNavigation }
    private var selected: Bool { enabled && ((controlState == .key && (hovering || keyboard)) || previewPoint != nil) }
    private var activePoint: UnitPoint { reduced || keyboard ? .init(x: 0.28, y: 0.24) : hovering ? pointer : previewPoint ?? pointer }
    private var dark: Bool { scheme == .dark }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                entryIcon
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
                if !hovering && enabled && controlState == .key && !reduced { playIconBurst() }
                hovering = true
                if !reduced {
                    pointer = .init(x: min(1, max(0, location.x / max(1, entrySize.width))),
                                    y: min(1, max(0, location.y / max(1, entrySize.height))))
                }
            case .ended: endHover()
            }
        }
        .onGeometryChange(for: CGSize.self) { $0.size } action: { entrySize = $0 }
        .onChange(of: controlState) { _, value in if value != .key { endHover() } }
        .onChange(of: reduced) { _, value in if value { stopIconBurst() } }
        .onDisappear { endHover() }
    }

    private var entryIcon: some View {
        ZStack {
            if symbol == "sparkle" && iconBurst {
                Image(systemName: symbol)
                    .foregroundStyle(palette.ink.opacity(0.25))
                    .scaleEffect(1.5)
                    .blur(radius: 3)
            }
            Image(systemName: symbol)
                .rotationEffect(.degrees(symbol == "sparkle" && iconBurst ? -14 : 0))
                .offset(y: symbol != "sparkle" && iconBurst ? -3 : 0)
        }
        .font(.system(size: 19, weight: .medium))
        .scaleEffect(iconBurst ? 1.22 : selected ? 1.12 : 1)
        .frame(width: 26, height: 26)
        .animation(reduced || keyboard ? nil : .spring(response: 0.22, dampingFraction: 0.62), value: iconBurst)
        .animation(reduced || keyboard ? nil : .spring(response: 0.28, dampingFraction: 0.7), value: selected)
        .accessibilityHidden(true) // The parent button already names the destination.
    }

    private func playIconBurst() {
        iconBurstTask?.cancel()
        iconBurst = true
        iconBurstTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(170))
            guard !Task.isCancelled else { return }
            iconBurst = false
            iconBurstTask = nil
        }
    }

    private func stopIconBurst() {
        iconBurstTask?.cancel()
        iconBurstTask = nil
        iconBurst = false
    }

    private func endHover() {
        hovering = false
        stopIconBurst()
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
        }
        .clipShape(shape)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

private struct TodayGlassPressStyle: ButtonStyle {
    let reduced: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed && !reduced ? 0.992 : 1)
            .animation(reduced ? nil : .easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
