import SwiftUI

/// Native glass remains the material. Reflections stay behind the text and never delay activation.
struct PrototypeGlassEntry: View {
    let title: String
    let detail: String
    let symbol: String
    var previewSelected = false
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
    @State private var enteredAt = Date.distantPast
    @State private var sweeping = false

    private var shape: RoundedRectangle { .init(cornerRadius: Runway.chipRadius, style: .continuous) }
    private var keyboard: Bool { focused && input.keyboardNavigation }
    private var selected: Bool { enabled && controlState == .key && (hovering || keyboard || previewSelected) }
    private var dark: Bool { scheme == .dark }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: symbol).font(.system(size: 19, weight: .medium)).frame(width: 26)
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.headline)
                    Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: "arrow.up.right").font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(selected ? (dark ? Color.black : .white) : palette.ink.opacity(0.5))
                    .frame(width: 26, height: 26)
                    .background(selected ? palette.ink : .clear, in: Circle())
                    .offset(x: selected && !reduced ? 2 : 0, y: selected && !reduced ? -2 : 0)
            }
            .padding(.horizontal, 22).padding(.vertical, 19)
            .frame(maxWidth: .infinity, minHeight: 84, alignment: .leading)
            .background { material }
            .overlay { rim.allowsHitTesting(false) }
            .contentShape(shape)
            .shadow(color: .black.opacity(selected ? (dark ? 0.25 : 0.09) : 0), radius: 12, y: 5)
            .animation(reduced ? nil : .easeOut(duration: 0.16), value: selected)
        }
        .buttonStyle(PrototypeGlassPressStyle(reduced: reduced))
        .focusable(enabled).focusEffectDisabled().focused($focused)
        .onKeyPress(keys: [.return, .space], phases: .down) { _ in
            guard focused && enabled else { return .ignored }; action(); return .handled
        }
        .onContinuousHover { phase in
            switch phase {
            case .active(let location):
                hovering = true
                pointer = .init(x: min(1, max(0, location.x / max(1, entrySize.width))),
                                y: min(1, max(0, location.y / max(1, entrySize.height))))
            case .ended: hovering = false
            }
        }
        .onHover { hovering = $0 }
        .onGeometryChange(for: CGSize.self) { $0.size } action: { entrySize = $0 }
        .task(id: EntryHighlight(active: selected && !keyboard, animated: !reduced && !opaque)) {
            sweeping = false
            guard selected && !keyboard && !reduced && !opaque else { return }
            enteredAt = .now; sweeping = true
            do { try await Task.sleep(for: .milliseconds(760)) } catch { return }
            guard !Task.isCancelled else { return }; sweeping = false
        }
        .onChange(of: controlState) { _, value in if value != .key { hovering = false } }
        .onDisappear { hovering = false; sweeping = false }
    }

    private var material: some View {
        ZStack {
            if opaque {
                shape.fill(palette.card)
            } else {
                shape.fill(.clear).glassEffect(.regular.interactive(!reduced), in: shape)
            }
            shape.fill(palette.ink.opacity(selected ? (dark ? 0.065 : 0.055) : 0))
            if selected && !opaque {
                RadialGradient(colors: [.white.opacity(dark ? 0.16 : 0.9), .clear],
                               center: reduced || keyboard ? .topLeading : pointer, startRadius: 0, endRadius: 190)
                if sweeping && !reduced {
                    TimelineView(.animation(minimumInterval: 1 / 60)) { clock in
                        GlassReflection(elapsed: clock.date.timeIntervalSince(enteredAt), dark: dark)
                    }
                }
            }
        }.clipShape(shape).allowsHitTesting(false)
    }

    private var rim: some View {
        ZStack {
            shape.strokeBorder(palette.ink.opacity(selected ? (dark ? 0.35 : 0.22) : (opaque ? 0.08 : 0)), lineWidth: selected ? 1.2 : 1)
            if selected && !opaque {
                shape.inset(by: 1.4).strokeBorder(
                    LinearGradient(colors: [.white.opacity(0.95), .white.opacity(0.14), .clear, .white.opacity(0.5)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1)
            }
            if keyboard { shape.strokeBorder(palette.ink, lineWidth: 1.5).padding(-3) }
        }
    }
}

private struct EntryHighlight: Equatable {
    let active: Bool
    let animated: Bool
}

private struct GlassReflection: View {
    let elapsed: Double
    let dark: Bool
    var body: some View {
        GeometryReader { geometry in
            let t = min(1, max(0, elapsed / 0.72))
            let travel = 1 - pow(1 - t, 2)
            let x = geometry.size.width * (-0.25 + 1.5 * travel)
            let flash = max(0, 1 - abs(elapsed - 0.18) / 0.16)
            ZStack(alignment: .topLeading) {
                Rectangle().fill(LinearGradient(stops: [
                    .init(color: .clear, location: 0), .init(color: .white.opacity(0.10), location: 0.25),
                    .init(color: .white.opacity(dark ? 0.4 : 0.95), location: 0.49),
                    .init(color: .white.opacity(0.12), location: 0.62), .init(color: .clear, location: 1)
                ], startPoint: .leading, endPoint: .trailing))
                .frame(width: geometry.size.width * 0.32, height: geometry.size.height * 2.5)
                .rotationEffect(.degrees(23)).position(x: x, y: geometry.size.height / 2)
                // One small specular glint at the rim, not a repeated full-card flash.
                Image(systemName: "sparkle").font(.system(size: 19, weight: .ultraLight))
                    .foregroundStyle(.white).shadow(color: .white.opacity(0.9), radius: 4)
                    .scaleEffect(0.7 + flash * 0.6).opacity(flash)
                    .position(x: geometry.size.width * 0.74, y: 2)
            }
        }.accessibilityHidden(true)
    }
}

private struct PrototypeGlassPressStyle: ButtonStyle {
    let reduced: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed && !reduced ? 0.992 : 1)
            .opacity(configuration.isPressed ? 0.86 : 1)
            .animation(reduced ? nil : .easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
