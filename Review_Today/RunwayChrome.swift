import AppKit
import SwiftUI

struct RunwayPalette: Equatable {
    var canvas: Color
    var card: Color
    var field: Color
    var ink: Color
    var action: Color
    var onAction: Color
    var plus: Color
    var agent: Color
    var hairline: Color
    var liftShadow: Color
    var scrim: Color
    var cardHighlight: Color

    static let light = RunwayPalette(
        canvas: Color(red: 0.965, green: 0.965, blue: 0.968),
        card: .white,
        field: Color(red: 0.94, green: 0.94, blue: 0.95),
        ink: Color(red: 0.10, green: 0.10, blue: 0.11),
        action: Color(red: 0.11, green: 0.11, blue: 0.12),
        onAction: .white,
        plus: Color(red: 0.18, green: 0.68, blue: 0.42),
        agent: Color(red: 0.15, green: 0.63, blue: 0.60),
        hairline: Color.black.opacity(0.08),
        liftShadow: Color.black.opacity(0.07),
        scrim: Color.black.opacity(0.28),
        cardHighlight: Color.white.opacity(0.8)
    )

    static let dark = RunwayPalette(
        canvas: Color(red: 0.07, green: 0.07, blue: 0.08),
        card: Color(red: 0.16, green: 0.16, blue: 0.18),
        field: Color(red: 0.22, green: 0.22, blue: 0.24),
        ink: Color(red: 0.96, green: 0.96, blue: 0.97),
        action: Color(red: 0.96, green: 0.96, blue: 0.97),
        onAction: Color(red: 0.10, green: 0.10, blue: 0.11),
        plus: Color(red: 0.42, green: 0.86, blue: 0.58),
        agent: Color(red: 0.38, green: 0.82, blue: 0.78),
        hairline: Color.white.opacity(0.14),
        liftShadow: Color.black.opacity(0.55),
        scrim: Color.black.opacity(0.62),
        cardHighlight: Color.white.opacity(0.12)
    )
}

private struct RunwayPaletteKey: EnvironmentKey {
    static let defaultValue = RunwayPalette.light
}

extension EnvironmentValues {
    var runway: RunwayPalette {
        get { self[RunwayPaletteKey.self] }
        set { self[RunwayPaletteKey.self] = newValue }
    }
}

enum Runway {
    static let cardRadius: CGFloat = 16
    static let railWidth: CGFloat = 240
    static let sidebarIdeal: CGFloat = 220

    static let cream = Color(red: 0.97, green: 0.95, blue: 0.90)
    static let mascotInk = Color(red: 0.10, green: 0.10, blue: 0.11)

    static let spring = Animation.interpolatingSpring(stiffness: 260, damping: 26)
    static let softSpring = Animation.interpolatingSpring(stiffness: 180, damping: 22)
    static let depthEase = Animation.timingCurve(0.215, 0.61, 0.355, 1, duration: 0.7)

    static func palette(dark: Bool) -> RunwayPalette {
        dark ? .dark : .light
    }
}

struct PaperSurface: View {
    @Environment(\.runway) private var runway

    var body: some View {
        runway.canvas.ignoresSafeArea()
    }
}

struct RunwayCard<Content: View>: View {
    var padding: CGFloat = 20
    var tinted: Bool = false
    @ViewBuilder var content: () -> Content
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(tinted ? runway.field : runway.card, in: RoundedRectangle(cornerRadius: Runway.cardRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Runway.cardRadius, style: .continuous)
                    .strokeBorder(runway.hairline, lineWidth: 1)
            )
            .shadow(color: runway.liftShadow, radius: hovering ? 16 : 8, y: hovering ? 6 : 3)
            .offset(y: hovering && !reduceMotion ? -1 : 0)
            .animation(reduceMotion ? nil : Runway.spring, value: hovering)
            .onHover { hovering = $0 }
    }
}

struct PaperWell<Content: View>: View {
    @Environment(\.runway) private var runway
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(12)
            .background(runway.field, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct RunwayPrimaryButton: View {
    var title: String
    var enabled: Bool = true
    var action: () -> Void
    @State private var pressed = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.body.weight(.semibold))
                .foregroundStyle(enabled ? runway.onAction : Color.secondary)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(
                    enabled ? runway.action : runway.field,
                    in: Capsule()
                )
                .scaleEffect(pressed && !reduceMotion ? 0.97 : 1)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .onLongPressGesture(minimumDuration: 0, pressing: { pressed = $0 }, perform: {})
        .animation(reduceMotion ? nil : Runway.spring, value: pressed)
    }
}

struct MetricTile: View {
    var title: String
    var value: String
    var note: String
    var emphasized: Bool = false
    var action: (() -> Void)? = nil
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: { action?() }) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.system(size: 32, weight: .semibold))
                    .foregroundStyle(.primary)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
                Text(note)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 96, alignment: .topLeading)
            .padding(18)
            .background(runway.card, in: RoundedRectangle(cornerRadius: Runway.cardRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Runway.cardRadius, style: .continuous)
                    .strokeBorder(runway.hairline, lineWidth: 1)
            )
            .shadow(color: runway.liftShadow, radius: hovering ? 14 : 6, y: hovering ? 5 : 2)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(reduceMotion ? nil : Runway.spring, value: hovering)
    }
}

struct StatusChip: View {
    enum Tone { case ready, wait, problem, quiet }

    var label: String
    var tone: Tone
    @Environment(\.runway) private var runway

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(dot)
                .frame(width: 6, height: 6)
            Text(label)
                .font(.caption)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .foregroundStyle(.secondary)
        .background(runway.field, in: Capsule())
        .accessibilityLabel(label)
    }

    private var dot: Color {
        switch tone {
        case .ready: runway.plus
        case .wait: Color.secondary
        case .problem: Color.orange
        case .quiet: Color.secondary.opacity(0.4)
        }
    }
}

struct GradeChip: View {
    var title: String
    var emphasized: Bool = false
    var action: () -> Void
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .background(emphasized ? runway.field : runway.card, in: Capsule())
                .overlay(Capsule().strokeBorder(runway.hairline, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct FilterPill: View {
    var title: String
    var selected: Bool
    var action: () -> Void
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline.weight(.medium))
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .foregroundStyle(selected ? runway.ink : Color.secondary)
                .background(selected ? runway.card : Color.clear, in: Capsule())
                .shadow(color: selected ? runway.liftShadow : .clear, radius: 4, y: 1)
        }
        .buttonStyle(.plain)
    }
}

enum CaptureProgress {
    static func steps(from json: String?) -> [String] {
        guard let json, let data = json.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([String].self, from: data)) ?? []
    }

    static func steps(for task: CaptureTask) -> [String] {
        let trail = steps(from: task.statusTrailJSON)
        if trail.isEmpty { return [task.userStatus] }
        if trail.last == task.userStatus { return trail }
        return trail + [task.userStatus]
    }
}

enum MasteryCopy {
    static func label(_ grade: String) -> String {
        switch grade.lowercased() {
        case "again": String(localized: "重来")
        case "hard": String(localized: "有点难")
        case "good": String(localized: "记住了")
        case "easy": String(localized: "太简单了")
        default: grade
        }
    }
}

struct ShortcutRow: View {
    var label: String
    var keys: [String]

    var body: some View {
        HStack {
            Text(label)
            Spacer()
            HStack(spacing: 4) {
                ForEach(keys, id: \.self) { key in
                    Text(key)
                        .font(.caption.monospaced())
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 5, style: .continuous))
                }
            }
        }
        .font(.subheadline)
    }
}
