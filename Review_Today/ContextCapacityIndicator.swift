import SwiftUI

/// Request accounting, not cumulative billing or an estimate of the unsent draft.
struct ContextCapacityPresentation {
    let used: Int?
    let window: Int?
    let budget: Int?
    let reserve: Int?
    let threshold: Int?
    var limit: Int? { budget ?? window.flatMap { value in reserve.flatMap { value > $0 ? value - $0 : nil } } }

    init(json: String?) {
        let data = ConversationProcessor.object(json)
        used = (data?["input_tokens"] as? Int).flatMap { $0 >= 0 ? $0 : nil }
        window = (data?["model_window"] as? Int).flatMap { $0 > 0 ? $0 : nil }
        budget = (data?["input_budget"] as? Int).flatMap { $0 > 0 ? $0 : nil }
        threshold = (data?["compact_threshold"] as? Int).flatMap { $0 > 0 ? $0 : nil }
        reserve = (data?["output_reserve"] as? Int).flatMap { $0 >= 0 ? $0 : nil }
    }

    var fraction: Double? {
        guard let used, let limit else { return nil }
        return min(1, max(0, Double(used) / Double(limit)))
    }
    var headline: String {
        guard let used else { return String(localized: "尚无请求") }
        return String(localized: "约 \(Self.compact(used)) / \(limit.map(Self.compact) ?? String(localized: "上限未知"))")
    }
    var detail: String {
        guard let used else { return String(localized: "发送后显示最近一次请求的上下文用量。未发送草稿不计入。") }
        var lines = [String(localized: "最近一次请求约 \(used.formatted()) token。")]
        if let window { lines.append(String(localized: "模型窗口上限：\(window.formatted()) token。")) }
        else { lines.append(String(localized: "模型窗口上限未知；活动上限按本地预算计算。")) }
        if let budget { lines.append(String(localized: "活动输入上限：\(budget.formatted()) token。")) }
        if limit == nil { lines.append(String(localized: "这条记录未提供有效活动上限，暂不显示占比。")) }
        if let threshold { lines.append(String(localized: "约 \(threshold.formatted()) token 时整理较早上下文。")) }
        if let reserve { lines.append(String(localized: "回答预留：\(reserve.formatted()) token。")) }
        lines.append(String(localized: "用量为估算；上下文整理后可能减少，不代表全部历史大小。"))
        return lines.joined(separator: "\n")
    }
    static func compact(_ value: Int) -> String {
        if value >= 1_000_000 { return String(format: "%.1fM", Double(value) / 1_000_000) }
        if value >= 1_000 { return value % 1_000 == 0 ? "\(value / 1_000)K" : String(format: "%.1fK", Double(value) / 1_000) }
        return value.formatted()
    }
}

struct ContextCapacityIndicator: View {
    let capacity: ContextCapacityPresentation
    @Environment(\.runway) private var runway
    @Environment(\.accessibilityReduceMotion) private var reduced
    @State private var expanded = false
    @State private var hovering = false
    @FocusState private var focused: Bool

    var body: some View {
        Button { expanded.toggle() } label: {
            ZStack {
                Circle().strokeBorder(.secondary.opacity(0.18), lineWidth: 2.5)
                if let fraction = capacity.fraction, fraction > 0 {
                    Circle().trim(from: 0, to: fraction)
                        .stroke(runway.decorativeAccent, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                        .padding(1.25).rotationEffect(.degrees(-90))
                } else if capacity.used != nil && capacity.limit == nil {
                    Text("?").font(.system(size: 10, weight: .medium)).foregroundStyle(.secondary)
                }
            }.frame(width: 18, height: 18).frame(width: 28, height: 28)
        }
        .buttonStyle(InteractionButtonStyle(focused: focused, padding: 2))
        .focusable().focused($focused).focusEffectDisabled()
        .onHover { hovering = $0 }
        .onDisappear { hovering = false; expanded = false }
        .animation(reduced ? nil : .easeOut(duration: 0.18), value: capacity.fraction)
        .overlay(alignment: .bottom) {
            if (hovering || focused) && !expanded {
                Text(capacity.headline).font(.callout.monospacedDigit())
                    .foregroundStyle(.white).padding(.horizontal, 10).padding(.vertical, 7)
                    .background(Color(white: 0.14), in: RoundedRectangle(cornerRadius: 10))
                    .fixedSize().offset(y: -36).allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
        }
        .zIndex(1)
        .popover(isPresented: $expanded, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 8) {
                Text("上下文窗口").font(.headline)
                Text(capacity.headline).monospacedDigit()
                Text(capacity.detail).font(.caption).foregroundStyle(.secondary)
            }.padding(16).frame(width: 280, alignment: .leading)
        }
        .accessibilityLabel("上下文窗口")
        .accessibilityValue(capacity.detail)
        .accessibilityHint("查看上下文用量与上限")
    }
}

struct MemoryExcludedMark: View {
    var body: some View {
        Image(systemName: "brain").font(.system(size: 12))
            .overlay {
                Rectangle().frame(width: 19, height: 1.5).rotationEffect(.degrees(-45))
            }
            .frame(width: 18, height: 18).foregroundStyle(.secondary)
            .help("已关闭跨会话记忆；可在会话操作中重新允许")
            .accessibilityLabel("已关闭跨会话记忆")
    }
}
