import SwiftData
import SwiftUI
import UserNotifications

struct TodayView: View {
    var coordinator: ReviewCoordinator
    var onOpenKnowledge: (UUID) -> Void
    var onOpenInbox: () -> Void
    var onOpenLibrary: () -> Void = {}
    var onOpenLearning: (UUID?) -> Void

    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway
    @Query private var captureTasks: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var reviewSessions: [ReviewSession]
    @Query private var attempts: [ReviewAttempt]
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var learningSessions: [AgentSession]
    @Query private var learningTasks: [LearningTask]
    @Query private var agentRuns: [AgentRun]
    @State private var recentExpanded = false
    @State private var selectedActivityDate: Date?

    private struct ActivityItem: Identifiable {
        var id: String
        var date: Date
        var kind: String
        var title: String
        var sessionID: UUID?
        var knowledgeID: UUID?
    }

    private var settings: AppSettings? { settingsRows.first }
    private var developerMode: Bool { settings?.developerMode == true }

    private var dueItems: [Knowledge] {
        knowledge.filter { ReviewQueue.isDue($0, developerMode: developerMode) }
    }

    private var activeLearning: [LearningTask] {
        learningTasks.filter { !["completed", "cancelled", "terminal_failed"].contains($0.status) }
    }

    private var inboxCount: Int {
        captureTasks.filter { ["needs_attention", "retryable_failed"].contains($0.status) }.count +
        learningTasks.filter { LearningDecisionInbox.includes($0, sessions: learningSessions) }.count
    }

    private var todayResults: [ReviewAttempt] {
        attempts.filter { row in
            guard row.mode != "preview", row.acked, !row.effectiveGrade.isEmpty else { return false }
            let completed = row.completedAt ?? reviewSessions.first(where: { $0.id == row.sessionId })?.endedAt
            return completed.map(Calendar.current.isDateInToday) ?? false
        }
    }

    private var activeKnowledgeCount: Int {
        knowledge.filter { $0.lifecycle == "active" }.count
    }

    private var activeLearningSessions: [AgentSession] {
        learningSessions.filter { $0.status == "active" }
    }

    private var recentLearningSessions: [AgentSession] {
        recentExpanded ? activeLearningSessions : Array(activeLearningSessions.prefix(3))
    }

