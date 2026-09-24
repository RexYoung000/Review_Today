import SwiftData
import SwiftUI

struct TodayView: View {
    var activityCache = TodayActivityCache()
    var coordinator: ReviewCoordinator
    var onOpenKnowledge: (UUID) -> Void
    var onOpenInbox: () -> Void
    var onOpenLibrary: () -> Void = {}
    var onOpenLearning: (UUID?) -> Void
    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway
    @Query private var captureTasks: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var reviewSessions: [ReviewSession]
    @Query private var attempts: [ReviewAttempt]
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var learningSessions: [AgentSession]
    @Query private var learningTasks: [LearningTask]
    @State private var recentExpanded = false
    @State private var examPresented = false
    @State private var recentID: UUID?

    var body: some View {
        Group {
            if examPresented {
                ExamSelectionView { examPresented = false }
            } else if let id = recentID, let session = learningSessions.first(where: { $0.id == id }) {
                RecentLearningDetail(session: session, back: { recentID = nil }, resume: { onOpenLearning(id) })
            } else {
                dashboard
            }
        }.background(PaperSurface()).navigationTitle("今天")
    }

    private var dashboard: some View {
        // Read query results and derive counts once per render. The heatmap retains its existing cache.
        let items = knowledge, tasks = learningTasks, sessions = learningSessions, reviews = reviewSessions
        let activeSessions = sessions.filter { $0.status == "active" }
        let projection = TodayReviewProjection(knowledge: items, sessions: reviews, developerMode: settingsRows.first?.developerMode == true)
        let latestSummary = projection.latest.map { ReviewRoundSummary(session: $0, attempts: attempts) }
        let learningCount = LearningGoalContinuity.unfinished(tasks, sessions: sessions).count
        let inboxCount = captureTasks.filter { ["needs_attention", "retryable_failed"].contains($0.status) }.count +
            tasks.filter { LearningDecisionInbox.includes($0, sessions: sessions) }.count +
            activeSessions.reduce(0) { $0 + TopicCaptureOffer.read($1.captureOffersJSON).filter(\.needsAttention).count }
        let libraryCount = items.filter { $0.lifecycle == "active" }.count
        let metrics: [(String, Int)] = projection.kind == .finished && latestSummary != nil ? [
            ("已完成", latestSummary!.completed), ("其中需帮助", latestSummary!.helped),
            ("跳过", latestSummary!.skipped), ("未完成", latestSummary!.unfinished)
        ] : [("到期复习", projection.due.count), ("学习中", learningCount), ("待处理", inboxCount), ("知识库", libraryCount)]
        return GeometryReader { geometry in
            VStack(spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("今天").font(.system(size: 30, weight: .bold))
                        Text("让学过的，再想起来。").font(.callout).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    ReviewActionButton(title: "最近小结", symbol: "rectangle.on.rectangle") {
                        if let latest = projection.latest { openSummary(latest) }
                    }.disabled(projection.latest == nil)
                        .help(projection.latest == nil ? "完成一轮复习后，可在这里查看小结" : "查看最近一轮复习小结")
                }.padding(.horizontal, 24).padding(.top, 24).padding(.bottom, 18)
                    .frame(maxWidth: 1008).frame(maxWidth: .infinity)
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        if geometry.size.width < 850 {
                            reviewCard(projection, summary: latestSummary)
                            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: geometry.size.width < 570 ? 2 : 4), spacing: 12) {
                                metricCards(metrics, summary: projection.kind == .finished)
                            }
                        } else {
                            HStack(alignment: .top, spacing: 16) {
                                reviewCard(projection, summary: latestSummary)
                                LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 16) {
                                    metricCards(metrics, summary: projection.kind == .finished)
                                }.frame(width: 280)
                            }
                        }
                        TodayEntryPair(horizontal: geometry.size.width >= 570,
                                       onLearn: { onOpenLearning(nil) },
                                       onExam: { examPresented = true })
                        recentLearningCard(sessions: activeSessions)
                        if let latest = projection.latest, let summary = latestSummary { recentReviewCard(latest, summary: summary) }
                        TodayActivityHeatmap(cache: activityCache, onOpenLearning: onOpenLearning, onOpenKnowledge: onOpenKnowledge)
                    }.padding(.horizontal, 24).padding(.bottom, 24).frame(maxWidth: 1008).frame(maxWidth: .infinity)
                }
            }
        }
    }
    private func metricCards(_ metrics: [(String, Int)], summary: Bool) -> some View {
        ForEach(metrics.indices, id: \.self) { index in
            Button {
                if summary { if let latest = reviewSessions.filter({ $0.protocolVersion == 2 && $0.mode == "formal" && $0.endedAt != nil && !ReviewLedger.queue($0).isEmpty }).max(by: { ($0.endedAt ?? .distantPast) < ($1.endedAt ?? .distantPast) }) { openSummary(latest) } }
                else { switch index { case 0: openReview(); case 1: onOpenLearning(nil); case 2: onOpenInbox(); default: onOpenLibrary() } }
            } label: { ReviewMetricCard(title: metrics[index].0, value: metrics[index].1) }
            .buttonStyle(InteractionButtonStyle(padding: 0, outline: .rounded(Runway.chipRadius)))
            .accessibilityLabel("\(metrics[index].0) \(metrics[index].1)")
        }
    }
    private func reviewCard(_ p: TodayReviewProjection, summary: ReviewRoundSummary?) -> some View {
        RunwayCard(padding: 24) {
            VStack(alignment: .leading, spacing: 0) {
                Label(p.kind == .paused ? "继续本轮" : "今日复习", systemImage: p.kind == .paused ? "pause.circle" : "arrow.clockwise")
                    .font(.callout.weight(.medium)).foregroundStyle(.secondary)
                Spacer(minLength: 22)
                Text(heroTitle(p, summary: summary)).font(.system(size: 26, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                Text(heroDetail(p)).font(.callout).foregroundStyle(.secondary).lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true).padding(.top, 9)
                Spacer(minLength: 22)
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 14) { heroActions(p) }
                    VStack(alignment: .leading, spacing: 10) { heroActions(p) }
                }
            }.frame(minHeight: 200, alignment: .leading)
        }
    }
    private func heroTitle(_ p: TodayReviewProjection, summary: ReviewRoundSummary?) -> String {
        switch p.kind {
        case .empty: "让今天的好奇，留下来"
        case .unenrolled: "挑一些学过的，加入复习"
        case .scheduled: "记忆正在沉淀"
        case .due: "把学过的，再想起来"
        case .paused: "接着上次，慢慢回想"
        case .finished: summary?.title ?? "这一轮先到这里"
        }
    }
    private func heroDetail(_ p: TodayReviewProjection) -> String {
        switch p.kind {
        case .empty: return "还没有保存的知识。从一个问题开始，值得记住的内容可以留下来。"
        case .unenrolled: return "知识已经保存。选择你学过的内容，之后会在适合的时候提醒你回顾。"
        case .scheduled: return p.nextDue.map { "下次复习：\($0.formatted(date: .abbreviated, time: .shortened))。现在可以继续学习，也可以管理复习内容。" } ?? "当前没有到期内容，可以继续学习。"
        case .due: return "今天有 \(p.due.count) 个知识点可以回顾，先从逾期的内容开始。"
        case .paused:
            guard let session = p.resumable else { return "已经保存的结果会保留，可以继续未完成清单。" }
            return "已处理 \(session.currentIndex) 个，还剩 \(max(0, ReviewLedger.queue(session).count - session.currentIndex)) 个。继续时沿用这一轮的清单。"
        case .finished: return "已处理的回忆留在小结里；跳过或未完成的内容，仍会保留后续安排。"
        }
    }
    @ViewBuilder private func heroActions(_ p: TodayReviewProjection) -> some View {
        switch p.kind {
        case .empty: ReviewStartButton(title: "开始学习") { onOpenLearning(nil) }
        case .unenrolled: ReviewStartButton(title: "选择复习内容", action: onOpenLibrary)
        case .scheduled: ReviewStartButton(title: "管理复习内容", action: onOpenLibrary)
        case .due: ReviewStartButton(title: "准备复习", action: openReview)
        case .paused: ReviewStartButton(title: "继续本轮", action: openReview)
        case .finished:
            ReviewStartButton(title: "查看本轮小结") { if let latest = p.latest { openSummary(latest) } }
            if !p.due.isEmpty { ReviewActionButton(title: "再复习 \(p.due.count) 个", action: openReview) }
            else { ReviewActionButton(title: "管理复习内容", action: onOpenLibrary) }
        }
    }
    private func openReview() {
        coordinator.startFormal(knowledgeIDs: ReviewQueue.ordered(knowledge, developerMode: settingsRows.first?.developerMode == true).map(\.id))
        openWindow(id: "review")
    }
    private func openSummary(_ session: ReviewSession) { coordinator.showSummary(sessionID: session.id); openWindow(id: "review") }

    private func recentLearningCard(sessions: [AgentSession]) -> some View {
        RunwayCard(padding: 20) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("最近学习").font(.headline); Spacer()
                    if sessions.count > 3 { ReviewActionButton(title: recentExpanded ? "收起" : "展开全部") { recentExpanded.toggle() } }
                }
                if sessions.isEmpty {
                    Text("还没有学习记录。开始一段对话后，可以从这里接着上次的内容。")
                        .font(.callout).foregroundStyle(.secondary).padding(.vertical, 12)
                }
                ForEach(recentExpanded ? sessions : Array(sessions.prefix(3)), id: \.id) { session in
                    Button { recentID = session.id } label: {
                        HStack(spacing: 14) {
                            Image(systemName: "text.book.closed").font(.system(size: 21, weight: .light))
                                .frame(width: 44, height: 48).background(runway.field.opacity(0.6), in: RoundedRectangle(cornerRadius: 13))
                            VStack(alignment: .leading, spacing: 7) {
                                Text(session.title).font(.system(size: 15, weight: .medium)).foregroundStyle(runway.ink).lineLimit(2)
                                TodaySessionStatus(sessionID: session.id).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                            VStack(alignment: .trailing, spacing: 7) {
                                Text(session.updatedAt, format: .dateTime.month().day()).font(.caption)
                                Text(LearningWorkspace.modeLabel(session.modePreset)).font(.caption2)
                            }.foregroundStyle(.secondary)
                            Image(systemName: "arrow.up.right").font(.caption).foregroundStyle(.secondary)
                        }.padding(.horizontal, 10).padding(.vertical, 13).contentShape(Rectangle())
                    }.buttonStyle(InteractionButtonStyle(padding: 0))
                }
            }
        }
    }
    private func recentReviewCard(_ session: ReviewSession, summary: ReviewRoundSummary) -> some View {
        RunwayCard(padding: 20) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("最近复习").font(.headline); Spacer()
                    ReviewActionButton(title: "查看小结", symbol: "arrow.up.right") { openSummary(session) }
                }
                Text("完成 \(summary.completed) · 其中需帮助 \(summary.helped) · 跳过 \(summary.skipped) · 未完成 \(summary.unfinished)")
                    .font(.callout).foregroundStyle(.secondary)
                Text(session.endedAt ?? session.startedAt, format: .dateTime.month().day().hour().minute()).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    static func firstURL(in text: String) -> String? {
        let pattern = #"https?://[^\s<>\"]+"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, range: range),
              let swiftRange = Range(match.range, in: text) else { return nil }
        return String(text[swiftRange]).trimmingCharacters(in: CharacterSet(charactersIn: ").,，。]」』"))
    }

    static func todayStamp() -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: .now)
    }
}
