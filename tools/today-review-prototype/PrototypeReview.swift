import SwiftUI

struct PrototypeReview: View {
    @Bindable var model: PrototypeState
    @Bindable var capture: PrototypeCapture
    let close: () -> Void
    @Environment(\.runway) private var palette
    @Environment(\.brandReduceMotion) private var reduced
    @FocusState private var answerFocused: Bool
    @FocusState private var correctionFocused: Bool
    @State private var helpOpen = false
    @State private var transcriptExpanded = false
    var body: some View {
        VStack(spacing: 0) {
            Group {
                switch model.phase {
                case .preparation: preparation
                case .summary: summary
                case .paused: paused
                default: answering
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            if model.phase != .summary { Divider() }
            demoToolbar
        }.background(PaperSurface())
        .onChange(of: model.textExpanded) { _, value in if value { answerFocused = true } }
        .onChange(of: model.phase) { _, value in if value == .asking && model.textExpanded { answerFocused = true } }
        .onChange(of: model.correcting) { _, value in if value { correctionFocused = true } }
        .onChange(of: model.text) { _, _ in model.inputChanged() }
        .onKeyPress(.escape) { if model.correcting { model.cancelCorrection() } else if model.phase != .preparation && model.phase != .summary { model.pause() }; return .handled }
    }
    private var preparation: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                HStack { Text("准备复习").font(.system(size: 30, weight: .bold)); Spacer(); PrototypeBadge() }
                Text("先想起来，再慢慢巩固。").font(.title3).foregroundStyle(.secondary)
                RunwayCard(padding: 24) {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack { VStack(alignment: .leading, spacing: 6) { Text("\(model.dueQuestions.count) 个到期知识点").font(.title2.weight(.semibold)); Text("按到期顺序 · 跨主题回顾").font(.callout).foregroundStyle(.secondary) }; Spacer(); Image(systemName: "rectangle.stack").font(.system(size: 30)).foregroundStyle(.secondary) }
                        Divider()
                        Text(model.dueQuestions.map(\.topic).joined(separator: "  ·  ")).font(.callout).foregroundStyle(.secondary).lineSpacing(5)
                    }
                }
                VStack(alignment: .leading, spacing: 16) {
                    Text("这一轮，想复习多少？").font(.headline)
                    Picker("本轮目标", selection: $model.goal) { ForEach(PrototypeGoal.allCases, id: \.self) { Text($0.rawValue).tag($0) } }.pickerStyle(.segmented)
                    if model.goal == .minutes {
                        HStack { Stepper(value: $model.minutes, in: 1...60) { Text("\(model.minutes) 分钟").monospacedDigit() }.frame(width: 170); Spacer(); Text("时间到后，完成当前题再收尾").font(.caption).foregroundStyle(.secondary) }
                    } else if model.goal == .count {
                        HStack { Stepper(value: $model.count, in: 1...30) { Text("\(model.count) 个知识点").monospacedDigit() }.frame(width: 170); Spacer(); Text("本轮最多 \(min(model.count, model.dueQuestions.count)) 个").font(.caption).foregroundStyle(.secondary) }
                    } else { Text("完成开始时的到期清单，本轮不会插入新的知识。").font(.callout).foregroundStyle(.secondary) }
                }
                HStack(spacing: 16) {
                    PrototypeCompanion(model: model).frame(width: 125, height: 120)
                    VStack(alignment: .leading, spacing: 8) { Text("Mr. B 陪你一起回顾").font(.headline); Text("可以随时暂停、请求帮助，或者改用文字。\n不用背原话，说出自己的理解就好。").font(.callout).foregroundStyle(.secondary).lineSpacing(4) }
                }
                HStack(spacing: 16) {
                    PrototypePrimaryButton(title: "开始语音", enabled: !model.dueQuestions.isEmpty) { model.start(.voice) }
                    PrototypeButton(title: "用文字开始", symbol: "keyboard") { model.start(.text) }.disabled(model.dueQuestions.isEmpty)
                }
                Text("本原型只演示语音状态，不连接麦克风，也不会播放声音。").font(.caption).foregroundStyle(.secondary)
            }.padding(36).frame(maxWidth: 760).frame(maxWidth: .infinity)
        }
    }
    private var answering: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 7) {
                    HStack { Text("回顾中").font(.callout.weight(.medium)); Text(model.progress).font(.callout.monospacedDigit()).foregroundStyle(.secondary) }
                    ProgressView(value: Double(model.results.count), total: Double(max(1, model.queue.count))).progressViewStyle(PrototypeProgressStyle()).frame(width: 155).accessibilityLabel("本轮已处理 \(model.results.count) 个，共 \(model.queue.count) 个")
                }
                Spacer()
                Text(model.timeExpired ? "完成当前题后收尾" : model.goal == .minutes ? "\(model.elapsedSeconds / 60):\(String(format: "%02d", model.elapsedSeconds % 60)) / \(model.minutes):00" : "一次回顾，一个知识点").font(.caption).foregroundStyle(.secondary)
                PrototypeButton(title: "暂停", symbol: "pause") { model.pause() }.keyboardShortcut("p", modifiers: [.command, .shift])
            }.padding(.horizontal, 30).padding(.vertical, 20)
            Divider().padding(.horizontal, 30)
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    VStack(alignment: .leading, spacing: 15) {
                        Text(model.question?.topic ?? "").font(.callout).foregroundStyle(.secondary)
                        ScrollView { Text(model.questionText).font(.system(size: model.longQuestion ? 24 : 29, weight: .semibold)).lineSpacing(7).frame(maxWidth: .infinity, alignment: .leading) }.id(model.question?.id)
                    }.frame(height: 155, alignment: .top).padding(.top, 26).padding(.bottom, 12)
                    HStack(alignment: .center, spacing: 20) {
                        PrototypeCompanion(model: model).frame(width: 155, height: 155)
                        VStack(alignment: .leading, spacing: 9) {
                            Label(model.status, systemImage: statusIcon).font(.callout.weight(.medium)).accessibilityAddTraits(.updatesFrequently)
                            Text(model.feedback.isEmpty ? "不需要完整的句子，先说你想起来的部分。" : model.feedback).font(.callout).foregroundStyle(.secondary).lineSpacing(4).fixedSize(horizontal: false, vertical: true)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(height: 155)
                    contextualActions.frame(minHeight: 36)
                    transcript
                }.padding(.horizontal, 32).padding(.bottom, 16).frame(maxWidth: 830).frame(maxWidth: .infinity)
            }
            Divider().padding(.horizontal, 30)
            answerControls.padding(.horizontal, 30).padding(.vertical, 14)
        }
    }
    private var statusIcon: String {
        if model.busy { return "ellipsis" }
        if model.voiceFailed { return "wifi.slash" }
        if model.listening { return "waveform" }
        if model.mode == .text { return "keyboard" }
        return model.muted ? "mic.slash" : "bubble.left"
    }
    @ViewBuilder private var contextualActions: some View {
        if model.phase == .help {
            HStack(spacing: 7) { PrototypeButton(title: "再想想") { model.thinkAgain() }; PrototypeButton(title: "提示", symbol: "lightbulb") { model.hint() }; PrototypeButton(title: "讲解", symbol: "text.bubble") { model.explain() }; PrototypeButton(title: "跳过") { model.skip() } }
        } else if model.phase == .explained {
            HStack(spacing: 12) { PrototypePrimaryButton(title: "继续下一题") { model.finishExplanation() }; PrototypeButton(title: "再解释一下") { model.explanationFollowup() }; if model.voiceSpeaking { PrototypeButton(title: "打断讲解") { model.voiceSpeaking = false; model.reaction = nil; model.motionToken += 1 } } }
        } else if model.phase == .saveFailed {
            PrototypePrimaryButton(title: "重试保存") { model.retrySave() }
        } else if model.phase == .feedback {
            HStack { Label("已记下本题 · 演示", systemImage: "checkmark.circle").font(.caption).foregroundStyle(.secondary); Spacer(); PrototypeButton(title: "下一题", symbol: "arrow.right") { model.advance() } }
        }
    }
    private var transcript: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.correcting {
                PaperWell {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("纠正刚才的回答").font(.callout.weight(.semibold))
                        TextField("正确转写", text: $model.correctionText, axis: .vertical).textFieldStyle(.plain).lineLimit(2...4).focused($correctionFocused).accessibilityLabel("纠正后的转写")
                            .task { try? await Task.sleep(for: .milliseconds(80)); if !Task.isCancelled && model.correcting { correctionFocused = true } }
                        HStack { PrototypePrimaryButton(title: "确认纠正", enabled: !model.correctionText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) { model.applyCorrection() }; PrototypeButton(title: "取消") { model.cancelCorrection() }; Text("更新同一次记录").font(.caption).foregroundStyle(.secondary) }
                    }
                }
            } else if !model.latestTranscript.isEmpty || !model.results.isEmpty {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) { Text("最近回答").font(.caption2).foregroundStyle(.secondary); Text(model.latestTranscript.isEmpty ? model.results.last?.correction ?? model.results.last?.rawAnswer ?? "" : model.latestTranscript).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                    Spacer(); PrototypeButton(title: "纠正") { model.beginCorrection() }.disabled(model.busy)
                }
            }
            DisclosureGroup("文字记录（\(model.records.count)）", isExpanded: $transcriptExpanded) {
                VStack(alignment: .leading, spacing: 10) { ForEach(model.records) { record in VStack(alignment: .leading, spacing: 3) { Text(record.speaker).font(.caption2.weight(.semibold)).foregroundStyle(.secondary); Text(record.text).font(.caption).textSelection(.enabled) }.frame(maxWidth: .infinity, alignment: .leading) } }.padding(.vertical, 12)
            }.font(.caption).foregroundStyle(.secondary)
        }
    }
    private var answerControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.textExpanded {
                HStack(alignment: .bottom, spacing: 12) {
                    TextField("用自己的话回答…", text: $model.text, axis: .vertical)
                        .textFieldStyle(.plain).lineLimit(3...5).padding(12)
                        .background(palette.field, in: RoundedRectangle(cornerRadius: 13))
                        .overlay(RoundedRectangle(cornerRadius: 13).strokeBorder(answerFocused ? palette.ink : palette.hairline, lineWidth: answerFocused ? 1.5 : 1))
                        .focused($answerFocused).focusEffectDisabled().accessibilityLabel("文字回答")
                        .task { try? await Task.sleep(for: .milliseconds(80)); if !Task.isCancelled && model.textExpanded { answerFocused = true } }
                    PrototypePrimaryButton(title: "答完了", enabled: model.canAnswer && !model.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) { model.submit(model.text) }.keyboardShortcut(.return, modifiers: .command)
                }
            }
            HStack(spacing: 8) {
                if model.textExpanded { PrototypeButton(title: model.voiceFailed ? "重新连接语音" : "返回语音", symbol: "mic") { model.useVoice() }.disabled(model.busy || model.correcting) }
                else {
                    PrototypeButton(title: model.muted ? "取消静音" : "静音", symbol: model.muted ? "mic.slash" : "mic") { model.toggleMute() }
                    PrototypeButton(title: "文字回答", symbol: "keyboard") { model.useText(); answerFocused = true }
                }
                Spacer(minLength: 4)
                PrototypeButton(title: "帮助", symbol: "questionmark.circle") { helpOpen.toggle() }
                    .disabled(!model.canAnswer)
                    .popover(isPresented: $helpOpen) {
                        PrototypeHelpChoices { choice in
                            helpOpen = false
                            switch choice { case 0: model.forgot(); case 1: model.clarify(); case 2: model.hint(); default: model.explain() }
                        } cancel: { helpOpen = false }
                    }
                    .onChange(of: helpOpen) { _, opened in if !opened && model.textExpanded { answerFocused = true } }
                PrototypeButton(title: "跳过", symbol: "forward.end") { model.skip() }.disabled(!model.canAnswer && model.phase != .explained)
            }
        }
    }
    private var paused: some View {
        VStack(spacing: 23) {
            PrototypeCompanion(model: model).frame(width: 175, height: 160)
            Text("先停一会儿").font(.system(size: 30, weight: .semibold))
            Text("已处理 \(model.results.count) / \(model.queue.count) 个，还剩 \(model.unfinished) 个。\n这一轮的题目和回答都留在这里。").multilineTextAlignment(.center).foregroundStyle(.secondary).lineSpacing(6)
            PrototypePrimaryButton(title: "继续本轮") { model.resume() }
            HStack { PrototypeButton(title: "回到今天") { close() }; PrototypeButton(title: "结束本轮") { model.finish() } }
            Text("关闭窗口也会暂停；退出原型后合成进度重置。").font(.caption).foregroundStyle(.secondary)
        }.padding(32)
    }
    private var summary: some View {
        PrototypeReviewSummary(model: model, close: close) { transcript }
    }
    private var demoToolbar: some View {
        HStack(spacing: 10) {
            Text("模拟判断").font(.caption).foregroundStyle(.secondary)
            Picker("模拟判断", selection: $model.scenario) { ForEach(PrototypeAnswer.allCases, id: \.self) { Text($0.rawValue).tag($0) } }.labelsHidden().frame(width: 150)
            Button("送入示例回答") { model.submitSample() }.disabled(!model.canAnswer).font(.caption)
            Spacer(minLength: 0)
            Menu("事件") {
                Button("模拟语音失败") { model.failVoice() }
                Button("模拟时间到") { model.expireTime() }
                Toggle("模拟保存失败", isOn: $model.simulateSaveFailure)
                Toggle("长题目", isOn: $model.longQuestion)
                Toggle("深色", isOn: $model.dark)
                Toggle("减少动态", isOn: $model.reduced)
                Divider(); Button("结束本轮") { model.finish() }.disabled(model.phase == .preparation)
            }.menuStyle(.borderlessButton).fixedSize()
            ChromeIconButton(title: "截取当前窗口", symbol: "camera") { capture.snapshot() }
            ChromeIconButton(title: capture.recording ? "停止录制" : "原速录制", symbol: capture.recording ? "stop.circle.fill" : "record.circle") { capture.toggleRecording() }
        }.padding(.horizontal, 14).padding(.vertical, 7).background(palette.field.opacity(0.5))
        .help("评估结果由模拟选项决定，不分析文字，不请求模型。")
    }
}

