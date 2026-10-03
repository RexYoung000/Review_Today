@testable import ReviewTodayContractSupport
import AppKit
import Combine
import SwiftUI

struct DictationIntegrationView: View {
    @Bindable var model: DictationIntegrationState
    @Bindable var capture: DictationIntegrationCapture
    var audit: () -> Void
    private let timer = Timer.publish(every: 0.05, on: .main, in: .common).autoconnect()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("集成验收 · 模拟声音与服务")
                    .font(.system(size: 22, weight: .semibold))
                    .fixedSize(horizontal: false, vertical: true)
                Text("正式听写面板、控制器和原生编辑器。无麦克风、无网络；草稿保存与发送只在此窗口内模拟。")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                composer
                if let message = model.controller.error ?? model.controller.notice {
                    Text(message).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
                }
                if let message = model.fixtureError { Text(message).foregroundStyle(.red) }
                options
                VStack(alignment: .leading, spacing: 6) {
                    Text("已完成保存回调：\(model.saveCount) 次")
                    Text("模拟服务调用：\(model.transport.calls.joined(separator: " → "))")
                    Text(model.editorAudit).textSelection(.enabled)
                    if let sent = model.lastSent { Text("仅模拟发送：\(sent)") }
                    Text("录屏：\(capture.message.isEmpty ? "⌘R 开始／停止；⌘S 截图" : capture.message)")
                }
                .font(.system(size: 11)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }
            .padding(18)
            .frame(maxWidth: 1036)
            .frame(maxWidth: .infinity)
        }
        .background(model.dark ? Color(white: 0.075) : Color(white: 0.965))
        .environment(\.runway, .brandMonochrome(dark: model.dark))
        .environment(\.brandTrialStill, model.reduced)
        .preferredColorScheme(model.dark ? .dark : .light)
        .tint(model.dark ? .white : .black)
        .onChange(of: model.dark) { _, dark in NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua) }
        .onReceive(timer) { model.tick($0) }
    }

    private var composer: some View {
        DictationComposerSurface(active: model.controller.busy) {
            LearningComposerInput(text: $model.draft, focusRequest: model.focusRequest,
                sessionID: model.sessionID, placeholder: "编辑合成草稿，或开始模拟听写…",
                insertion: model.controller.insertion, editable: !model.controller.busy,
                onInsertionApplied: model.acceptInsertion, onSubmit: model.send) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 12) { editorActions }
                    VStack(alignment: .leading, spacing: 10) { editorActions }
                }
                .padding(.horizontal, 8)
            }
        } status: {
            DictationComposerStatus(phase: model.panelPhase, level: model.controller.level,
                elapsed: model.controller.elapsed, error: model.controller.error,
                onCancel: model.cancel, onFinish: model.finish, onRetry: model.retry)
        }
    }

    @ViewBuilder private var editorActions: some View {
        Button(action: model.start) { Label("模拟听写", systemImage: "mic") }
            .disabled(model.controller.busy)
        if model.controller.pending {
            Button("重试听写", action: model.retry).disabled(model.controller.busy)
            Button("丢弃录音", action: model.cancel).disabled(model.controller.busy)
        }
        Button("模拟发送", action: model.send)
            .disabled(model.controller.busy || model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private var options: some View {
        VStack(alignment: .leading, spacing: 12) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 16) { appearanceOptions }
                VStack(alignment: .leading, spacing: 10) { appearanceOptions }
            }
            Toggle("下次模拟转写失败", isOn: Binding(get: { model.transport.failNext }, set: { model.transport.failNext = $0 }))
            Toggle("模拟整理失败，保留原始转写", isOn: Binding(get: { model.transport.rawFallback }, set: { model.transport.rawFallback = $0 }))
            Toggle("下次模拟保存失败", isOn: $model.failSave)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { diagnosticActions }
                VStack(alignment: .leading, spacing: 10) { diagnosticActions }
            }
        }
        .toggleStyle(.checkbox).font(.system(size: 12))
        .padding(14)
        .background(.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))
    }
    @ViewBuilder private var appearanceOptions: some View {
        Toggle("深色外观", isOn: $model.dark)
        Toggle("减少动态", isOn: $model.reduced)
        Toggle("模拟静默音量", isOn: $model.silent)
    }
    @ViewBuilder private var diagnosticActions: some View {
        Button("恢复示例草稿", action: model.resetDraft).disabled(model.controller.busy)
        Button("检查编辑器", action: audit)
    }
}
