import SwiftData
import SwiftUI

struct ReviewView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @Environment(\.runway) private var runway
    var coordinator: ReviewCoordinator
    @State private var controller = ReviewController()

    init(coordinator: ReviewCoordinator, controller: ReviewController? = nil) {
        self.coordinator = coordinator; _controller = State(initialValue: controller ?? ReviewController())
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "waveform").font(.title2).foregroundStyle(runway.action).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(coordinator.mode == "preview" ? "试一题 · 不计入排期" : "今日复习").font(.headline)
                    Text(controller.phase == "setup" ? "回想学过的内容，让记忆更牢固" : controller.progress).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if controller.session != nil && !["summary", "paused", "setup"].contains(controller.phase) {
                    Button("暂停") { controller.pause() }.keyboardShortcut("p", modifiers: [.command])
                }
            }.padding(24)
            Divider().opacity(0.4)
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    if controller.phase == "setup" { setup }
                    else if controller.phase == "summary" { summary }
                    else if controller.phase == "paused" { paused }
                    else if let entry = controller.entry { question(entry) }
                    if let error = controller.errorText {
                        Label(error, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange).textSelection(.enabled)
                    }
                    if !controller.records.isEmpty { records }
                }
                .frame(maxWidth: 720, alignment: .leading)
                .padding(28).frame(maxWidth: .infinity)
            }
        }
        .background(PaperSurface()).frame(minWidth: 660, minHeight: 520)
        .onAppear { controller.configure(context, coordinator: coordinator) }
        .onChange(of: coordinator.openNonce) { _, _ in controller.configure(context, coordinator: coordinator) }
        .onDisappear { controller.pause() }
    }
    private var setup: some View {
        RunwayCard(padding: 26) {
            VStack(alignment: .leading, spacing: 20) {
                Text("开始一轮复习").font(.title2.weight(.semibold))
                if let session = controller.resumable {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("上次还有 \(max(0, ReviewLedger.queue(session).count - session.currentIndex)) 个知识点未处理").foregroundStyle(.secondary)
                        HStack {
                            Button("继续语音复习") { controller.start(usingVoice: true, resume: true) }.buttonStyle(.borderedProminent).tint(runway.ink)
                            Button("用文字继续") { controller.start(usingVoice: false, resume: true) }
                        }
                    }
                    Divider()
                }
                if coordinator.mode != "preview" {
                    Picker("本轮目标", selection: $controller.goal) {
                        Text("完成当前到期内容").tag("due")
                        Text("按时间").tag("minutes")
                        Text("按知识点数量").tag("count")
                    }
                    if controller.goal != "due" {
                        Stepper(value: $controller.goalValue, in: 1...100) {
                            Text(controller.goal == "minutes" ? "\(controller.goalValue) 分钟 · 当前题答完再结束" : "\(controller.goalValue) 个知识点")
                        }
                    }
                }
                Text("可以随时打断、问清题目，或者请我给一点提示。结果会自动保存。").font(.callout).foregroundStyle(.secondary)
                ViewThatFits {
                    HStack(spacing: 16) { startButtons }
                    VStack(alignment: .leading, spacing: 12) { startButtons }
                }
                Text("开始语音后才使用麦克风，音频由阿里云处理；本机只保留文字和结果，不保留录音回放。").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    @ViewBuilder private var startButtons: some View {
        RunwayPrimaryButton(title: "开始语音复习", action: { controller.start(usingVoice: true) })
        Button("用文字开始") { controller.start(usingVoice: false) }
    }
    private func question(_ entry: ReviewQueueEntry) -> some View {
        RunwayCard(padding: 26) {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Label(controller.voice.connected ? controller.voice.status : "文字回答", systemImage: controller.voice.connected ? "mic" : "text.cursor")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if controller.voice.connected {
                        Button(controller.voice.muted ? "取消静音" : "静音") { controller.voice.toggleMute() }
                            .accessibilityLabel(controller.voice.muted ? "取消麦克风静音" : "麦克风静音")
                    } else {
                        Button("连接语音") { controller.connectVoice() }.disabled(controller.busy)
                    }
                }
                if controller.correctionTarget != nil { Text("修正之前的转写").font(.caption).foregroundStyle(runway.action) }
                Text(entry.prompt).font(.system(size: 27, weight: .semibold, design: .rounded)).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                if !controller.feedback.isEmpty { Text(controller.feedback).font(.body).textSelection(.enabled).fixedSize(horizontal: false, vertical: true) }
                if controller.busy {
                    HStack { ProgressView().controlSize(.small); Text(controller.phase == "connecting" ? "正在连接语音…" : controller.phase == "saving" ? "正在保存结果…" : "正在理解你的回答…").foregroundStyle(.secondary) }
                }
                PaperWell {
                    TextField(controller.correctionTarget == nil ? "也可以输入回答、追问或帮助请求…" : "修正原话后重新判断…", text: $controller.answer, axis: .vertical)
                        .textFieldStyle(.plain).font(.title3).lineLimit(3...8)
                        .accessibilityLabel("回答或追问")
                }
                HStack {
                    if controller.voice.connected { Button("我说完了") { controller.voice.finishUtterance() } }
                    Spacer()
                    RunwayPrimaryButton(title: controller.correctionTarget == nil ? "发送" : "重新判断", enabled: !controller.busy && !controller.answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                                        action: { controller.submit(controller.answer) }).keyboardShortcut(.return, modifiers: [.command])
                }
                ViewThatFits {
                    HStack(spacing: 12) { helpButtons }
                    VStack(alignment: .leading, spacing: 10) { helpButtons }
                }.disabled(controller.busy)
            }
        }
    }
    @ViewBuilder private var helpButtons: some View {
        if controller.correctionTarget != nil {
            Button("取消纠正") { controller.cancelCorrection() }
        } else {
        Button("换个问法") { controller.submit("请解释题目在问什么，不提示答案。", action: "clarify") }
        Button("给我提示") { controller.submit("请给我一点提示。", action: "hint") }
        Button("重新讲解") { controller.submit("请围绕这道题重新讲解。", action: "explain") }
        Button(controller.phase == "explained" ? "继续其他题" : "跳过") { controller.skipOrContinue() }
        Button("转写有误") { controller.beginCorrection() }
        }
    }
    private var paused: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 16) {
                Text("已暂停").font(.title2.weight(.semibold))
                Text("已经完成的结果已保存，麦克风已停止。可以稍后继续这份清单。").foregroundStyle(.secondary)
                HStack {
                    Button("继续语音") { controller.start(usingVoice: true, resume: true) }
                    Button("用文字继续") { controller.start(usingVoice: false, resume: true) }
                    Button("关闭") { dismiss() }
                }
            }
        }
    }
    private var summary: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 18) {
                Text(controller.entries.isEmpty ? "现在没有到期内容" : "这一轮已结束").font(.title2.weight(.semibold))
                Text(controller.progress).foregroundStyle(.secondary)
                if controller.needsHelp > 0 { Text("需要再巩固 \(controller.needsHelp) 个知识点，其中 \(controller.assisted) 个使用了帮助。") }
                if controller.skipped > 0 || (controller.session?.currentIndex ?? 0) < controller.entries.count {
                    Text("跳过和未完成的内容仍在后续复习中。").foregroundStyle(.secondary)
                }
                ForEach(controller.entries) { entry in
                    if let row = controller.completed.first(where: { $0.attemptId == entry.attemptID }) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(entry.title).font(.callout.weight(.medium))
                            Text(ReviewRecallCopy.label(row.effectiveGrade)).font(.caption).foregroundStyle(.secondary)
                            if let raw = row.schedulerAfterJSON, let snapshot = try? JSONDecoder().decode(ReviewScheduleSnapshot.self, from: Data(raw.utf8)) {
                                Text("下次 \(snapshot.dueAt.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                RunwayPrimaryButton(title: "关闭", action: { dismiss() })
            }
        }
    }
    private var records: some View {
        DisclosureGroup("本轮文字记录与纠正", isExpanded: $controller.showRecords) {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(controller.records) { line in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(line.role == "user" ? "你" : "复习教练").font(.caption).foregroundStyle(.secondary)
                        Text(line.text).textSelection(.enabled)
                    }
                }
                ForEach(controller.entries) { entry in
                    if controller.completed.contains(where: { $0.attemptId == entry.attemptID }) {
                        HStack {
                            Text(entry.title).lineLimit(1)
                            Menu("纠正本次结果") {
                                Button("修正转写并重新判断") { controller.beginCorrection(entry) }
                                ForEach(["again", "hard", "good", "easy"], id: \.self) { grade in
                                    Button(ReviewRecallCopy.label(grade)) { controller.overrideGrade(grade, entry: entry) }
                                }
                            }.disabled(controller.busy)
                        }
                    }
                }
            }.padding(.top, 12)
        }
    }
}

enum ReviewRecallCopy {
    static func label(_ grade: String) -> String {
        switch grade {
        case "again": "本次未能独立回忆完整"
        case "hard": "独立答对，回忆有些困难"
        case "good": "本次独立回忆正确"
        case "easy": "轻松回忆 · 手动确认"
        default: grade
        }
    }
}
