import AppKit
import SwiftUI

/// Standalone comparison. The neutral surface values mirror BrandMaterialTrial;
/// waveform sizes and silver illumination are proposals for visual acceptance.
struct DictationDemoView: View {
    @Bindable var model: DictationDemoState
    @Bindable var capture: DictationDemoCapture
    @Environment(\.accessibilityReduceMotion) private var systemReduced
    @State private var dark = false
    @State private var reduced = false
    @State private var time = Date.now
    @State private var activeComposer = "A"
    @FocusState private var focusedDraft: String?
    private let timer = Timer.publish(every: 0.05, on: .main, in: .common).autoconnect()
    private var ink: Color { dark ? Color(white: 0.96) : Color(white: 0.10) }
    private var canvas: Color { dark ? Color(white: 0.075) : Color(white: 0.965) }
    private var still: Bool { reduced || systemReduced }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header
                context
                VStack(spacing: 24) {
                    comparison(glow: false, index: "A", title: "纯黑白声波", subtitle: "清楚、直接，专注声音的起伏。")
                    comparison(glow: true, index: "B", title: "声波 + 银白柔光", subtitle: "相同声波，声音越强，局部光感越明显。")
                }
                controls
                HStack(spacing: 6) {
                    Image(systemName: "info.circle")
                    Text("独立原生小样 · 两版共用模拟声音与草稿 · 不使用麦克风、不联网")
                    Spacer()
                    if capture.recording { Text("正在录制界面").foregroundStyle(.red) }
                }
                .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            .padding(32)
            .frame(maxWidth: 1120)
            .frame(maxWidth: .infinity)
        }
        .background(canvas)
        .foregroundStyle(ink)
        .preferredColorScheme(dark ? .dark : .light)
        .tint(ink)
        .onReceive(timer) { date in
            guard NSApp.isActive, model.phase == .recording else { return }
            time = date; model.tick(date: date)
        }
        .onExitCommand { model.cancel() }
        .onChange(of: model.phase) { _, phase in
            focusedDraft = phase == .idle ? activeComposer : nil
        }
        .onChange(of: dark) { _, value in NSApp.appearance = NSAppearance(named: value ? .darkAqua : .aqua) }
        .onDisappear { model.cancel() }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 7) {
                Text("听写，清楚一点。")
                    .font(.system(size: 27, weight: .semibold))
                Text("说话 → 完成听写 → 编辑草稿 → 发送")
                    .font(.system(size: 13)).foregroundStyle(.secondary)
            }
            Spacer()
            Text("动效对照 / 01")
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(.secondary).padding(.top, 8)
        }
    }

    private var context: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "text.bubble")
                .font(.system(size: 17)).frame(width: 30, height: 30)
            VStack(alignment: .leading, spacing: 5) {
                Text("今天想怎样复习？说说你的安排。")
                    .font(.system(size: 15, weight: .medium))
                Text(model.lastSent == nil ? "点击任意一版的麦克风，比较同一段声音的反馈。" : "模拟已发送：\(model.lastSent ?? "")")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
    }

    private func comparison(glow: Bool, index: String, title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .center, spacing: 10) {
                Text(index).font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .frame(width: 23, height: 23)
                    .background(ink.opacity(0.07), in: RoundedRectangle(cornerRadius: 7))
                Text(title).font(.system(size: 14, weight: .semibold))
                Text(subtitle).font(.system(size: 11)).foregroundStyle(.secondary)
                    .lineLimit(1).minimumScaleFactor(0.9)
                Spacer(minLength: 0)
            }
            .frame(height: 24)
            .foregroundStyle(ink)
            .drawingGroup()
            if model.phase == .idle {
                draftComposer(index: index)
            } else {
                voiceComposer(glow: glow)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("方案\(index)：\(title)")
    }

    private func draftComposer(index: String) -> some View {
        VStack(spacing: 8) {
            ZStack(alignment: .topLeading) {
                if model.draft.isEmpty {
                    Text("输入回答，或用听写说出你的想法…")
                        .font(.system(size: 15)).foregroundStyle(.secondary)
                        .padding(.leading, 5).padding(.top, 7)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $model.draft)
                    .font(.system(size: 15))
                    .scrollContentBackground(.hidden)
                    .accessibilityLabel("方案\(index)草稿")
                    .focused($focusedDraft, equals: index)
                    .frame(height: 57)
            }
            HStack(spacing: 12) {
                if let notice = model.notice {
                    Label(notice, systemImage: "checkmark.circle")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                } else {
                    Text("完成听写后，文字会出现在这里")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Button(action: { activeComposer = index; model.start() }) {
                    Image(systemName: "mic.fill").font(.system(size: 16))
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.plain).help("开始听写 · ⌘D")
                .accessibilityLabel("开始听写 \(index)")
                Button(action: model.send) {
                    Image(systemName: "arrow.up").font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? ink.opacity(0.25) : canvas)
                        .frame(width: 36, height: 36)
                        .background(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? ink.opacity(0.06) : ink, in: Circle())
                }
                .buttonStyle(.plain).disabled(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help("模拟发送；不会连接任何服务")
                .accessibilityLabel("模拟发送 \(index)")
            }
        }
        .padding(18)
        .background(dark ? Color(white: 0.125) : .white, in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(ink.opacity(0.18), lineWidth: 1))
    }

    private func voiceComposer(glow: Bool) -> some View {
        let recording = model.phase == .recording
        let failed = model.phase == .failed
        let level = model.level(at: model.elapsed)
        return HStack(spacing: 20) {
            Button(action: model.cancel) {
                Image(systemName: "xmark").font(.system(size: 13, weight: .medium))
                    .frame(width: 34, height: 34)
                    .background(Color.white.opacity(0.09), in: Circle())
            }
            .buttonStyle(.plain).help(failed ? "丢弃本次听写，保留原草稿" : "取消听写，保留原草稿 · Esc")
            .accessibilityLabel(failed ? "丢弃听写" : "取消听写")

            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 8) {
                    Text(statusTitle).font(.system(size: 13, weight: .medium))
                    if recording {
                        Text(elapsedText).font(.system(size: 12, design: .monospaced))
                            .monospacedDigit().foregroundStyle(.white.opacity(0.65))
                        Spacer(minLength: 4)
                        if model.elapsed >= 240 {
                            Text("剩余 \(max(0, 300 - Int(model.elapsed))) 秒").font(.system(size: 11))
                        } else if still {
                            Text(level < 0.018 ? "等待声音" : level < 0.2 ? "声音较轻" : "有声音输入")
                                .font(.system(size: 11)).foregroundStyle(.white.opacity(0.65))
                        }
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(statusTitle)
                .accessibilityValue(recording ? "已录 \(Int(model.elapsed)) 秒，\(level < 0.018 ? "等待声音" : level < 0.2 ? "声音较轻" : "有声音输入")\(model.elapsed >= 240 ? "，剩余 \(max(0, 300 - Int(model.elapsed))) 秒" : "")" : "")
                if recording {
                    DictationWaveform(level: level, time: time.timeIntervalSinceReferenceDate, glow: glow, reduced: still)
                        .frame(height: 43)
                        .accessibilityHidden(true)
                } else {
                    HStack(spacing: 10) {
                        if failed {
                            Image(systemName: "exclamationmark.circle")
                                .font(.system(size: 19))
                        } else if still {
                            Image(systemName: "ellipsis").font(.system(size: 19))
                        } else {
                            TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
                                Circle().trim(from: 0, to: 0.7)
                                    .stroke(.white.opacity(0.8), style: StrokeStyle(lineWidth: 1.7, lineCap: .round))
                                    .rotationEffect(.degrees(timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1) * 360))
                            }
                            .frame(width: 14, height: 14).accessibilityHidden(true)
                        }
                        Text(failed ? "本次听写已保留，可重试或丢弃。" : "完成后添加到草稿，由你确认发送。")
                            .font(.system(size: 12)).foregroundStyle(.white.opacity(0.70))
                    }
                    .frame(height: 43, alignment: .leading)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if recording || failed {
                Button(action: { if failed { model.retry() } else { model.finish() } }) {
                    Label(failed ? "重试" : "完成听写", systemImage: failed ? "arrow.clockwise" : "checkmark")
                        .font(.system(size: 13, weight: .semibold))
                        .padding(.horizontal, 14).frame(height: 38)
                        .foregroundStyle(Color(white: 0.08))
                        .background(.white, in: Capsule())
                }
                .buttonStyle(.plain).fixedSize()
                .help(failed ? "使用同一次模拟听写重试" : "停止收音并转成草稿，不会发送 · ⌘Return")
            }
        }
        .padding(.horizontal, 22).frame(height: 137)
        .foregroundStyle(.white)
        .background(Color(white: dark ? 0.055 : 0.085), in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(Color.white.opacity(dark ? 0.24 : 0.04), lineWidth: 1))
    }

    private var statusTitle: String {
        switch model.phase {
        case .recording: return "正在听写"
        case .transcribing: return "正在转成文字…"
        case .cleaning: return "正在整理文字…"
        case .failed: return "暂时无法转成文字"
        case .idle: return ""
        }
    }
    private var elapsedText: String {
        String(format: "%d:%02d", Int(model.elapsed) / 60, Int(model.elapsed) % 60)
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 16) {
                Text("比较条件").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                Picker("模拟声音", selection: $model.signal) {
                    ForEach(DictationDemoState.Signal.allCases, id: \.self) { signal in Text(signal.rawValue).tag(signal) }
                }
                .labelsHidden().accessibilityLabel("模拟声音")
                .pickerStyle(.segmented).frame(maxWidth: 280)
                Spacer(minLength: 8)
                Button("重置小样", action: model.reset).font(.system(size: 12))
            }
            HStack(spacing: 20) {
                Toggle("深色外观", isOn: $dark)
                Toggle("减少动态", isOn: $reduced)
                Toggle("下次转写失败", isOn: $model.failNext)
                Spacer(minLength: 0)
            }
            .toggleStyle(.checkbox).font(.system(size: 12))
        }
        .padding(16)
        .background(ink.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))
    }
}