    private var activityItems: [ActivityItem] {
        let runItems = agentRuns.compactMap { run -> ActivityItem? in
            guard run.status == "completed", let kind = run.activityKind, let date = run.completedAt else { return nil }
            let title = learningSessions.first(where: { $0.id == run.sessionID })?.title ?? "学习会话"
            return ActivityItem(id: "run-\(run.id)", date: date, kind: kind, title: title, sessionID: run.sessionID)
        }
        let reviewItems = attempts.compactMap { attempt -> ActivityItem? in
            guard attempt.mode != "preview", attempt.acked, !attempt.effectiveGrade.isEmpty,
                  let date = attempt.completedAt else { return nil }
            let title = knowledge.first(where: { $0.id == attempt.knowledgeId }).map { KnowledgeLexicon.keyword(for: $0, clipped: false) } ?? "正式复习"
            return ActivityItem(id: "review-\(attempt.attemptId)", date: date, kind: "formal_review", title: title, knowledgeID: attempt.knowledgeId)
        }
        return runItems + reviewItems
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Runway.gap) {
                statusBoard
                if !activeLearningSessions.isEmpty {
                    recentLearningCard
                }
                if !todayResults.isEmpty {
                    resultsCard
                }
                activityHeatmap
            }
            .padding(24)
        }
        .background(PaperSurface())
        .navigationTitle(String(localized: "今天"))
        .onAppear {
            ReminderNotifications.request()
            ReminderNotifications.scheduleDaily(
                minuteOfDay: settings?.dailyReminderMinutes ?? 21 * 60,
                hasDue: !dueItems.isEmpty,
                skippedToday: settings?.skipToday == Self.todayStamp()
            )
            backfillClearReviewDates()
        }
    }

    private var statusBoard: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(dueItems.isEmpty ? "今天的学习状态" : tonightTitle)
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(runway.ink)
                    Text(boardSubtitle)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                if !dueItems.isEmpty {
                    RunwayPrimaryButton(title: String(localized: "现在开始")) {
                        coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                        openWindow(id: "review")
                    }
                } else {
                    RunwayPrimaryButton(title: activeLearning.isEmpty ? "开始学习" : "继续学习") { onOpenLearning(nil) }
                }
            }
            StatStrip(items: [
                StatCell(
                    id: "due",
                    value: "\(dueItems.count)",
                    title: String(localized: "今晚复习"),
                    action: dueItems.isEmpty ? nil : {
                        coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                        openWindow(id: "review")
                    }
                ),
                StatCell(
                    id: "learning",
                    value: "\(activeLearning.count)",
                    title: String(localized: "学习中"),
                    action: { onOpenLearning(nil) }
                ),
                StatCell(
                    id: "inbox",
                    value: "\(inboxCount)",
                    title: String(localized: "待处理"),
                    action: inboxCount == 0 ? nil : onOpenInbox
                ),
                StatCell(
                    id: "library",
                    value: "\(activeKnowledgeCount)",
                    title: String(localized: "知识库"),
                    action: onOpenLibrary
                )
            ])
        }
    }

    private var recentLearningCard: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("最近学习")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Button(recentExpanded ? "收起" : "展开") { recentExpanded.toggle() }
                        .buttonStyle(.borderless)
                }
                Group {
                    if recentExpanded {
                        ScrollView {
                            recentSessionRows
                        }
                        .frame(maxHeight: 280)
                    } else {
                        recentSessionRows
                    }
                }
            }
        }
    }

    private var recentSessionRows: some View {
        VStack(spacing: 4) {
            ForEach(recentLearningSessions, id: \.id) { session in
                    Button { onOpenLearning(session.id) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(session.title)
                                    .foregroundStyle(runway.ink)
                                    .lineLimit(1)
                                HStack(spacing: 5) {
                                    ForEach(Array(session.displayTopicTags.prefix(2)), id: \.self) { Text($0) }
                                    if !session.displayTopicTags.isEmpty { Text("·") }
                                    Text(latestStatus(for: session))
                                }.font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                            Spacer()
                            MetaTag(title: LearningWorkspace.modeLabel(session.modePreset))
                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(InteractionButtonStyle(padding: 4))
                    .padding(.vertical, 5)
            }
        }
    }

    private var activityHeatmap: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 44) {
                    activityStat(value: activeDayCount, title: "活跃天数")
                    activityStat(value: currentStreak, title: "当前连续天数")
                    activityStat(value: longestStreak, title: "最长连续天数")
                    Spacer()
                    Text("最近 26 周").font(.caption).foregroundStyle(.secondary)
                }
                ViewThatFits(in: .horizontal) {
                    heatmapGrid(cell: 16, spacing: 5)
                    heatmapGrid(cell: 12, spacing: 4)
                }
                HStack(spacing: 5) {
                    Text("较少")
                    ForEach(0 ..< 5, id: \.self) { level in
                        RoundedRectangle(cornerRadius: 3).fill(activityColor(level: level)).frame(width: 14, height: 14)
                    }
                    Text("较多")
                }
                .font(.caption2).foregroundStyle(.secondary)
                if let selectedActivityDate {
                    Divider()
                    activityDayDetails(selectedActivityDate)
                }
            }
        }
    }

    private func activityStat(value: Int, title: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(value) 天").font(.title2.bold()).foregroundStyle(runway.ink)
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func heatmapGrid(cell: CGFloat, spacing: CGFloat) -> some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(spacing: spacing) {
                ForEach(Self.weekdayLabels, id: \.self) { Text($0).frame(width: 12, height: cell) }
            }.font(.caption2).foregroundStyle(.secondary)
            HStack(spacing: spacing) {
                ForEach(0 ..< 26, id: \.self) { week in
                    VStack(spacing: spacing) {
                        ForEach(0 ..< 7, id: \.self) { day in
                            heatmapCell(date: Calendar.current.date(byAdding: .day, value: week * 7 + day, to: heatmapStart)!, size: cell)
                        }
                    }
                }
            }
        }
    }

    private func heatmapCell(date: Date, size: CGFloat) -> some View {
        let items = activities(on: date)
        let future = date > Calendar.current.startOfDay(for: .now)
        return Button {
            if !items.isEmpty { selectedActivityDate = Calendar.current.startOfDay(for: date) }
        } label: {
            RoundedRectangle(cornerRadius: 4, style: .continuous)
                .fill(future ? Color.clear : activityColor(level: intensity(for: items.count)))
                .overlay(RoundedRectangle(cornerRadius: 4).stroke(runway.hairline.opacity(future ? 0.35 : 0)))
                .frame(width: size, height: size)
        }
        .buttonStyle(.plain)
        .disabled(items.isEmpty)
        .help(activityHelp(date: date, items: items))
        .accessibilityLabel(activityHelp(date: date, items: items))
    }

    private func activityDayDetails(_ date: Date) -> some View {
        let rows = activities(on: date).sorted { $0.date < $1.date }
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(date, format: .dateTime.year().month().day()).font(.subheadline.weight(.semibold))
                Text("\(rows.count) 次有效活动").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(rows) { item in
                Button {
                    if let sessionID = item.sessionID { onOpenLearning(sessionID) }
                    else if let knowledgeID = item.knowledgeID { onOpenKnowledge(knowledgeID) }
                } label: {
                    HStack {
                        Text(activityKindLabel(item.kind)).font(.caption).foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
                        Text(item.title).foregroundStyle(runway.ink).lineLimit(1)
                        Spacer()
                        Text(item.date, style: .time).font(.caption).foregroundStyle(.secondary)
                        Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary)
                    }.contentShape(Rectangle())
                }.buttonStyle(InteractionButtonStyle(padding: 4))
            }
        }
    }

    private var resultsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(String(localized: "今日复习结果"))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(runway.ink)
            VStack(alignment: .leading, spacing: 10) {
                ForEach(todayResults, id: \.attemptId) { row in
                    let item = knowledge.first(where: { $0.id == row.knowledgeId })
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.map { KnowledgeLexicon.keyword(for: $0, clipped: false) } ?? String(localized: "知识点"))
                                .font(.callout)
                                .foregroundStyle(runway.ink)
                            if let due = item?.dueAt {
                                Text("下次 \(due.formatted(date: .abbreviated, time: .shortened))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        Text(MasteryCopy.label(row.effectiveGrade))
                            .font(.caption.weight(.medium))
                            .foregroundStyle(runway.agent)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
        .shadow(color: runway.liftShadow, radius: 8, y: 2)
    }

    private var boardSubtitle: String {
        if !activeLearning.isEmpty { return "有 \(activeLearning.count) 个学习任务正在继续" }
        if dueItems.isEmpty { return "没有到期知识，可以开始新的学习" }
        return "预计约 \(dueItems.count) 分钟"
    }

    private var tonightTitle: String { "今晚 \(tonightClock) 复习" }

    private static var weekdayLabels: [String] {
        let formatter = DateFormatter()
        formatter.locale = .current
        let symbols = formatter.veryShortStandaloneWeekdaySymbols ?? ["日", "一", "二", "三", "四", "五", "六"]
        let offset = max(0, min(6, Calendar.current.firstWeekday - 1))
        return Array(symbols[offset...]) + Array(symbols[..<offset])
    }

    private var heatmapStart: Date {
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: .now)
        let weekday = calendar.component(.weekday, from: today)
        let offset = (weekday - calendar.firstWeekday + 7) % 7
        let thisWeek = calendar.date(byAdding: .day, value: -offset, to: today)!
        return calendar.date(byAdding: .weekOfYear, value: -25, to: thisWeek)!
    }

    private var activeDates: [Date] {
        LearningActivityCalendar.uniqueDays(activityItems.map(\.date))
    }

    private var activeDayCount: Int { activeDates.count }

    private var currentStreak: Int {
        LearningActivityCalendar.currentStreak(activeDates)
    }

    private var longestStreak: Int {
        LearningActivityCalendar.longestStreak(activeDates)
    }

    private func activities(on date: Date) -> [ActivityItem] {
        activityItems.filter { Calendar.current.isDate($0.date, inSameDayAs: date) }
    }

    private func intensity(for count: Int) -> Int {
        LearningActivityCalendar.intensity(count)
    }

    private func activityColor(level: Int) -> Color {
        switch level {
        case 0: return runway.field.opacity(0.72)
        case 1: return runway.agent.opacity(0.22)
        case 2: return runway.agent.opacity(0.42)
        case 3: return runway.agent.opacity(0.68)
        default: return runway.agent
        }
    }

    private func activityHelp(date: Date, items: [ActivityItem]) -> String {
        let counts = Dictionary(grouping: items, by: \.kind).mapValues(\.count)
        let details = counts.sorted(by: { $0.key < $1.key })
            .map { "\(activityKindLabel($0.key)) \($0.value)" }.joined(separator: "，")
        return "\(date.formatted(date: .abbreviated, time: .omitted))：\(items.count) 次\(details.isEmpty ? "" : "（\(details)）")"
    }

    private func activityKindLabel(_ kind: String) -> String {
        switch kind {
        case "lesson_step": return "资料学习"
        case "formal_review": return "正式复习"
        default: return "知识回答"
        }
    }

    private func backfillClearReviewDates() {
        var changed = false
        for attempt in attempts where attempt.mode != "preview" && attempt.acked && !attempt.effectiveGrade.isEmpty && attempt.completedAt == nil {
            guard let review = reviewSessions.first(where: { $0.id == attempt.sessionId }) else { continue }
            attempt.completedAt = review.endedAt ?? review.startedAt
            changed = true
        }
        if changed { try? modelContext.save() }
    }

    private var tonightClock: String {
        let minutes = settings?.dailyReminderMinutes ?? 21 * 60
        return String(format: "%d:%02d", minutes / 60, minutes % 60)
    }

    private func latestStatus(for session: AgentSession) -> String {
        if let task = learningTasks.filter({ $0.sessionID == session.id && $0.learningPlanJSON != nil }).max(by: { $0.updatedAt < $1.updatedAt }),
           let plan = ConversationProcessor.object(task.learningPlanJSON),
           let steps = plan["steps"] as? [[String: Any]],
           let current = steps.first(where: { $0["id"] as? String == plan["current_step_id"] as? String }),
           let title = current["title"] as? String {
            return task.status == "completed" ? "查看本次学习小结" : "上次学到：" + title
        }
        if let run = agentRuns.filter({ $0.sessionID == session.id }).max(by: { $0.updatedAt < $1.updatedAt }) {
            return run.userSummary
        }
        return learningTasks
            .filter { $0.sessionID == session.id }
            .max(by: { $0.updatedAt < $1.updatedAt })?
            .userSummary ?? "尚未开始任务"
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
