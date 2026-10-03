import AppKit
import SwiftUI

enum AgentVoiceComposerPhase: Equatable {
    case connecting, listening, transcribing, thinking, speaking, failed
}

/// The voice coordinator owns capture, playback and turn submission. This view
/// only presents those facts, sharing the confirmed dictation material/renderer.
struct AgentVoiceComposerStatus: View {
    let phase: AgentVoiceComposerPhase
    let inputLevel: Double
    let outputLevel: Double
    let muted: Bool
    var isCapturing: Bool = false
    var statusDetail: String? = nil
    let onToggleMute: () -> Void
    let onFinishUtterance: () -> Void
    let onEnd: () -> Void

    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.colorScheme) private var colorScheme
    @State private var visible = false
    @FocusState private var focused: Action?
    private enum Action: Hashable { case mute, finishUtterance, end }

    private var level: Double {
        let raw = phase == .speaking ? outputLevel : (phase == .listening && !muted ? inputLevel : 0)
        return raw.isFinite ? max(0, min(1, raw)) : 0
    }
    private var hasWaveform: Bool { phase == .speaking || (phase == .listening && !muted) }
    private var processing: Bool { phase == .connecting || phase == .transcribing || phase == .thinking }
    private var canFinishUtterance: Bool { phase == .listening && isCapturing && !muted }
    private var animate: Bool { visible && !reduced && (processing || (hasWaveform && level > 0)) }
    private var title: String {
        switch phase {
        case .connecting: return "正在连接语音"
        case .listening: return muted ? "麦克风已静音" : isCapturing ? "正在听你说" : "正在聆听"
        case .transcribing: return "正在转写你的话"
        case .thinking: return "正在处理你的问题"
        case .speaking: return "正在播报"
        case .failed: return "语音暂不可用"
        }
    }
    private var strength: String {
        if phase == .speaking { return level < 0.018 ? "播报停顿" : level < 0.2 ? "播放声音较轻" : "正在播放声音" }
        if muted { return "麦克风已静音" }
        return level < 0.018 ? "等待声音" : level < 0.2 ? "声音较轻" : "有声音输入"
    }
    private var detail: String {
        switch phase {
        case .connecting: return "连接完成后即可说话。"
        case .listening: return muted ? "回答和播报仍可继续。" : "说完稍停，会自动提交。"
        case .transcribing: return muted ? "麦克风已静音，正在转写已提交的片段。" : "已说的话正在转成文字。"
        case .thinking: return muted ? "麦克风已静音，回答仍在继续。" : "你可以再次开口打断。"
        case .speaking: return muted ? "麦克风已静音，播报继续。" : "你可以开口打断。"
        case .failed: return "结束语音后，可以用文字继续。"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Button(action: onToggleMute) {
                    Image(systemName: muted ? "mic.slash" : "mic")
                        .font(.system(size: 15, weight: .medium))
                        .frame(width: 36, height: 36)
                        .background(.white.opacity(0.10), in: Circle())
                        .overlay(Circle().strokeBorder(focused == .mute ? .white : .clear, lineWidth: 1).padding(-3))
                }
                .buttonStyle(.plain)
                .disabled(phase == .connecting || phase == .failed)
                .focusable().focusEffectDisabled().focused($focused, equals: .mute)
                .accessibilityLabel(muted ? "取消麦克风静音" : "静音麦克风")
                .help(muted ? "恢复收音，播报不受影响" : "静音并丢弃尚未提交的语音；已提交回答和播报继续")

                VStack(alignment: .leading, spacing: 8) {
                    Text(title)
                        .font(.system(size: 13, weight: .medium))
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityValue(hasWaveform ? strength : detail)
                    if hasWaveform {
                        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !animate)) { context in
                            DictationComposerWaveform(level: level, time: context.date.timeIntervalSinceReferenceDate, reduced: reduced)
                        }
                        .frame(height: 43).accessibilityHidden(true)
                        if reduced {
                            Text(strength).font(.system(size: 11)).foregroundStyle(.white.opacity(0.7))
                        }
                    } else if processing {
                        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !animate)) { context in
                            ZStack {
                                Circle().stroke(.white.opacity(0.24), lineWidth: 2)
                                Circle().trim(from: 0, to: 0.72)
                                    .stroke(.white, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                                    .rotationEffect(.degrees(reduced ? -90 : context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.2) * 300))
                            }
                        }
                        .frame(width: 17, height: 17).padding(.vertical, 10)
                        .accessibilityHidden(true)
                    } else {
                        Image(systemName: phase == .failed ? "exclamationmark.circle" : "mic.slash")
                            .font(.system(size: 20)).padding(.vertical, 10).accessibilityHidden(true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Button(action: onEnd) {
                    Text("结束语音")
                        .font(.system(size: 13, weight: .semibold))
                        .padding(.horizontal, 14).frame(height: 38)
                        .foregroundStyle(Color(white: 0.08))
                        .background(.white, in: Capsule())
                        .overlay(Capsule().strokeBorder(focused == .end ? .white : .clear, lineWidth: 1).padding(-3))
                }
                .buttonStyle(.plain).fixedSize()
                .focusable().focusEffectDisabled().focused($focused, equals: .end)
                .keyboardShortcut(.cancelAction)
                .help("停止收音和播放，回到原文字草稿 · Esc")
            }
            HStack(alignment: .top, spacing: 12) {
                Text(detail)
                    .font(.system(size: 12)).foregroundStyle(.white.opacity(0.72))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if canFinishUtterance {
                    Button("我说完了", action: onFinishUtterance)
                        .font(.system(size: 12, weight: .medium))
                        .buttonStyle(.plain).fixedSize()
                        .focusable().focusEffectDisabled().focused($focused, equals: .finishUtterance)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .overlay(Capsule().strokeBorder(.white.opacity(focused == .finishUtterance ? 1 : 0.35), lineWidth: 1))
                        .help("提交当前已说的话，继续这次语音对话")
                }
            }
            if let statusDetail, !statusDetail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(statusDetail)
                    .font(.system(size: 12)).foregroundStyle(.white.opacity(0.82))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 18)
        .frame(maxWidth: .infinity, minHeight: 137, alignment: .leading)
        .foregroundStyle(.white)
        .background(Color(white: colorScheme == .dark ? 0.055 : 0.085), in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(.white.opacity(colorScheme == .dark ? 0.24 : 0.04), lineWidth: 1))
        .shadow(color: runway.liftShadow.opacity(0.35), radius: 8, y: 2)
        .background(DictationComposerVisibility { visible = $0 })
        .onDisappear { visible = false }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("语音对话")
    }
}
