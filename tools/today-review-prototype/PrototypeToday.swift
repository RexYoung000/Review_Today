import AppKit
import SwiftUI

struct PrototypeShell: View {
    @Bindable var model: PrototypeState
    let openReview: () -> Void
    let openSummary: () -> Void
    @Bindable var capture: PrototypeCapture
    @Environment(\.runway) private var palette
    @State private var nav: SidebarItem? = .today
    @State private var session: UUID?
    @State private var selectedLearning: PrototypeLearningItem?
    @State private var selectedKnowledge: PrototypeQuestion?
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                sidebar.frame(width: 206)
                Divider()
                Group {
                    switch model.page {
                    case .today: today
                    case .exam: PrototypeExamPage(model: model)
                    case .library: library
                    case .learning: learningDestination
                    case .inbox: destination(title: "没有待处理内容", symbol: "tray", detail: "原型没有接入真实待处理任务。")
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity).modifier(PageArrivalLift(page: nav ?? .today))
            }
            Divider()
            demoToolbar
        }.background(PaperSurface())
        .sheet(item: $selectedKnowledge) { question in
            VStack(alignment: .leading, spacing: 20) {
                HStack { Text(question.topic).font(.title2.weight(.semibold)); Spacer(); PrototypeBadge() }
                Text(question.question).font(.headline)
                Text(question.explanation).font(.body).lineSpacing(6)
                Text("合成知识预览 · 仅演示内容与排版").font(.caption).foregroundStyle(.secondary)
                PrototypeButton(title: "关闭预览", symbol: "chevron.left") { selectedKnowledge = nil }
            }.padding(28).frame(width: 500).background(PaperSurface())
        }
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
            HStack { Text("合成数据 · 待体验确认").font(.caption).foregroundStyle(.secondary); Spacer(); ChromeIconButton(title: model.dark ? "切换浅色" : "切换深色", symbol: model.dark ? "sun.max" : "moon") { model.dark.toggle() } }.padding(16)
        }.background(palette.field.opacity(0.45))
    }
    private var today: some View {
        PrototypeTodayPage(model: model, openReview: openReview, openSummary: openSummary, openLearning: { item in
            selectedLearning = item; model.page = .learning
        }, openKnowledge: { id in
            selectedKnowledge = PrototypeQuestion.samples.first { PrototypeLearningItem.sampleID($0.id) == id }
        })
    }
    @ViewBuilder private var learningDestination: some View {
        if let item = selectedLearning {
            PrototypeLearningPage(item: item, back: { model.page = .today }, openKnowledge: {
                selectedKnowledge = PrototypeQuestion.samples.first { PrototypeLearningItem.sampleID($0.id) == item.id }
            })
        } else {
            destination(title: "从一个问题开始", symbol: "terminal", detail: "学习入口将打开现有 Agent，你的学习方式和对话能力保持不变。")
        }
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
