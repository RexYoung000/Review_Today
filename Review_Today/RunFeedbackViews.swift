import SwiftUI

/// Logical selection changes immediately; only the tiny glyph settles afterward.
struct SelectionDot: View {
    var selected: Bool
    var delay: Double
    @Environment(\.accessibilityReduceMotion) private var reduced
    @State private var scale = 1.0
    @State private var initialized = false
    var body: some View {
        Image(systemName: selected ? "checkmark.circle.fill" : "circle")
            .scaleEffect(reduced ? 1 : scale)
            .task(id: selected) {
                defer { initialized = true }
                guard initialized && selected && !reduced else { scale = 1; return }
                scale = 0.65
                try? await Task.sleep(for: .milliseconds(min(90, max(0, delay * 1000))))
                guard !Task.isCancelled else { return }
                withAnimation(.spring(response: 0.22, dampingFraction: 0.7)) { scale = 1 }
            }
            .accessibilityLabel(selected ? "已选择" : "未选择")
    }
}

struct RunDetails<Content: View>: View {
    var title = "运行详情"
    @ViewBuilder var content: () -> Content
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button { expanded.toggle() } label: {
                HStack(spacing: 6) {
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 10, weight: .semibold)).frame(width: 12)
                    Text(title).font(.caption)
                    Spacer(minLength: 0)
                }
                .foregroundStyle(.secondary)
                .padding(.vertical, 7)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(InteractionButtonStyle(padding: 2))
            .accessibilityLabel(title)
            .accessibilityValue(expanded ? "已展开" : "已收起")
            .help(expanded ? "收起运行详情" : "展开运行详情")
            if expanded { content() }
        }
    }
}

/// Only this small component observes the clock. Transcript layout has no timer.
struct RunPhaseLine: View {
    var run: AgentRun
    @Environment(\.runway) private var runway
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var running: Bool { ["running", "adjusting"].contains(run.status) && run.startedAt != nil }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            if running {
                DotsRing(color: runway.agent, reduced: reduceMotion).frame(width: 18, height: 18)
            } else {
                Circle().fill(run.errorCode == nil ? runway.agent : .orange).frame(width: 6, height: 6)
            }
            StageSummary(text: run.userSummary, animate: running && !reduceMotion)
            if running {
                TimelineView(.periodic(from: .now, by: 1)) { tick in
                    Text("\(max(0, Int(tick.date.timeIntervalSince(run.startedAt ?? tick.date)))) 秒")
                        .monospacedDigit().foregroundStyle(.secondary)
                }
            } else if run.elapsedMS > 0 {
                Text(String(format: "%.1f 秒", Double(run.elapsedMS) / 1000)).monospacedDigit().foregroundStyle(.secondary)
            }
        }
        .font(.caption)
        .foregroundStyle(run.errorCode == nil ? runway.agent : .orange)
    }
}

/// An execution indicator, never a percentage or an invented stream of thought.
struct DotsRing: View {
    let color: Color
    let reduced: Bool
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduced)) { timeline in
            Canvas { context, size in
                let time = timeline.date.timeIntervalSinceReferenceDate
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                for index in 0..<8 {
                    let angle = Double(index) * .pi / 4 - .pi / 2
                    let wave = reduced ? 1 : (cos((time - Double(index) * 0.15) * 2 * .pi / 1.5) + 1) / 2
                    let diameter = 2 + wave
                    let point = CGPoint(x: center.x + cos(angle) * 6.5, y: center.y + sin(angle) * 6.5)
                    let rect = CGRect(x: point.x - diameter / 2, y: point.y - diameter / 2, width: diameter, height: diameter)
                    context.fill(Path(ellipseIn: rect), with: .color(color.opacity(0.3 + 0.7 * wave)))
                }
            }
        }.accessibilityHidden(true)
    }
}

private struct StageSummary: View {
    var text: String
    var animate: Bool
    @State private var shown = ""
    @State private var initialized = false
    var body: some View {
        Text(initialized ? shown : text)
            .fixedSize(horizontal: false, vertical: true)
            .task(id: text) {
                let previous = initialized
                initialized = true
                guard animate && previous else { shown = text; return }
                let characters = Array(text)
                let stride = max(1, characters.count / 12)
                shown = ""
                for count in Swift.stride(from: stride, through: characters.count + stride, by: stride) {
                    if Task.isCancelled { return }
                    shown = String(characters.prefix(count))
                    try? await Task.sleep(for: .milliseconds(12))
                }
            }
            .onChange(of: animate) { _, active in if !active { shown = text } }
            .accessibilityLabel(text)
    }
}
