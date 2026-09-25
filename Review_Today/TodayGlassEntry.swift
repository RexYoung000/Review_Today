import SwiftUI

enum TodayEntryKind: String, Hashable { case learning, exam }

/// Shared native glass for Today's live entries and the isolated design comparison.
struct TodayGlassEntry: View {
    let title: String
    let detail: String
    let symbol: String
    var kind: TodayEntryKind? = nil
    var animatedIconReady = false
    var previewPoint: UnitPoint? = nil
    var onHoverChanged: ((TimeInterval?) -> Void)? = nil
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
    @State private var hoverStartedAt: TimeInterval?

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
                if hoverStartedAt == nil && enabled && controlState == .key && !reduced && !keyboard {
                    let start = Date().timeIntervalSince1970
                    hoverStartedAt = start
                    onHoverChanged?(start)
                }
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
        .onChange(of: reduced) { _, value in if value { endHover() } }
        .onChange(of: keyboard) { _, value in if value { endHover() } }
        .onDisappear { endHover() }
    }

    private var entryIcon: some View {
        Group {
            if kind == .exam {
                Image("TodayExamIcon")
                    .resizable()
                    .renderingMode(.template)
                    .foregroundStyle(palette.ink)
                    .opacity(animatedIconReady ? 0.18 : 1)
                    .frame(width: 44, height: 44)
                    // The Spine overlay disappears immediately on hover exit. Restore its
                    // static fallback in the same frame instead of inheriting the card's
                    // hover animation, which briefly leaves a pale icon behind.
                    .transaction { transaction in
                        transaction.animation = nil
                        transaction.disablesAnimations = true
                    }
            } else {
                Image(systemName: symbol)
                    .font(.system(size: 19, weight: .medium))
                    .scaleEffect(selected ? 1.12 : 1)
            }
        }
        .frame(width: 26, height: 26)
        .animation(reduced || keyboard ? nil : .spring(response: 0.28, dampingFraction: 0.7), value: selected)
        .accessibilityHidden(true) // The parent button already names the destination.
    }

    private func endHover() {
        if hoverStartedAt != nil { onHoverChanged?(nil) }
        hovering = false
        hoverStartedAt = nil
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

private struct TodayEntryFramesKey: PreferenceKey {
    static var defaultValue: [TodayEntryKind: CGRect] = [:]
    static func reduce(value: inout [TodayEntryKind: CGRect], nextValue: () -> [TodayEntryKind: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

/// Each entry has its own Spine surface so switching cards cannot expose a
/// stale mascot frame. The native symbols remain as loading/failure fallbacks.
struct TodayEntryPair: View {
    var horizontal: Bool
    var previewPoint: UnitPoint? = nil
    var previewKind: TodayEntryKind? = nil
    let onLearn: () -> Void
    let onExam: () -> Void
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.colorScheme) private var scheme
    @Environment(\.controlActiveState) private var controlState
    @State private var active: TodayEntryKind?
    @State private var start: TimeInterval = 0
    @State private var frames: [TodayEntryKind: CGRect] = [:]
    @State private var examRendererReady = false

    private var learningActive: Bool { (active ?? previewKind) == .learning }
    private var examActive: Bool { (active ?? previewKind) == .exam }

    var body: some View {
        Group {
            if horizontal { HStack(spacing: 16) { entries } }
            else { VStack(spacing: 16) { entries } }
        }
        .coordinateSpace(name: "todayEntryPair")
        .onPreferenceChange(TodayEntryFramesKey.self) { frames = $0 }
        .overlay(alignment: .topLeading) {
            GeometryReader { _ in
                if let rect = frames[.learning] {
                    MascotWebSurface(configuration: .init(surface: .recall, mode: .idle,
                                                          reduced: reduced, dark: scheme == .dark,
                                                          visible: !reduced && learningActive && controlState == .key,
                                                          // Keep the parked canvas on the star rig; otherwise
                                                          // its last frame can be the solid mascot silhouette.
                                                          header: true, entryKind: TodayEntryKind.learning.rawValue,
                                                          entryStartEpoch: start,
                                                          material: "graphite", palette: .theme(dark: scheme == .dark)),
                                     onReady: { _ in })
                        .frame(width: 44, height: 44)
                        .position(x: rect.minX + 35, y: rect.midY)
                        .opacity(!reduced && learningActive ? 1 : 0)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
                if let rect = frames[.exam] {
                    ExamEntrySpine(playing: !reduced && examActive && controlState == .key,
                                    dark: scheme == .dark,
                                    onReady: { examRendererReady = $0 })
                        .frame(width: 44, height: 44)
                        .position(x: rect.minX + 35, y: rect.midY)
                        .opacity(examRendererReady && !reduced && examActive && controlState == .key ? 1 : 0)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
            }
        }
        .onChange(of: controlState) { _, state in if state != .key { active = nil } }
        .onChange(of: reduced) { _, value in if value { active = nil } }
        .onChange(of: previewKind) { _, _ in start = Date().timeIntervalSince1970 }
        .onDisappear { active = nil; examRendererReady = false }
    }

    @ViewBuilder private var entries: some View {
        entry(.learning, title: "开始学习", detail: "从一个问题，或一份材料开始", symbol: "sparkle", action: onLearn)
        entry(.exam, title: "模拟考", detail: "知识测验 · 模拟面试", symbol: "checklist", action: onExam)
    }

    private func entry(_ kind: TodayEntryKind, title: String, detail: String, symbol: String,
                       action: @escaping () -> Void) -> some View {
        TodayGlassEntry(title: title, detail: detail, symbol: symbol, kind: kind,
                        animatedIconReady: kind == .exam && examRendererReady && !reduced && examActive && controlState == .key,
                        previewPoint: (previewKind == nil || previewKind == kind) ? previewPoint : nil,
                        onHoverChanged: { epoch in
            if let epoch { active = kind; start = epoch }
            else if active == kind { active = nil }
        },
                        action: action)
        .background {
            GeometryReader { geometry in
                Color.clear.preference(key: TodayEntryFramesKey.self,
                                       value: [kind: geometry.frame(in: .named("todayEntryPair"))])
            }
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