struct PrototypeCompanion: View {
    @Bindable var model: PrototypeState
    @Environment(\.brandReduceMotion) private var reduced
    @State private var failed = false
    private var activeReaction: String? { model.phase == .summary ? (model.correcting ? nil : model.summaryMotion) : model.reaction }
    private var voice: Bool { activeReaction == nil && ![.paused, .preparation, .summary].contains(model.phase) && (model.listening || model.voiceSpeaking) }
    private var voicePhase: MascotPhase { model.busy ? .thinking : model.voiceSpeaking ? .speaking : model.listening ? .listening : .idle }
    var body: some View {
        ZStack {
            MascotWebSurface(configuration: .init(surface: .voice, mode: voicePhase, level: model.listening || model.voiceSpeaking ? 0.28 : 0, reduced: reduced, dark: model.dark, visible: voice && model.windowOpen, material: "graphite", palette: .theme(dark: model.dark)))
                .frame(width: 360, height: 180).scaleEffect(1.6).offset(y: -18)
                .frame(width: 155, height: 155).clipped().opacity(voice ? 1 : 0)
            MrBMotionView(configuration: .init(kind: model.busy ? "thinking" : activeReaction ?? "reaction_rest", token: model.motionToken, dark: model.dark, reduced: reduced || (activeReaction == nil && !model.busy), visible: !voice && model.windowOpen, count: max(1, model.completed), seekTime: model.phase == .summary ? model.summaryMotionTime : nil, seekToken: model.phase == .summary ? model.motionToken + 1 : 0, reviewRecording: false), onEvent: { event in
                if event == "failed" { failed = true }
                if event == "ready" { failed = false }
                if event == "finished" && model.phase == .explained { model.reaction = nil }
            }, onTime: { time in
                if model.phase == .summary && model.summaryMotion != nil && model.windowOpen { model.summaryMotionTime = time }
            })
                .opacity(voice ? 0 : 1)
            if failed { Image(systemName: "book.closed").font(.system(size: 40)).foregroundStyle(.secondary) }
        }.allowsHitTesting(false).accessibilityHidden(true)
    }
}

