#if DEBUG
import SwiftUI

/// Explicit local verification surface, isolated from sessions and recording.
struct MascotMotionPreview: View {
    @State private var phase: MascotPhase = .idle
    @State private var level = 0.65
    @State private var reduced = false
    @State private var slow = false
    @State private var dark = false
    @State private var sampleRun = AgentRun(id: UUID(), sessionID: UUID())
    @Environment(\.runway) private var runway
    @Environment(\.accessibilityReduceMotion) private var systemReduced
    private var palette: RunwayPalette { dark ? .dark : .light }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("已确认动效 · App 内验证").font(.title2.weight(.semibold))
            Text("四态为模拟演示；未开启麦克风，不发送消息。日常界面的环绕动画由真实运行状态驱动。")
                .font(.callout).foregroundStyle(.secondary)
            HStack(spacing: 24) {
                VStack {
                    Text("运行标识").font(.caption)
                    MascotMotion(phase: phase == .thinking ? .thinking : .idle, reduced: reduced || systemReduced, rate: slow ? 0.5 : 1)
                        .frame(width: 160, height: 140)
                    RunPhaseLine(run: sampleRun, reducedOverride: reduced || systemReduced)
                }
                VStack {
                    Text("语音组件 · 模拟状态").font(.caption)
                    MascotMotion(surface: .voice, phase: phase, level: level, reduced: reduced || systemReduced, rate: slow ? 0.5 : 1)
                        .frame(maxWidth: .infinity).frame(height: 160)
                    MascotMotion(surface: .voice, phase: phase, level: level, reduced: reduced || systemReduced, rate: slow ? 0.5 : 1)
                        .frame(width: 240, height: 90)
                }.frame(maxWidth: .infinity)
            }
            HStack {
                ForEach(MascotPhase.allCases, id: \.self) { item in
                    Button(item.title) { phase = item }.buttonStyle(.bordered).tint(phase == item ? palette.agent : .secondary)
                }
            }
            HStack { Text("模拟声量"); Slider(value: $level, in: 0...1).accessibilityLabel("模拟声量"); Text("\(Int(level * 100))%").monospacedDigit() }
            HStack { Toggle("减少动态效果", isOn: $reduced); Toggle("半速", isOn: $slow); Toggle("深色", isOn: $dark) }
            Text("每次演示最多 20 秒；停止后收敛，后台暂停。语音转文字与真实语音会话留待下一轮。")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(24).frame(minWidth: 620, minHeight: 460)
        .background(palette.canvas).foregroundStyle(palette.ink)
        .environment(\.runway, palette)
        .environment(\.colorScheme, dark ? .dark : .light)
        .onAppear { sampleRun.status = "completed"; sampleRun.userSummary = "模拟 · 未运行" }
        .task(id: phase) {
            sampleRun.status = phase == .thinking ? "running" : "completed"
            sampleRun.startedAt = phase == .thinking ? .now : nil
            sampleRun.userSummary = phase == .thinking ? "模拟 · 正在运行" : "模拟 · 未运行"
            guard phase != .idle else { return }
            try? await Task.sleep(for: .seconds(20))
            guard !Task.isCancelled else { return }
            phase = .idle
        }
    }
}
#endif
