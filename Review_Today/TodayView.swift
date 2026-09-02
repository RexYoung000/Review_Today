import SwiftData
import SwiftUI
import UserNotifications

struct TodayView: View {
    var coordinator: ReviewCoordinator
    var onOpenKnowledge: (UUID) -> Void
    var onOpenInbox: () -> Void
    var onOpenLibrary: () -> Void = {}
    var onOpenLearning: () -> Void

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

    private var settings: AppSettings? { settingsRows.first }
    private var developerMode: Bool { settings?.developerMode == true }

    private var dueItems: [Knowledge] {
        knowledge.filter { ReviewQueue.isDue($0, developerMode: developerMode) }
    }

    private var activeLearning: [LearningTask] {
        learningTasks.filter { !["completed", "cancelled", "terminal_failed"].contains($0.status) }
    }

    private var inboxCount: Int {
        captureTasks.filter { ["needs_attention", "retryable_failed"].contains($0.status) }.count
    }

    private var todayResults: [ReviewAttempt] {
        attempts.filter { row in
            guard row.mode != "preview", row.acked, !row.effectiveGrade.isEmpty else { return false }
            let started = reviewSessions.first(where: { $0.id == row.sessionId })?.startedAt ?? .distantPast
            return Calendar.current.isDateInToday(started)
        }
    }

    private var activeKnowledgeCount: Int {
        knowledge.filter { $0.lifecycle == "active" }.count
    }

    private var recentLearningSessions: [AgentSession] {
        Array(learningSessions.filter { $0.status == "active" }.prefix(3))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Runway.gap) {
                statusBoard
                if !recentLearningSessions.isEmpty {
                    recentLearningCard
                }
                if !todayResults.isEmpty {
                    resultsCard
                }
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
                    RunwayPrimaryButton(title: activeLearning.isEmpty ? "开始学习" : "继续学习", action: onOpenLearning)
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
                    action: onOpenLearning
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
                    Button("查看全部", action: onOpenLearning)
                        .buttonStyle(.borderless)
                }
                ForEach(recentLearningSessions, id: \.id) { session in
                    Button(action: onOpenLearning) {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(session.title)
                                    .foregroundStyle(runway.ink)
                                    .lineLimit(1)
                                Text(latestStatus(for: session))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                            Spacer()
                            MetaTag(title: LearningWorkspace.modeLabel(session.modePreset))
                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
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

    private var tonightClock: String {
        let minutes = settings?.dailyReminderMinutes ?? 21 * 60
        return String(format: "%d:%02d", minutes / 60, minutes % 60)
    }

    private func latestStatus(for session: AgentSession) -> String {
        learningTasks
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
