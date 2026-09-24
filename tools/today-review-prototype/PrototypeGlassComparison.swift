import SwiftUI

/// Two real-size entry pairs in an isolated native window. The left side stays identical to
/// the current prototype; the right side tests light that reacts to the pointer itself.
struct PrototypeGlassComparison: View {
    @Bindable var model: PrototypeState
    @Environment(\.runway) private var palette
    @State private var lastAction = ""
    @State private var previewPoint = 2

    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width < 960
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    header
                    HStack(spacing: 12) {
                        Text("定点预选").font(.caption).foregroundStyle(.secondary)
                        Picker("定点预选", selection: $previewPoint) {
                            Text("关闭").tag(0)
                            Text("左缘").tag(1)
                            Text("中部").tag(2)
                            Text("右缘").tag(3)
                        }
                        .pickerStyle(.segmented).labelsHidden().frame(width: 320)
                        Text("可复现定格效果；真实指针仍可直接悬停。")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if compact {
                        VStack(spacing: 16) { currentPanel; proposedPanel }
                    } else {
                        HStack(alignment: .top, spacing: 16) { currentPanel; proposedPanel }
                    }
                    HStack(spacing: 8) {
                        Image(systemName: "cursorarrow.rays")
                        Text("把指针缓慢移过两张入口、停住，再离开比较。点击只验证按下反馈，不会进入真实流程。")
                    }
                    .font(.caption).foregroundStyle(.secondary)
                    if !lastAction.isEmpty {
                        Text(lastAction).font(.caption).foregroundStyle(palette.ink)
                    }
                }
                .frame(maxWidth: 1120, alignment: .leading)
                .padding(32)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .accessibilityIdentifier("glass-comparison")
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 20) {
            VStack(alignment: .leading, spacing: 8) {
                Text("入口玻璃 · 原生对照").font(.system(size: 29, weight: .semibold))
                Text("相同尺寸与内容，只比较悬停时玻璃如何响应。")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            VStack(alignment: .trailing, spacing: 10) {
                Toggle("深色", isOn: $model.dark).toggleStyle(.switch)
                Toggle("减少动态", isOn: $model.reduced).toggleStyle(.switch)
            }.font(.caption)
        }
    }

    private var currentPanel: some View {
        panel(title: "当前入口", number: "01", description: "整块扫光与沿边缘循环的光点") {
            PrototypeGlassEntry(title: "开始学习", detail: "从一个问题，或一份材料开始", symbol: "sparkle", previewSelected: previewPoint != 0) { tapped("当前入口 · 开始学习") }
            PrototypeGlassEntry(title: "模拟考", detail: "知识测验 · 模拟面试", symbol: "checklist", previewSelected: previewPoint != 0) { tapped("当前入口 · 模拟考") }
        }
    }

    private var proposedPanel: some View {
        panel(title: "B · 玻璃反光试作", number: "02", description: "反光跟随指针，仅在边缘加强折射") {
            PointerGlassEntry(title: "开始学习", detail: "从一个问题，或一份材料开始", symbol: "sparkle", previewPoint: samplePoint) { tapped("试作 · 开始学习") }
            PointerGlassEntry(title: "模拟考", detail: "知识测验 · 模拟面试", symbol: "checklist", previewPoint: samplePoint) { tapped("试作 · 模拟考") }
        }
    }

    private func panel<Content: View>(title: String, number: String, description: String,
                                       @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.system(size: 18, weight: .semibold))
                Spacer()
                Text(number).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            Text(description).font(.caption).foregroundStyle(.secondary)
            VStack(spacing: 16, content: content)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(palette.card.opacity(0.48), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(palette.hairline, lineWidth: 1))
    }

    private func tapped(_ label: String) { lastAction = "已触发模拟点击：\(label)" }
    private var samplePoint: UnitPoint? {
        switch previewPoint {
        case 1: .init(x: 0.08, y: 0.40)
        case 2: .init(x: 0.50, y: 0.25)
        case 3: .init(x: 0.92, y: 0.40)
        default: nil
        }
    }
}

/// The experiment keeps the same native glass material and entry geometry. It has no clock:
/// light and inner-edge caustics respond only to pointer position, focus and press.
private struct PointerGlassEntry: View {
    let title: String
    let detail: String
    let symbol: String
    let previewPoint: UnitPoint?
    let action: () -> Void

    @Environment(\.runway) private var palette
    @Environment(\.colorScheme) private var scheme
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.accessibilityReduceTransparency) private var opaque
    @Environment(\.controlActiveState) private var controlState
    @FocusState private var focused: Bool
    @ObservedObject private var input = InteractionInputMode.shared
    @State private var hovering = false
    @State private var pointer = UnitPoint(x: 0.5, y: 0.32)
    @State private var entrySize = CGSize(width: 460, height: 84)

    private var shape: RoundedRectangle { .init(cornerRadius: Runway.chipRadius, style: .continuous) }
    private var keyboard: Bool { focused && input.keyboardNavigation }
    private var selected: Bool { (controlState == .key && (hovering || keyboard)) || previewPoint != nil }
    private var activePoint: UnitPoint { reduced || keyboard ? .init(x: 0.28, y: 0.24) : hovering ? pointer : previewPoint ?? pointer }
    private var dark: Bool { scheme == .dark }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: symbol).font(.system(size: 19, weight: .medium)).frame(width: 26)
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.headline).underline(keyboard)
                    Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 12, weight: selected ? .bold : .medium))
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
        .buttonStyle(PointerGlassPressStyle(reduced: reduced))
        .focusable().focusEffectDisabled().focused($focused)
        .onKeyPress(keys: [.return, .space], phases: .down) { _ in
            guard focused else { return .ignored }; action(); return .handled
        }
        .onContinuousHover { phase in
            switch phase {
            case .active(let location):
                hovering = true
                if !reduced {
                    pointer = UnitPoint(x: min(1, max(0, location.x / max(1, entrySize.width))),
                                        y: min(1, max(0, location.y / max(1, entrySize.height))))
                }
            case .ended: hovering = false
            }
        }
        .onHover { hovering = $0 }
        .onGeometryChange(for: CGSize.self) { $0.size } action: { entrySize = $0 }
        .onChange(of: controlState) { _, value in if value != .key { hovering = false } }
        .onDisappear { hovering = false }
    }

    private var glass: some View {
        ZStack {
            if opaque {
                shape.fill(palette.card)
            } else {
                shape.fill(.clear).glassEffect(.regular, in: shape)
                // A neutral silver glaze gives the specular light something to lift on
                // very bright paper, while the system glass remains the actual substrate.
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
            // A quiet permanent rim keeps the glass legible on the paper canvas.
            shape.inset(by: 0.7).strokeBorder(dark ? .white.opacity(0.18) : Color(white: 0.68).opacity(0.18), lineWidth: 0.8)
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

private struct PointerGlassPressStyle: ButtonStyle {
    let reduced: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed && !reduced ? 0.992 : 1)
            .animation(reduced ? nil : .easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
