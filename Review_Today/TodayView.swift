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

    var body: some View {
        VStack(spacing: 0) {
            statusHeader
                .frame(maxWidth: 960)
                .padding(.horizontal, 24)
                .padding(.top, 24)
                .padding(.bottom, 16)
                .frame(maxWidth: .infinity)
            ScrollView {
            VStack(alignment: .leading, spacing: Runway.gap) {
                statusBoard
                if !activeLearningSessions.isEmpty {
                    recentLearningCard
                }
                if !todayResults.isEmpty {
                    resultsCard
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

    private var statusHeader: some View {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(dueItems.isEmpty ? "今天的学习状态" : tonightTitle)
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(runway.ink)
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
    }

    private var statusBoard: some View {
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
