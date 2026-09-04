import SwiftUI

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
            .buttonStyle(.plain)
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
    @State private var pulse = false
    private var running: Bool { ["running", "adjusting"].contains(run.status) && run.startedAt != nil }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Circle().fill(run.errorCode == nil ? runway.agent : .orange)
                .frame(width: 6, height: 6)
                .opacity(running && !reduceMotion && pulse ? 0.35 : 1)
                .animation(running && !reduceMotion ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true) : nil, value: pulse)
                .onAppear { pulse = true }
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
