import SwiftUI

/// Glass owns the material; light is additive and never changes the label or hit target.
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
    @State private var enteredAt = Date.now

    private var shape: RoundedRectangle { .init(cornerRadius: Runway.chipRadius, style: .continuous) }
    private var keyboard: Bool { focused && input.keyboardNavigation }
    private var selected: Bool { enabled && controlState == .key && (hovering || keyboard || previewSelected) }
    private var dark: Bool { scheme == .dark }
    private var flowing: Bool { selected && !keyboard && !reduced && !opaque }

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
                    .background(.white.opacity(selected ? (dark ? 0.16 : 0.75) : 0), in: Circle())
                    .offset(x: selected && !reduced ? 2 : 0, y: selected && !reduced ? -2 : 0)
            }
            .padding(.horizontal, 22).padding(.vertical, 19)
            .frame(maxWidth: .infinity, minHeight: 84, alignment: .leading)
            .background { material }
            .contentShape(shape)
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
        .onChange(of: flowing) { _, active in if active { enteredAt = .now } }
        .onChange(of: controlState) { _, value in if value != .key { hovering = false } }
        .onDisappear { hovering = false }
    }

    private var material: some View {
        ZStack {
            if opaque {
                shape.fill(palette.card)
            } else {
                // Our hover light replaces the system interactive wash, which darkened this monochrome surface.
                shape.fill(.clear).glassEffect(.regular, in: shape)
            }
            if selected {
                shape.fill(.white.opacity(dark ? 0.035 : 0.02))
                if !opaque {
                    RadialGradient(colors: [.white.opacity(dark ? 0.15 : 0.35), .clear],
                                   center: reduced || keyboard ? .topLeading : pointer, startRadius: 0, endRadius: 190)
                }
                shape.inset(by: 1).strokeBorder(
                    LinearGradient(colors: [.white.opacity(0.9), .white.opacity(0.08), .white.opacity(0.6)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1)
            }
            if flowing {
                TimelineView(.animation(minimumInterval: 1 / 60)) { clock in
                    GlassReflection(elapsed: max(0, clock.date.timeIntervalSince(enteredAt)), dark: dark)
                }
            }
        }.clipShape(shape).allowsHitTesting(false)
    }
}

/// A continuous highlight trail and small moving glints; no full-card flash or dark rim.
private struct GlassReflection: View {
    let elapsed: Double
    let dark: Bool
    var body: some View {
        GeometryReader { geometry in
            let phase = elapsed.truncatingRemainder(dividingBy: 2.8) / 2.8
            let x = geometry.size.width * (-0.3 + 1.6 * phase)
            ZStack {
                Rectangle().fill(LinearGradient(stops: [
                    .init(color: .clear, location: 0),
                    .init(color: Color(red: 0.79, green: 0.87, blue: 0.92).opacity(dark ? 0.07 : 0.46), location: 0.26),
                    .init(color: .white.opacity(dark ? 0.23 : 0.88), location: 0.49),
                    .init(color: .white.opacity(0.08), location: 0.65), .init(color: .clear, location: 1)
                ], startPoint: .leading, endPoint: .trailing))
                .frame(width: geometry.size.width * 0.40, height: geometry.size.height * 3)
                .rotationEffect(.degrees(23)).position(x: x, y: geometry.size.height / 2)
                Canvas { context, size in
                    let path = RoundedRectangle(cornerRadius: Runway.chipRadius - 4, style: .continuous)
                        .path(in: CGRect(origin: .zero, size: size).insetBy(dx: 4, dy: 4))
                    for offset in [0.0, 0.5] {
                        let head = (elapsed / 3.6 + offset).truncatingRemainder(dividingBy: 1)
                        let silver = dark ? Color.white : Color(red: 0.57, green: 0.70, blue: 0.81)
                        var glow = context
                        glow.addFilter(.shadow(color: silver.opacity(0.7), radius: 3))
                        for step in 0..<12 {
                            let end = (head - Double(step) * 0.009 + 1).truncatingRemainder(dividingBy: 1)
                            let start = max(0, end - 0.012)
                            glow.stroke(path.trimmedPath(from: start, to: end),
                                        with: .color(silver.opacity((1 - Double(step) / 12) * (dark ? 0.8 : 0.85))),
                                        style: StrokeStyle(lineWidth: 1.7, lineCap: .round))
                        }
                        if let point = path.trimmedPath(from: 0, to: max(0.0001, head)).currentPoint {
                            let pulse = 0.6 + 0.4 * pow(sin(elapsed * 2.7 + offset * 8), 2)
                            var star = Path()
                            star.move(to: .init(x: point.x - 5 * pulse, y: point.y))
                            star.addLine(to: .init(x: point.x + 5 * pulse, y: point.y))
                            star.move(to: .init(x: point.x, y: point.y - 5 * pulse))
                            star.addLine(to: .init(x: point.x, y: point.y + 5 * pulse))
                            glow.stroke(star, with: .color(silver), style: StrokeStyle(lineWidth: 1, lineCap: .round))
                            glow.fill(Path(ellipseIn: CGRect(x: point.x - 1.4, y: point.y - 1.4, width: 2.8, height: 2.8)), with: .color(.white))
                        }
                    }
                }
            }
        }.accessibilityHidden(true)
    }
}

private struct PrototypeGlassPressStyle: ButtonStyle {
    let reduced: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed && !reduced ? 0.992 : 1)
            .animation(reduced ? nil : .easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
