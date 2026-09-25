import SwiftData
import SwiftUI

struct ReviewView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway
    var coordinator: ReviewCoordinator
    @State private var controller = ReviewController()
    @State private var motion = ReviewCompanionState()
    @State private var textExpanded = false
    @FocusState private var answerFocused: Bool

    init(coordinator: ReviewCoordinator, controller: ReviewController? = nil) {
        self.coordinator = coordinator; _controller = State(initialValue: controller ?? ReviewController())
    }
    var body: some View {
        Group {
            switch controller.phase {
            case "setup": ReviewPreparationView(controller: controller, coordinator: coordinator, motion: motion, start: start)
            case "summary":
                if let session = controller.session {
                    ReviewSummaryView(summary: ReviewRoundSummary(session: session, attempts: controller.attempts), motion: motion, close: closeToToday) { records }
                }
            case "paused": paused
            default: answering
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if let error = controller.errorText {
                    Label(error, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.secondary)
                        .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(16).background(runway.card)
                }
            }
            .background(PaperSurface()).frame(minWidth: 700, minHeight: 650)
            .onReceive(NotificationCenter.default.publisher(for: .localDataWillReset)) { _ in
                controller.discardForDataReset(); motion.show(nil, still: true)
                coordinator.summarySessionID = nil; coordinator.knowledgeIDs = []; coordinator.previewQuestionID = nil
                dismiss()
            }
            .onAppear { configure() }
            .onChange(of: coordinator.openNonce) { _, _ in configure() }
            .onDisappear { controller.pause(); motion.show(nil, still: true) }
            .onChange(of: controller.phase) { _, phase in
                updateMotion()
                if phase == "asking" && !controller.voice.connected { textExpanded = true }
                if phase == "asking" && textExpanded { answerFocused = true }
            }
            .onChange(of: controller.savedResultToken) { _, _ in
                if controller.phase != "summary" { motion.show(controller.savedReaction) }
            }
            .onChange(of: controller.errorText) { _, error in
                if error != nil && controller.entry != nil { useText(); motion.show(nil, still: true) }
            }
            .onChange(of: controller.voice.status) { _, _ in
                if !["summary", "setup", "paused"].contains(controller.phase) && !controller.busy &&
                    (!controller.voice.connected || controller.voice.status == "正在聆听" || controller.voice.muted) { motion.show(nil) }
            }
            .onChange(of: controller.correctionTarget?.id) { _, target in if target != nil { useText() } }
            .onChange(of: controller.answer) { _, value in if !controller.busy && !value.isEmpty { motion.show(nil) } }
            .task(id: textExpanded) { if textExpanded { await Task.yield(); answerFocused = true } }
            .onKeyPress(.escape) {
                if controller.correctionTarget != nil { controller.cancelCorrection() }
                else if !["setup", "summary", "paused"].contains(controller.phase) { controller.pause() }
                else { return .ignored }
                return .handled
            }
    }
    private func configure() {
        controller.configure(context, coordinator: coordinator); textExpanded = false; updateMotion()
    }
    private func start(_ voice: Bool) {
        textExpanded = !voice
        controller.start(usingVoice: voice, resume: controller.resumable != nil)
        if !voice { answerFocused = true }
    }
    private func useText() { controller.useText(); textExpanded = true; answerFocused = true }
    private func connectVoice() { answerFocused = false; textExpanded = false; controller.connectVoice() }
    private func closeToToday() {
        NotificationCenter.default.post(name: .reviewReturnToToday, object: nil)
        if let window = ConversationWindowRouter.target?.window, window.isVisible || window.isMiniaturized {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
        } else { openWindow(id: "main") }
        dismiss()
    }
    private func updateMotion() {
        switch controller.phase {
        case "summary":
            guard let session = controller.session else { motion.show(nil); return }
            let summary = ReviewRoundSummary(session: session, attempts: controller.attempts)
            motion.show(summary.full && !summary.preview ? "review_study" : summary.completed > 0 ? "reaction_encourage" : "reaction_guide", still: controller.viewingHistory)
        case "help": motion.show("reaction_encourage")
        case "explained": motion.show("reaction_guide")
        case "paused", "setup": motion.show(nil, still: true)
        default: motion.show(nil)
        }
    }
    private var answering: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 7) {
                    HStack { Text(controller.correctionTarget == nil ? "回顾中" : "纠正回答").font(.callout.weight(.medium)); Text(controller.progress).font(.callout.monospacedDigit()).foregroundStyle(.secondary) }
                    ProgressView(value: Double(controller.session?.currentIndex ?? 0), total: Double(max(1, controller.entries.count)))
                        .progressViewStyle(.linear).tint(runway.ink).frame(width: 155)
                        .accessibilityLabel("本轮已处理 \(controller.session?.currentIndex ?? 0) 个，共 \(controller.entries.count) 个")
                }
                Spacer()
                if controller.session?.mode == "preview" { Text("试一题 · 不计排期").font(.caption).foregroundStyle(.secondary) }
                else { timeStatus }
                ReviewActionButton(title: "暂停", symbol: "pause") { controller.pause() }.keyboardShortcut("p", modifiers: [.command])
            }.padding(.horizontal, 30).padding(.vertical, 20)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        if let entry = controller.entry {
                            VStack(alignment: .leading, spacing: 14) {
                                Text(entry.title).font(.callout).foregroundStyle(.secondary)
                                Text(entry.prompt).font(.system(size: 29, weight: .semibold)).lineSpacing(7)
                                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled).id(entry.id)
                            }.frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading).padding(.top, 12).id("current-question")
                        }
                        HStack(spacing: 20) {
                            ReviewCompanion(motion: motion, busy: controller.busy,
                                listening: controller.voice.connected && !controller.voice.muted && controller.voice.status == "正在聆听",
                                speaking: controller.voice.connected && controller.voice.status.contains("播报"))
                                .frame(width: 155, height: 155)
                            ReviewFeedbackView(controller: controller, textExpanded: textExpanded)
                        }.frame(minHeight: 155)
                        if controller.phase == "help" { contextualHelp }
                        if controller.phase == "explained" {
                            HStack { Text("可以继续追问，也可以先回顾其他题。").font(.caption).foregroundStyle(.secondary); Spacer(); ReviewActionButton(title: "继续其他题", symbol: "arrow.right") { controller.skipOrContinue() } }
                        }
                        latestAnswer
                        records
                    }.padding(.horizontal, 30).padding(.bottom, 18).frame(maxWidth: 880).frame(maxWidth: .infinity)
                }.onChange(of: controller.entry?.id) { _, _ in proxy.scrollTo("current-question", anchor: .top) }
            }
            answerControls
        }
    }
    @ViewBuilder private var timeStatus: some View {
        if let session = controller.session, session.goal == "minutes" {
            TimelineView(.periodic(from: .now, by: 1)) { clock in
                let seconds = Int(ReviewLedger.elapsed(session, now: clock.date))
                Text(seconds >= session.goalValue * 60 ? "完成当前题后收尾" : "\(seconds / 60):\(String(format: "%02d", seconds % 60)) / \(session.goalValue):00")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        } else { Text("一次回顾，一个知识点").font(.caption).foregroundStyle(.secondary) }
    }
    private var contextualHelp: some View {
        HStack(spacing: 8) {
            ReviewActionButton(title: "再想想") { controller.phase = "asking" }
            ReviewActionButton(title: "提示", symbol: "lightbulb") { controller.submit("请给一点提示。", action: "hint") }
            ReviewActionButton(title: "讲解", symbol: "text.bubble") { controller.submit("请围绕这道题重新讲解。", action: "explain") }
            ReviewActionButton(title: "跳过") { controller.skipOrContinue() }
        }.disabled(controller.busy)
    }
    private var answerControls: some View {
        VStack(alignment: .leading, spacing: 14) {
            if textExpanded {
                HStack(alignment: .bottom, spacing: 14) {
                    PaperWell {
                        TextField(controller.correctionTarget == nil ? "输入回答，也可以追问…" : "修正刚才的原话…", text: $controller.answer, axis: .vertical)
                            .textFieldStyle(.plain).font(.body).lineLimit(2...5).focused($answerFocused)
                            .accessibilityLabel("回答或追问").disabled(controller.busy)
                    }
                    ReviewStartButton(title: controller.correctionTarget == nil ? "发送" : "重新判断",
                        enabled: !controller.busy && !controller.answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) { controller.submit(controller.answer) }
                        .keyboardShortcut(.return, modifiers: [.command])
                }
            }
            HStack(spacing: 14) {
                if controller.correctionTarget != nil {
                    ReviewActionButton(title: "取消纠正") { controller.cancelCorrection() }
                } else {
                    if textExpanded { ReviewActionButton(title: "切回语音", symbol: "mic", action: connectVoice).disabled(controller.busy) }
                    else { ReviewActionButton(title: "文字回答", symbol: "keyboard", action: useText) }
                    if controller.voice.connected {
                        ReviewActionButton(title: controller.voice.muted ? "取消静音" : "静音", symbol: controller.voice.muted ? "mic.slash" : "mic") { controller.voice.toggleMute() }
                        ReviewActionButton(title: "我说完了") { controller.voice.finishUtterance() }.disabled(controller.busy)
                    }
                    Spacer(minLength: 0)
                    Menu {
                        Button("我忘记了") { controller.submit("我忘记了。") }
                        Button("没理解题意") { controller.submit("请解释题目在问什么，不提示答案。", action: "clarify") }
                        Button("给我提示") { controller.submit("请给一点提示。", action: "hint") }
                        Button("重新讲解") { controller.submit("请围绕这道题重新讲解。", action: "explain") }
                    } label: { Label("需要帮助", systemImage: "questionmark.circle") }.menuStyle(.borderlessButton).fixedSize().disabled(controller.busy)
                    ReviewActionButton(title: controller.phase == "explained" ? "继续其他题" : "跳过", symbol: "forward.end") { controller.skipOrContinue() }.disabled(controller.busy)
                }
            }
        }.padding(.horizontal, 28).padding(.vertical, 18).background(runway.card.opacity(0.55))
    }
    @ViewBuilder private var latestAnswer: some View {
        let row = controller.attempts.filter { !$0.answerText.isEmpty || !$0.originalAnswer.isEmpty }.max { $0.createdAt < $1.createdAt }
        if let row, let entry = controller.entries.first(where: { $0.attemptID == row.attemptId }) {
            RunwayCard(padding: 16) {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(entry.id == controller.entry?.id ? "刚才的回答" : "最近回答 · \(entry.title)").font(.caption).foregroundStyle(.secondary)
                        let answer = row.correctedAnswer ?? (row.originalAnswer.isEmpty ? row.answerText : row.originalAnswer)
                        Text(answer).font(.callout).lineLimit(3).textSelection(.enabled).id(answer)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    ReviewActionButton(title: "纠正") { controller.beginCorrection(entry) }.disabled(controller.busy)
                }
            }
        }
    }
    private var paused: some View {
        VStack(spacing: 22) {
            ReviewCompanion(motion: motion).frame(width: 175, height: 160)
            Text("先停一下，进度留在这里").font(.system(size: 28, weight: .semibold))
            Text("已经保存的结果会保留，麦克风已停止。回来后继续未完成的清单。")
                .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
            HStack(spacing: 16) {
                ReviewActionButton(title: "用文字继续", symbol: "keyboard") { start(false) }
                ReviewStartButton(title: "继续语音") { start(true) }
                ReviewActionButton(title: "回到今天", action: closeToToday)
            }
        }.padding(32).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    private var records: some View {
        DisclosureGroup("本轮文字记录与纠正", isExpanded: $controller.showRecords) {
            VStack(alignment: .leading, spacing: 16) {
                if controller.records.isEmpty { Text("回答后会在这里保留文字记录。").font(.callout).foregroundStyle(.secondary) }
                ForEach(controller.records) { line in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(line.role == "user" ? "你" : "Mr. B").font(.caption).foregroundStyle(.secondary)
                        Text(line.text).font(.callout).textSelection(.enabled)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                ForEach(controller.entries) { entry in
                    if controller.completed.contains(where: { $0.attemptId == entry.attemptID }) {
                        HStack {
                            Text(entry.title).font(.callout).lineLimit(2); Spacer()
                            Menu("纠正本次结果") {
                                Button("修正转写并重新判断") { controller.beginCorrection(entry) }
                                ForEach(["again", "hard", "good", "easy"], id: \.self) { grade in
                                    Button(ReviewRecallCopy.label(grade)) { controller.overrideGrade(grade, entry: entry) }
                                }
                            }.disabled(controller.busy || controller.session?.paused == true)
                        }
                    }
                }
            }.padding(.top, 14)
        }.font(.callout).padding(4)
    }
}


/// Track response changes in its own body, including turns which keep the same phase.
private struct ReviewFeedbackView: View {
    let controller: ReviewController
    let textExpanded: Bool
    var body: some View {
        let message = !controller.feedback.isEmpty ? controller.feedback : !controller.savedFeedback.isEmpty ? "上一题：" + controller.savedFeedback : "不需要完整的句子，先说你想起来的部分。"
        VStack(alignment: .leading, spacing: 9) {
            Label(status, systemImage: controller.busy ? "ellipsis" : textExpanded ? "keyboard" : "waveform")
                .font(.callout.weight(.medium)).accessibilityAddTraits(.updatesFrequently)
            Text(message).font(.callout).foregroundStyle(.secondary).lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled).id(message)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private var status: String {
        if controller.phase == "connecting" { return "正在连接语音…" }
        if controller.phase == "saving" { return "正在保存结果…" }
        if controller.busy { return "正在理解你的回答…" }
        if controller.correctionTarget != nil { return "修正原话后重新判断" }
        return controller.voice.connected ? controller.voice.status : "文字回答"
    }
}

extension Notification.Name { static let reviewReturnToToday = Notification.Name("reviewReturnToToday") }

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
