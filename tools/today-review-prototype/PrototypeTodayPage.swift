import SwiftUI

/// Value-only examples for the existing Today components. Never loads a model context.
struct PrototypeLearningItem: Identifiable {
    let id: UUID
    let title: String
    let topics: String
    let status: String
    let mode: String
    let when: String

    static func sampleID(_ number: Int) -> UUID {
        UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", number))!
    }
    static let samples: [Self] = [
        .init(id: sampleID(1), title: "理解 RAG 的工作方式", topics: "人工智能 · 检索增强生成", status: "停在检索与生成的分工", mode: "理解", when: "今天"),
        .init(id: sampleID(2), title: "光合作用中的能量从哪来", topics: "生物 · 光合作用", status: "已经整理，可以继续追问", mode: "精读", when: "昨天"),
        .init(id: sampleID(3), title: "怎样判断一个产品变好了", topics: "产品设计 · 指标", status: "下一步：用留存分析一个案例", mode: "理解", when: "周一"),
        .init(id: sampleID(5), title: "工作记忆与分步表达", topics: "认知 · 工作记忆", status: "停在一个生活中的例子", mode: "理解", when: "上周"),
        .init(id: sampleID(6), title: "HTTP 缓存的两种方式", topics: "网络 · 缓存", status: "下一步：比较一次真实请求", mode: "精读", when: "上周")
    ]

    static func activities(now: Date = .now) -> [TodayActivity] {
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: now)
        return (0..<182).flatMap { offset -> [TodayActivity] in
            // A reproducible history with quiet days and different intensities.
            guard offset < 3 || (offset * 7 + 3) % 11 < 6 else { return [] }
            let count = 1 + (offset * 3 + 1) % 5
            return (0..<count).map { activity in
                let item = samples[(offset + activity) % samples.count]
                let date = calendar.date(byAdding: .day, value: -offset, to: today)!.addingTimeInterval(Double(9 * 3600 + activity * 1200))
                let isReview = activity == 2
                return TodayActivity(id: "prototype-\(offset)-\(activity)", date: min(date, now), kind: isReview ? "formal_review" : "lesson_step", title: item.title,
                                     sessionID: isReview ? nil : item.id, knowledgeID: isReview ? item.id : nil)
            }
        }
    }
}

