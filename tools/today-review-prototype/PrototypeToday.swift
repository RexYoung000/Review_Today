import AppKit
import SwiftUI

struct PrototypeShell: View {
    @Bindable var model: PrototypeState
    let openReview: () -> Void
    @Bindable var capture: PrototypeCapture
    @Environment(\.runway) private var palette
    @State private var nav: SidebarItem? = .today
    @State private var session: UUID?
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                sidebar.frame(width: 206)
                Divider()
                Group {
                    switch model.page {
                    case .today: today
                    case .exam: exam
                    case .library: library
                    case .learning: destination(title: "从一个问题开始", symbol: "terminal", detail: "学习入口将打开现有 Agent，你的学习方式和对话能力保持不变。")
                    case .inbox: destination(title: "没有待处理内容", symbol: "tray", detail: "原型没有接入真实待处理任务。")
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity).modifier(PageArrivalLift(page: nav ?? .today))
            }
            Divider()
            demoToolbar
        }.background(PaperSurface())
        .onChange(of: model.page) { _, page in nav = page == .exam ? .today : SidebarItem(rawValue: page.rawValue) }
        .onChange(of: nav) { _, selected in if let selected, !(model.page == .exam && selected == .today) { model.page = PrototypePage(rawValue: selected.rawValue) ?? .today } }
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 10) {
                BrandMark(size: 32)
                Text("Review Today").font(.system(size: 18, weight: .semibold))
            }.padding(.horizontal, 18).padding(.top, 26)
            SidebarPrimaryNavigation(selection: Binding(get: { nav }, set: { nav = $0; model.page = PrototypePage(rawValue: $0?.rawValue ?? "today") ?? .today }), selectedSessionID: $session, inboxCount: 0).padding(.horizontal, 10)
            Divider().padding(.horizontal, 16)
            VStack(alignment: .leading, spacing: 14) {
                Text("会话").font(.subheadline.weight(.medium))
                Label("理解 RAG 的工作方式", systemImage: "bubble.left").font(.system(size: 12)).foregroundStyle(.secondary)
                Text("合成学习记录").font(.caption2).foregroundStyle(.tertiary)
            }.padding(.horizontal, 22)
            Spacer()
            HStack { Text("原型待体验确认").font(.caption).foregroundStyle(.secondary); Spacer(); ChromeIconButton(title: model.dark ? "切换浅色" : "切换深色", symbol: model.dark ? "sun.max" : "moon") { model.dark.toggle() } }.padding(16)
        }.background(palette.field.opacity(0.45))
    }
    private var today: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 6) { Text("今天").font(.system(size: 30, weight: .bold)); Text("让学过的，再想起来。").font(.callout).foregroundStyle(.secondary) }
                    Spacer(); PrototypeBadge()
                }
                reviewHero
                HStack(spacing: 16) {
                    entry(title: "开始学习", detail: "从问题、资料或一个新想法开始", icon: "sparkle", action: { model.page = .learning })
                    entry(title: "模拟考", detail: "知识测验 · 模拟面试", icon: "text.badge.checkmark", action: { model.page = .exam })
                }
                VStack(alignment: .leading, spacing: 14) {
                    Text("最近学习").font(.headline)
                    if model.today == .empty { Text("从第一个问题开始，你的学习会留在这里。").font(.callout).foregroundStyle(.secondary) }
                    else {
                        Button { model.page = .learning } label: {
                            HStack { Image(systemName: "bubble.left").foregroundStyle(.secondary); VStack(alignment: .leading, spacing: 5) { Text("理解 RAG 的工作方式").font(.callout.weight(.medium)); Text("刚刚 · 还可以继续聊聊资料检索").font(.caption).foregroundStyle(.secondary) }; Spacer(); Image(systemName: "arrow.up.right").font(.caption) }.padding(16).background(palette.card, in: RoundedRectangle(cornerRadius: 16))
                        }.buttonStyle(InteractionButtonStyle(padding: 0, outline: .rounded(16)))
                            .modifier(PrototypeKeyboardAction(radius: 16) { model.page = .learning })
                    }
                }
                if !model.results.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("复习结果").font(.headline)
                        HStack { Text("最近一轮").font(.callout); Spacer(); Text("\(model.completed) 完成 · \(model.helped) 需要帮助 · \(model.skipped) 跳过").font(.caption).foregroundStyle(.secondary) }
                    }
                }
                activity
            }.padding(32).frame(maxWidth: 960).frame(maxWidth: .infinity)
        }
    }
    private var reviewHero: some View {
        RunwayCard(padding: 26) {
            VStack(alignment: .leading, spacing: 22) {
                HStack { Label(model.today == .paused ? "继续你的节奏" : "今日复习", systemImage: model.today == .paused ? "pause.circle" : "arrow.clockwise").font(.callout.weight(.medium)).foregroundStyle(.secondary); Spacer(); if model.today == .due { Text("2 个已逾期").font(.caption).foregroundStyle(.secondary) } }
                HStack(alignment: .center, spacing: 22) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(heroTitle).font(.system(size: 26, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                        Text(heroDetail).font(.callout).foregroundStyle(.secondary).lineSpacing(4).fixedSize(horizontal: false, vertical: true)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    if [.due, .paused].contains(model.today) {
                        VStack(spacing: 2) { Text("\(model.today == .paused ? model.unfinished : model.dueQuestions.count)").font(.system(size: 55, weight: .light, design: .rounded)); Text(model.today == .paused ? "个待继续" : "个知识点").font(.caption).foregroundStyle(.secondary) }.frame(width: 108)
                    }
                }
                if model.today == .finished { summaryStats }
                HStack(spacing: 12) {
                    PrototypePrimaryButton(title: heroAction, action: performHero)
                    if model.today == .due { Text("先准备，再开始").font(.caption).foregroundStyle(.secondary) }
                    if model.today == .finished && !model.dueQuestions.isEmpty { PrototypeButton(title: "再复习 \(model.dueQuestions.count) 个") { model.newRound(); openReview() } }
                }
            }
        }
    }
    private var heroTitle: String {
        switch model.today {
        case .empty: "学过的知识，在这里慢慢记牢"
        case .unenrolled: "知识已经收好了，选一些来复习"
        case .scheduled: "今天暂时不用复习"
        case .due: "把学过的，再想一遍"
        case .paused: "上次停下的地方，还为你留着"
        case .finished: model.unfinished > 0 || model.skipped > 0 ? "这一轮先到这里" : "又回顾了一遍，给记忆一点时间"
        }
    }
    private var heroDetail: String {
        switch model.today {
        case .empty: "先学一点感兴趣的内容，保存后可以选择加入复习。"
        case .unenrolled: "保存不等于加入复习。选出已经学过、想记住的内容即可。"
        case .scheduled: "下次安排在今天 18:30，共 \(model.enrolledSamples.count) 个知识点。到时候再来就好。"
        case .due: "按到期先后回顾，不分主题。用自己的话，看看还记得多少。"
        case .paused: "已处理 \(model.results.count) / \(model.queue.count) 个，继续本轮不会加入新的内容。"
        case .finished: "已处理的回忆会留在结果里；跳过或未完成的内容仍在清单中。"
        }
    }
    private var heroAction: String {
        switch model.today {
        case .empty: "开始学习"
        case .unenrolled: "选择复习内容"
        case .scheduled: "管理复习内容"
        case .due: "准备复习"
        case .paused: "继续本轮"
        case .finished: "查看本轮小结"
        }
    }
    private func performHero() {
        switch model.today {
        case .empty: model.page = .learning
        case .unenrolled, .scheduled: model.page = .library
        case .due: model.newRound(); openReview()
        case .paused, .finished: openReview()
        }
    }
    private var summaryStats: some View {
        HStack(spacing: 25) {
            metric("已完成", model.completed); metric("其中需要帮助", model.helped); metric("跳过", model.skipped); metric("未完成", model.unfinished)
        }
    }
    private func metric(_ label: String, _ value: Int) -> some View { VStack(alignment: .leading, spacing: 4) { Text("\(value)").font(.title2.weight(.medium)); Text(label).font(.caption).foregroundStyle(.secondary) } }
    private func entry(title: String, detail: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) { Image(systemName: icon).font(.title3).frame(width: 26).padding(.top, 2); VStack(alignment: .leading, spacing: 7) { Text(title).font(.headline); Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }; Spacer(minLength: 0); Image(systemName: "arrow.up.right").font(.caption).foregroundStyle(.secondary) }.padding(20).frame(maxWidth: .infinity, minHeight: 90, alignment: .leading).background(palette.field.opacity(0.5), in: RoundedRectangle(cornerRadius: 18))
        }.buttonStyle(InteractionButtonStyle(padding: 0, outline: .rounded(18)))
            .modifier(PrototypeKeyboardAction(action: action))
    }
    private var activity: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack { Text("活动记录").font(.headline); Spacer(); Text("最近 4 周 · 合成示例").font(.caption).foregroundStyle(.secondary) }
            HStack(spacing: 5) { ForEach(0..<28, id: \.self) { i in RoundedRectangle(cornerRadius: 3).fill(palette.ink.opacity(model.today == .empty ? 0.04 : [0.05, 0.13, 0.28, 0.06, 0.18, 0.04, 0.09][i % 7])).frame(height: 14) } }.accessibilityElement(children: .ignore).accessibilityLabel(model.today == .empty ? "暂无活动" : "合成活动示例，不表示知识掌握程度")
        }
    }
    private var exam: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                PrototypeButton(title: "今天", symbol: "chevron.left") { model.page = .today }
                HStack { Text("你想练习哪一种？").font(.system(size: 28, weight: .bold)); Spacer(); PrototypeBadge() }
                Text("用一次完整练习，看看自己准备得怎么样。").foregroundStyle(.secondary)
                examOption("知识测验", symbol: "checklist", detail: "围绕学过的知识，检查理解与运用。")
                examOption("模拟面试", symbol: "person.bubble", detail: "围绕目标岗位，练习表达与临场回答。")
                if let selected = model.examSelection {
                    PaperWell { VStack(alignment: .leading, spacing: 8) { Label("已选择\(selected)", systemImage: "checkmark.circle").font(.headline); Text("本轮先确认入口与模式选择。出题、评分和结果流程将在后续单独设计。").font(.callout).foregroundStyle(.secondary) } }
                }
                Text("模式选择原型 · 暂未开放考试").font(.caption).foregroundStyle(.secondary)
            }.padding(32).frame(maxWidth: 820).frame(maxWidth: .infinity)
        }
    }
    private func examOption(_ title: String, symbol: String, detail: String) -> some View {
        Button { model.examSelection = title } label: {
            RunwayCard(padding: 24) { HStack(spacing: 20) { Image(systemName: symbol).font(.system(size: 28)).frame(width: 44); VStack(alignment: .leading, spacing: 8) { Text(title).font(.title3.weight(.semibold)); Text(detail).font(.callout).foregroundStyle(.secondary) }; Spacer(); Image(systemName: model.examSelection == title ? "checkmark.circle.fill" : "circle").font(.title3) } }
        }.buttonStyle(InteractionButtonStyle(selected: model.examSelection == title, padding: 0, outline: .rounded(24))).accessibilityAddTraits(model.examSelection == title ? .isSelected : [])
            .modifier(PrototypeKeyboardAction(radius: 24) { model.examSelection = title })
    }
    private var library: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Text("选择想记住的内容").font(.system(size: 28, weight: .bold))
                Text("已学过的知识可以加入复习；关闭复习不会删除知识。").foregroundStyle(.secondary)
                ForEach(PrototypeQuestion.samples) { q in
                    RunwayCard { HStack { VStack(alignment: .leading, spacing: 6) { Text(q.topic).font(.headline); Text(q.question).font(.caption).foregroundStyle(.secondary) }; Spacer(); Toggle("加入复习", isOn: Binding(get: { model.enrolledSamples.contains(q.id) }, set: { model.setEnrollment(q.id, enabled: $0) })).toggleStyle(.switch).fixedSize().accessibilityLabel("\(q.topic)，加入复习") } }
                }
                Text("知识库去向预览 · 开关只影响合成数据，新加入的内容演示为稍后到期。").font(.caption).foregroundStyle(.secondary)
                PrototypeButton(title: "回到今天", symbol: "chevron.left") { model.page = .today }
            }.padding(32).frame(maxWidth: 880).frame(maxWidth: .infinity)
        }
    }
    private func destination(title: String, symbol: String, detail: String) -> some View {
        VStack(spacing: 22) { Image(systemName: symbol).font(.system(size: 36)).foregroundStyle(.secondary); Text(title).font(.system(size: 28, weight: .bold)); Text(detail).multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 410); Text("入口去向预览 · 本原型不发送对话").font(.caption).foregroundStyle(.secondary); PrototypeButton(title: "回到今天", symbol: "chevron.left") { model.page = .today } }.padding(32)
    }
    private var demoToolbar: some View {
        HStack(spacing: 12) {
            Text("演示状态").font(.caption).foregroundStyle(.secondary)
            Picker("今天状态", selection: Binding(get: { model.today }, set: { model.select($0) })) { ForEach(PrototypeToday.allCases) { Text($0.rawValue).tag($0) } }.labelsHidden().frame(width: 150)
            Toggle("减少动态", isOn: $model.reduced).toggleStyle(.checkbox).font(.caption)
            Spacer()
            if !capture.message.isEmpty { Text(capture.message).font(.caption2).lineLimit(1) }
            ChromeIconButton(title: "截取当前窗口", symbol: "camera") { capture.snapshot() }
            ChromeIconButton(title: capture.recording ? "停止录制" : "原速录制", symbol: capture.recording ? "stop.circle.fill" : "record.circle") { capture.toggleRecording() }
        }.padding(.horizontal, 16).padding(.vertical, 7).background(palette.field.opacity(0.5))
    }
}