struct PrototypeProgressStyle: ProgressViewStyle {
    @Environment(\.runway) private var palette
    func makeBody(configuration: Configuration) -> some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(palette.field)
                Capsule().fill(palette.ink).frame(width: geometry.size.width * max(0, min(1, configuration.fractionCompleted ?? 0)))
            }
        }.frame(height: 4)
    }
}

struct PrototypeHelpChoices: View {
    var select: (Int) -> Void
    var cancel: () -> Void
    @FocusState private var focus: Int?
    private let titles = ["我忘记了", "没理解题意", "给个提示", "重新讲解"]
    private let symbols = ["brain", "questionmark.bubble", "lightbulb", "text.bubble"]
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(0..<titles.count, id: \.self) { i in
                Button { select(i) } label: {
                    Label(titles[i], systemImage: symbols[i]).frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }.buttonStyle(InteractionButtonStyle(focused: focus == i, padding: 0))
                    .focusable().focusEffectDisabled().focused($focus, equals: i)
                    .onKeyPress(keys: [.return, .space], phases: .down) { _ in select(i); return .handled }
            }
        }.padding(8).frame(width: 240)
            .task { await Task.yield(); focus = 0 }
            .onKeyPress(.escape) { cancel(); return .handled }
            .onKeyPress(.downArrow) { focus = min(3, (focus ?? 0) + 1); return .handled }
            .onKeyPress(.upArrow) { focus = max(0, (focus ?? 0) - 1); return .handled }
    }
}