struct PrototypeTodayPage: View {
    @Bindable var model: PrototypeState
    var openReview: () -> Void
    var openSummary: () -> Void
    var openLearning: (PrototypeLearningItem?) -> Void
    var openKnowledge: (UUID) -> Void
    @Environment(\.runway) private var palette
    @State private var recentExpanded = false
    @State private var activityCache = TodayActivityCache()

    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width < 820
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("今天").font(.system(size: 30, weight: .bold))
                            Text("让学过的，再想起来。").font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        PrototypeButton(title: "小结预览", symbol: "rectangle.on.rectangle", action: openSummary)
                            .help("打开独立的示例小结，不改变当前复习进度")
                        PrototypeBadge()
                    }.padding(.bottom, 2)

                    if compact {
                        reviewCard
                        HStack(spacing: 12) { ForEach(metrics) { metric($0) } }
                    } else {
                        HStack(alignment: .top, spacing: 16) {
                            reviewCard
                            VStack(spacing: 16) {
                                HStack(spacing: 16) { metric(metrics[0]); metric(metrics[1]) }
                                HStack(spacing: 16) { metric(metrics[2]); metric(metrics[3]) }
                            }.frame(width: 280)
                        }
                    }

                    TodayEntryPair(horizontal: true,
                                   previewPoint: model.previewGlassEntry == nil ? nil : .init(x: 0.28, y: 0.24),
                                   previewKind: model.previewGlassEntry == "开始学习" ? .learning : model.previewGlassEntry == "模拟考" ? .exam : nil,
                                   onLearn: { model.previewGlassEntry = nil; openLearning(nil) },
                                   onExam: { model.previewGlassEntry = nil; model.page = .exam })
                    recentLearning
                    if !model.results.isEmpty { reviewResults }
                    TodayActivityHeatmap(cache: activityCache, onOpenLearning: { id in
                        openLearning(PrototypeLearningItem.samples.first { $0.id == id })
                    }, onOpenKnowledge: openKnowledge)
                }
                .padding(24).frame(maxWidth: 1008).frame(maxWidth: .infinity)
            }
        }
        .onAppear(perform: refreshActivity)
        .onChange(of: model.today) { _, _ in refreshActivity(); recentExpanded = false }
    }

    private func refreshActivity() {
        activityCache.sourceActivities = model.today == .empty ? [] : PrototypeLearningItem.activities()
    }

    private var reviewCard: some View {
        RunwayCard(padding: 24) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Label(model.today == .paused ? "继续本轮" : "今日复习", systemImage: model.today == .paused ? "pause.circle" : "arrow.clockwise")
                        .font(.callout.weight(.medium)).foregroundStyle(.secondary)
                    Spacer(minLength: 6)
                    if model.today == .due { Text("2 个已逾期").font(.caption).foregroundStyle(.secondary) }
                }
                Spacer(minLength: 22)
                Text(heroTitle).font(.system(size: 26, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                Text(heroDetail).font(.callout).foregroundStyle(.secondary).lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true).padding(.top, 9)
                Spacer(minLength: 23)
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 10) { heroActions }
                    VStack(alignment: .leading, spacing: 8) { heroActions }
                }
            }.frame(minHeight: 200, alignment: .leading)
        }
    }

    @ViewBuilder private var heroActions: some View {
        PrototypePrimaryButton(title: heroAction, action: performHero)
        if model.today == .finished && !model.dueQuestions.isEmpty {
            PrototypeButton(title: "再复习 \(model.dueQuestions.count) 个", symbol: "arrow.right") { model.newRound(); openReview() }
        }
    }

    private var heroTitle: String {
        switch model.today {
        case .empty: "把想记住的，留在这里"
        case .unenrolled: "选一些学过的，慢慢记牢"
        case .scheduled: "今天，给记忆一点时间"
        case .due: "把学过的，再想一遍"
        case .paused: "从上次停下的地方继续"
        case .finished: model.unfinished > 0 || model.skipped > 0 ? "这一轮先到这里" : "又回顾了一遍"
        }
    }
    private var heroDetail: String {
        switch model.today {
        case .empty: "从感兴趣的问题开始。学过并保存后，再选择加入复习。"
        case .unenrolled: "知识已经收好了。选出学过、想记住的内容，安排下一次回顾。"
        case .scheduled: "下次安排在今天 18:30，共 \(model.enrolledSamples.count) 个知识点。"
        case .due: "用自己的话回忆，看看还记得多少。先准备，再开始。"
        case .paused: "已经处理 \(model.results.count) 个，还剩 \(model.unfinished) 个。原来的清单为你保留着。"
        case .finished: "回忆中的进步已经记下。跳过和未完成的内容，仍留在待复习清单。"
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
        case .empty: openLearning(nil)
        case .unenrolled, .scheduled: model.page = .library
        case .due: model.newRound(); openReview()
        case .paused, .finished: openReview()
        }
    }

    private struct Metric: Identifiable {
        var id: String { title }
        let title: String
        let value: Int
    }
    private var metrics: [Metric] {
        if model.today == .finished {
            return [.init(title: "已完成", value: model.completed), .init(title: "其中需帮助", value: model.helped),
                    .init(title: "跳过", value: model.skipped), .init(title: "未完成", value: model.unfinished)]
        }
        if model.today == .paused {
            return [.init(title: "已处理", value: model.results.count), .init(title: "本轮剩余", value: model.unfinished),
                    .init(title: "学习中", value: PrototypeLearningItem.samples.count), .init(title: "知识库", value: PrototypeQuestion.samples.count)]
        }
        let hasKnowledge = model.today != .empty
        return [.init(title: "到期复习", value: model.dueQuestions.count), .init(title: "学习中", value: hasKnowledge ? PrototypeLearningItem.samples.count : 0),
                .init(title: "待处理", value: 0), .init(title: "知识库", value: hasKnowledge ? PrototypeQuestion.samples.count : 0)]
    }
    private func metric(_ item: Metric) -> some View {
        PrototypeMetricCard(title: item.title, value: item.value)
    }

    private var recentLearning: some View {
        RunwayCard(padding: 20) {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("最近学习").font(.headline)
                    Spacer()
                    if model.today != .empty {
                        PrototypeButton(title: recentExpanded ? "收起" : "展开全部 5 条", symbol: recentExpanded ? "chevron.up" : "chevron.down") { recentExpanded.toggle() }
                            .accessibilityValue(recentExpanded ? "已展开" : "显示最近三条")
                    }
                }
                if model.today == .empty {
                    Text("你最近学过的内容，会留在这里。随时回来接着聊。").font(.callout).foregroundStyle(.secondary).padding(.vertical, 14)
                } else if recentExpanded {
                    recentRows(PrototypeLearningItem.samples)
                } else { recentRows(Array(PrototypeLearningItem.samples.prefix(3))) }
            }
        }
    }
    private func recentRows(_ items: [PrototypeLearningItem]) -> some View {
        VStack(spacing: 6) {
            ForEach(items) { item in
                Button { openLearning(item) } label: {
                    HStack(spacing: 16) {
                        Image(systemName: item.mode == "精读" ? "book.closed" : "text.bubble")
                            .font(.system(size: 18, weight: .light)).frame(width: 44, height: 48)
                            .background(palette.field.opacity(0.65), in: RoundedRectangle(cornerRadius: 13))
                        VStack(alignment: .leading, spacing: 7) {
                            Text(item.title).font(.system(size: 15, weight: .medium)).lineLimit(2)
                            Text(item.status).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }
                        Spacer(minLength: 12)
                        VStack(alignment: .trailing, spacing: 8) {
                            Text(item.when).font(.caption).foregroundStyle(.secondary)
                            Text(item.mode).font(.caption2).foregroundStyle(.tertiary)
                        }
                        Image(systemName: "arrow.up.right").font(.caption2).foregroundStyle(.secondary).padding(.leading, 4)
                    }.padding(.horizontal, 10).padding(.vertical, 13).contentShape(Rectangle())
                }.buttonStyle(InteractionButtonStyle(padding: 0, outline: .rounded(13)))
                    .modifier(PrototypeKeyboardAction(radius: 13) { openLearning(item) })
            }
        }
    }
    private var reviewResults: some View {
        RunwayCard(padding: 20) {
            VStack(alignment: .leading, spacing: 12) {
                HStack { Text("最近复习").font(.headline); Spacer(); PrototypeButton(title: "查看本轮", symbol: "arrow.up.right", action: openReview) }
                ForEach(model.results) { result in
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(result.question.topic).font(.callout.weight(.medium))
                            Text(result.arrangement).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(result.skipped ? "已跳过" : result.helped ? "在帮助下回顾" : "独立回忆")
                            .font(.caption).foregroundStyle(.secondary)
                    }.padding(.vertical, 4)
                }
            }
        }
    }
}

/// Scoped to the two Today actions. Native glass owns its optical and pointer effects.
