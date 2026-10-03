@testable import ReviewTodayContractSupport
import AppKit
import SwiftUI

struct AgentVoiceIntegrationView: View {
    @Bindable var model: AgentVoiceIntegrationState
    @Bindable var capture: AgentVoiceIntegrationCapture
    var audit: () -> Void
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("同一聊天 · 连续语音集成验收").font(.system(size: 22, weight: .semibold))
                Text("正式音频状态机、协调器、面板与编辑器；模拟输入、转写和播报完成回调。无麦克风、网络、模型或扬声器播放。")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                composer
                options
                Text("已提交 \(model.turn) 轮 · 原草稿\(model.draft == model.originalDraft ? "保留" : "已编辑")")
                    .font(.system(size: 12, weight: .medium))
                ForEach(model.messages, id: \.id) { message in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(message.role == "user" ? "你 · 模拟语音" : "Agent · 脚本回复")
                            .font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                        Text(message.content.isEmpty ? "正在生成脚本回复…" : message.content).font(.system(size: 14))
                        if let record = model.playback[message.id] {
                            Text(record.caption).font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                    }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(.primary.opacity(message.role == "user" ? 0.07 : 0.035), in: RoundedRectangle(cornerRadius: 12))
                }
                Text(model.editorAudit).font(.system(size: 10)).foregroundStyle(.secondary).textSelection(.enabled)
                Text(model.exportStatus).font(.system(size: 11)).foregroundStyle(.secondary)
                Text("录屏：\(capture.message.isEmpty ? "⌘R 开始／停止，⌘S 截图" : capture.message)")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }.padding(18).frame(maxWidth: 1036).frame(maxWidth: .infinity)
        }
        .background(model.dark ? Color(white: 0.075) : Color(white: 0.965))
        .environment(\.runway, .brandMonochrome(dark: model.dark))
        .environment(\.brandTrialStill, model.reduced)
        .preferredColorScheme(model.dark ? .dark : .light)
        .tint(model.dark ? .white : .black)
        .onChange(of: model.dark) { _, dark in NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua) }
    }
    private var composer: some View {
        DictationComposerSurface(active: model.voice.active) {
            LearningComposerInput(text: $model.draft, focusRequest: model.focusRequest, sessionID: model.owner,
                placeholder: "原草稿保留；语音提交不清空这里", insertion: nil, editable: !model.voice.active,
                onInsertionApplied: { _ in }, onSubmit: {}) {
                Button("开始模拟语音对话", action: model.start).disabled(model.voice.active)
            }
        } status: {
            AgentVoiceComposerStatus(phase: model.voice.phase, inputLevel: model.voice.audio.inputLevel,
                outputLevel: model.voice.audio.outputLevel, muted: model.voice.audio.muted,
                isCapturing: model.voice.audio.capturingSpeech, statusDetail: model.voice.statusDetail,
                onToggleMute: model.toggleMute, onFinishUtterance: model.voice.audio.finishUtterance, onEnd: model.end)
        }
    }
    private var options: some View {
        VStack(alignment: .leading, spacing: 12) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { voiceActions }
                VStack(alignment: .leading, spacing: 10) { voiceActions }
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { automaticActions }
                VStack(alignment: .leading, spacing: 10) { automaticActions }
            }
            if !model.automaticStatus.isEmpty {
                Text(model.automaticStatus).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { appearance }
                VStack(alignment: .leading, spacing: 10) { appearance }
            }
            HStack(spacing: 12) {
                Button("检查编辑器", action: audit)
                Button("导出运行记录", action: model.export)
            }
        }.font(.system(size: 12)).toggleStyle(.checkbox)
            .padding(14).background(.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))
    }
    @ViewBuilder private var voiceActions: some View {
        Button(model.nextTitle) { model.speak() }.disabled(!model.canSpeak || model.automaticTesting)
        Button("模拟开口打断") { model.speak(interrupt: true) }.disabled(!model.canSpeak || model.automaticTesting)
        Button("模拟连接失败", action: model.fail).disabled(!model.voice.audio.connected)
    }
    @ViewBuilder private var automaticActions: some View {
        Button("自动验证播报中打断") { model.verifyDuringPlayback(mute: false) }
            .disabled(!model.canSpeak || model.automaticTesting)
        Button("自动验证播报中静音") { model.verifyDuringPlayback(mute: true) }
            .disabled(!model.canSpeak || model.automaticTesting)
    }
    @ViewBuilder private var appearance: some View {
        Toggle("深色外观", isOn: $model.dark)
        Toggle("减少动态", isOn: $model.reduced)
    }
}
