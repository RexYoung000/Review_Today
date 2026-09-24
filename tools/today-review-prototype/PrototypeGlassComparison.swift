import SwiftUI

/// Two real-size entry pairs in an isolated native window. The left side stays identical to
/// the current prototype; the right side tests light that reacts to the pointer itself.
struct PrototypeGlassComparison: View {
    @Bindable var model: PrototypeState
    @Environment(\.runway) private var palette
    @State private var lastAction = ""
    @State private var previewPoint = 0
    @State private var previewIcon = 0

    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width < 960
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    header
                    HStack(spacing: 12) {
                        Text("定点反光预览").font(.caption).foregroundStyle(.secondary)
                        Picker("定点反光预览", selection: $previewPoint) {
                            Text("关闭").tag(0)
                            Text("左缘").tag(1)
                            Text("中部").tag(2)
                            Text("右缘").tag(3)
                        }
                        .pickerStyle(.segmented).labelsHidden().frame(width: 320)
                        Text("此处只预览静态反光位置；图标循环可在下方单独预览。")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    HStack(spacing: 12) {
                        Text("图标循环预览").font(.caption).foregroundStyle(.secondary)
                        Picker("图标循环预览", selection: $previewIcon) {
                            Text("关闭").tag(0)
                            Text("学习星芒").tag(1)
                            Text("模拟考勾选").tag(2)
                        }
                        .pickerStyle(.segmented).labelsHidden().frame(width: 320)
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
        panel(title: "旧版对照", number: "01", description: "整块扫光与沿边缘循环的光点") {
            PrototypeGlassEntry(title: "开始学习", detail: "从一个问题，或一份材料开始", symbol: "sparkle", previewSelected: previewPoint != 0) { tapped("当前入口 · 开始学习") }
            PrototypeGlassEntry(title: "模拟考", detail: "知识测验 · 模拟面试", symbol: "checklist", previewSelected: previewPoint != 0) { tapped("当前入口 · 模拟考") }
        }
    }

    private var proposedPanel: some View {
        panel(title: "现用入口 · 图标 Spine", number: "02", description: "悬停时星芒闪烁，或由完整的模拟考图标接替静态图标；移开立即停播") {
            TodayEntryPair(horizontal: false, previewPoint: samplePoint,
                           previewKind: previewIcon == 1 ? .learning : previewIcon == 2 ? .exam : nil,
                           onLearn: { tapped("试作 · 开始学习") },
                           onExam: { tapped("试作 · 模拟考") })
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