private struct DictationWaveform: View {
    let level: Double
    let time: Double
    let glow: Bool
    let reduced: Bool
    var body: some View {
        GeometryReader { geometry in
            let strength = reduced ? 0.3 : level
            ZStack {
                if glow {
                    // Local silver illumination, never a full-window flashing edge.
                    Ellipse()
                        .fill(.white.opacity(reduced ? 0.08 : 0.05 + strength * 0.22))
                        .frame(width: geometry.size.width * (reduced ? 0.60 : 0.32 + strength * 0.45), height: reduced ? 20 : 8 + strength * 24)
                        .blur(radius: 15)
                    Capsule()
                        .fill(LinearGradient(colors: [.clear, .white.opacity(reduced ? 0.2 : 0.15 + strength * 0.6), .clear], startPoint: .leading, endPoint: .trailing))
                        .frame(height: 1)
                        .blur(radius: 1)
                }
                Canvas { context, size in
                    let count = max(20, min(70, Int(size.width / 8)))
                    let spacing = size.width / CGFloat(count)
                    for i in 0..<count {
                        let normalized = Double(i) / Double(count - 1)
                        let envelope = 0.3 + 0.7 * pow(sin(normalized * .pi), 0.7)
                        let oscillation = reduced ? 0.5 : 0.25 + 0.75 * abs(sin(time * 7.4 - Double(i) * 0.58) * cos(time * 3.1 + Double(i) * 0.22))
                        let height = 3 + strength * 39 * envelope * oscillation
                        let rect = CGRect(x: CGFloat(i) * spacing + (spacing - 3) / 2, y: (size.height - height) / 2, width: 3, height: height)
                        context.fill(Path(roundedRect: rect, cornerRadius: 1.5), with: .color(.white.opacity(0.4 + envelope * 0.6)))
                    }
                }
                .shadow(color: glow ? .white.opacity(reduced ? 0.12 : strength * 0.8) : .clear, radius: 5)
            }
        }
    }
}
