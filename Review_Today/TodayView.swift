import SwiftData
import SwiftUI
import UserNotifications

struct TodayView: View {
    var activityCache = TodayActivityCache()
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
    @State private var recentExpanded = false
    private var settings: AppSettings? { settingsRows.first }
    private var developerMode: Bool { settings?.developerMode == true }

    // Actions re-evaluate the clock and developer settings at activation time.
    private var dueItems: [Knowledge] {
        let developerMode = developerMode
        let now = Date.now
        return knowledge.filter { ReviewQueue.isDue($0, developerMode: developerMode, now: now) }
    }

    var body: some View {
        // Query getters and derived lists are evaluated once per body, not once
        // per stat/header/row. In particular, do not read settings per knowledge.
        let items = knowledge
        let tasks = learningTasks
        let sessions = learningSessions
        let activeSessions = sessions.filter { $0.status == "active" }
        let developerMode = developerMode
        let now = Date.now
        let dueCount = items.filter { ReviewQueue.isDue($0, developerMode: developerMode, now: now) }.count
        let learningCount = LearningGoalContinuity.unfinished(tasks, sessions: sessions).count
        let inboxCount = captureTasks.filter { ["needs_attention", "retryable_failed"].contains($0.status) }.count +
            tasks.filter { LearningDecisionInbox.includes($0, sessions: sessions) }.count +
            activeSessions.reduce(0) { $0 + TopicCaptureOffer.read($1.captureOffersJSON).filter(\.needsAttention).count }
        let libraryCount = items.filter { $0.lifecycle == "active" }.count
        let reviews = reviewSessions
        let results = attempts.filter { row in
            guard row.mode != "preview", row.acked, !row.effectiveGrade.isEmpty else { return false }
            let completed = row.completedAt ?? reviews.first(where: { $0.id == row.sessionId })?.endedAt
            return completed.map(Calendar.current.isDateInToday) ?? false
        }
        VStack(spacing: 0) {
            statusHeader(dueCount: dueCount, learningCount: learningCount)
                .frame(maxWidth: 960)
                .padding(.horizontal, 24)
                .padding(.top, 24)
                .padding(.bottom, 16)
                .frame(maxWidth: .infinity)
            ScrollView {
            VStack(alignment: .leading, spacing: Runway.gap) {
                statusBoard(dueCount: dueCount, learningCount: learningCount, inboxCount: inboxCount, libraryCount: libraryCount)
                if !activeSessions.isEmpty {
                    recentLearningCard(sessions: activeSessions)
                }
                if !results.isEmpty {
                    resultsCard(results: results, knowledge: items)
                }
                TodayActivityHeatmap(cache: activityCache, onOpenLearning: onOpenLearning, onOpenKnowledge: onOpenKnowledge)
            }
            .frame(maxWidth: 960)
            .padding(.horizontal, 24)
            .padding(.bottom, 24)
            .frame(maxWidth: .infinity)
        }
        }
        .background(PaperSurface())
        .navigationTitle(String(localized: "今天"))

    }

    private func statusHeader(dueCount: Int, learningCount: Int) -> some View {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(dueCount == 0 ? "今天的学习状态" : tonightTitle)
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(runway.ink)
                }
                Spacer(minLength: 8)
                if dueCount > 0 {
                    RunwayPrimaryButton(title: String(localized: "现在开始")) {
                        coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                        openWindow(id: "review")
                    }
                } else {
                    RunwayPrimaryButton(title: learningCount == 0 ? "开始学习" : "继续学习") { onOpenLearning(nil) }
                }
            }
    }

    private func statusBoard(dueCount: Int, learningCount: Int, inboxCount: Int, libraryCount: Int) -> some View {
            StatStrip(items: [
                StatCell(
                    id: "due",
                    value: "\(dueCount)",
                    title: String(localized: "今晚复习"),
                    action: dueCount == 0 ? nil : {
                        coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                        openWindow(id: "review")
                    }
                ),
                StatCell(
                    id: "learning",
                    value: "\(learningCount)",
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
                    value: "\(libraryCount)",
                    title: String(localized: "知识库"),
                    action: onOpenLibrary
                )
            ])
    }

    private func recentLearningCard(sessions: [AgentSession]) -> some View {
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
                            recentSessionRows(sessions)
                        }
                        .frame(maxHeight: 280)
                    } else {
                        recentSessionRows(Array(sessions.prefix(3)))
                    }
                }
            }
        }
    }

    private func recentSessionRows(_ sessions: [AgentSession]) -> some View {
        VStack(spacing: 4) {
            ForEach(sessions, id: \.id) { session in
                    Button { onOpenLearning(session.id) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(session.title)
                                    .foregroundStyle(runway.ink)
                                    .lineLimit(1)
                                HStack(spacing: 5) {
                                    ForEach(Array(session.displayTopicTags.prefix(2)), id: \.self) { Text($0) }
                                    if !session.displayTopicTags.isEmpty { Text("·") }
                                    TodaySessionStatus(sessionID: session.id)
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

    private func resultsCard(results: [ReviewAttempt], knowledge: [Knowledge]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(String(localized: "今日复习结果"))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(runway.ink)
            VStack(alignment: .leading, spacing: 10) {
                ForEach(results, id: \.attemptId) { row in
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
                            .foregroundStyle(runway.information)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
        .shadow(color: runway.liftShadow, radius: 8, y: 2)
    }

    private var tonightTitle: String { "今晚 \(tonightClock) 复习" }

    private var tonightClock: String {
        let minutes = settings?.dailyReminderMinutes ?? 21 * 60
        return String(format: "%d:%02d", minutes / 60, minutes % 60)
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
