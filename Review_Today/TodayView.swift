import AppKit
import AVFoundation
import SwiftData
import SwiftUI
import UserNotifications

struct TodayView: View {
    var monitor: AgentServiceMonitor
    var coordinator: ReviewCoordinator
    var onOpenKnowledge: (UUID) -> Void
    var onOpenInbox: () -> Void
    var onOpenLibrary: () -> Void = {}

    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway
    @Query(sort: \CaptureTask.createdAt, order: .reverse) private var tasks: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var sessions: [ReviewSession]
    @Query private var attempts: [ReviewAttempt]
    @State private var draft = ""
    @State private var recorder = VoiceRecorder()
    @State private var micAllowed = false
    @State private var notifyAllowed = false

    private var settings: AppSettings? { settingsRows.first }
    private var developerMode: Bool { settings?.developerMode == true }

    private var dueItems: [Knowledge] {
        knowledge.filter { ReviewQueue.isDue($0, developerMode: developerMode) }
    }

    private var forming: [CaptureTask] {
        tasks.filter { !["completed", "cancelled"].contains($0.status) }
    }

    private var inboxCount: Int {
        tasks.filter { $0.status == "needs_attention" }.count
    }

    private var todayReceipts: [CaptureTask] {
        tasks.filter { $0.status == "completed" && Calendar.current.isDateInToday($0.updatedAt) }
    }

    private var todayResults: [ReviewAttempt] {
        attempts.filter { row in
            guard row.mode != "preview", !row.effectiveGrade.isEmpty else { return false }
            let started = sessions.first(where: { $0.id == row.sessionId })?.startedAt ?? .distantPast
            return Calendar.current.isDateInToday(started)
        }
    }

    private var activeKnowledgeCount: Int {
        knowledge.filter { $0.lifecycle == "active" }.count
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                headline
                metricGrid
                captureCard
                HStack(alignment: .top, spacing: 16) {
                    agentWorkCard
                    receiptsCard
                }
                if !todayResults.isEmpty {
                    resultsCard
                }
            }
            .padding(28)
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
            refreshPermissions()
        }
    }

    private var headline: some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(dueItems.isEmpty ? String(localized: "今天无需复习") : tonightTitle)
                    .font(.system(size: 34, weight: .bold))
                Text(agentRailStatus)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            CoachMark(pose: coachPose, size: 56)
            if !dueItems.isEmpty {
                RunwayPrimaryButton(title: String(localized: "现在开始")) {
                    coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                    openWindow(id: "review")
                }
            }
        }
    }

    private var metricGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 16), GridItem(.flexible(), spacing: 16)], spacing: 16) {
            MetricTile(
                title: String(localized: "今晚复习"),
                value: dueItems.isEmpty ? "0" : "\(dueItems.count)",
                note: dueItems.isEmpty
                    ? String(localized: "没有到期的知识")
                    : "预计约 \(dueItems.count) 分钟 · \(tonightClock)",
                emphasized: !dueItems.isEmpty,
                action: dueItems.isEmpty ? nil : {
                    coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                    openWindow(id: "review")
                }
            )
            MetricTile(
                title: String(localized: "正在形成"),
                value: "\(forming.count)",
                note: forming.first?.userStatus ?? String(localized: "没有正在处理的内容")
            )
            MetricTile(
                title: String(localized: "待处理"),
                value: "\(inboxCount)",
                note: inboxCount == 0
                    ? String(localized: "没有需要你确认的事项")
                    : String(localized: "需要你确认来源或冲突"),
                emphasized: inboxCount > 0,
                action: inboxCount == 0 ? nil : onOpenInbox
            )
            MetricTile(
                title: String(localized: "知识库"),
                value: "\(activeKnowledgeCount)",
                note: String(localized: "在用的知识点"),
                action: onOpenLibrary
            )
        }
    }

    private var captureCard: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 14) {
                Text(String(localized: "记住点什么"))
                    .font(.headline)
                PaperWell {
                    TextField(
                        String(localized: "输入文字或粘贴链接……"),
                        text: $draft,
                        axis: .vertical
                    )
                    .textFieldStyle(.plain)
                    .font(.title3)
                    .lineLimit(3 ... 6)
                }
                HStack {
                    Button(recorder.isRecording ? String(localized: "停止录音") : String(localized: "语音")) {
                        AVCaptureDevice.requestAccess(for: .audio) { granted in
                            DispatchQueue.main.async { micAllowed = granted }
                        }
                        recorder.toggle()
                        if !recorder.isRecording, let url = recorder.lastFileURL {
                            saveVoice(url)
                        }
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(recorder.isRecording ? Color.orange : .secondary)
                    Spacer()
                    if !dueItems.isEmpty {
                        Button(String(localized: "现在开始")) {
                            coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                            openWindow(id: "review")
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(runway.action)
                        .keyboardShortcut(.return, modifiers: [.command, .shift])
                    }
                    RunwayPrimaryButton(
                        title: String(localized: "记住"),
                        enabled: !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                        action: saveDraft
                    )
                    .keyboardShortcut(.return, modifiers: [.command])
                }
            }
        }
    }

    private var agentWorkCard: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text(String(localized: "Agent 正在做"))
                        .font(.headline)
                    Spacer()
                    Circle()
                        .fill(forming.isEmpty ? Color.secondary.opacity(0.25) : runway.agent)
                        .frame(width: 8, height: 8)
                }
                if forming.isEmpty {
                    Text(String(localized: "空闲。记下内容后，我会在这里展开整理步骤。"))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 88, alignment: .topLeading)
                } else {
                    ForEach(forming.prefix(3), id: \.id) { task in
                        agentTaskBlock(task)
                    }
                }
            }
        }
    }

    private func agentTaskBlock(_ task: CaptureTask) -> some View {
        let steps = CaptureProgress.steps(for: task)
        let needsYou = task.status == "needs_attention"
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(task.userStatus)
                    .font(.subheadline.weight(.medium))
                Spacer()
                if needsYou {
                    Button(String(localized: "去处理"), action: onOpenInbox)
                        .buttonStyle(.plain)
                        .foregroundStyle(runway.action)
                        .font(.subheadline.weight(.semibold))
                }
            }
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Circle()
                        .strokeBorder(index == steps.count - 1 ? runway.agent : Color.secondary.opacity(0.35), lineWidth: 1.5)
                        .background(Circle().fill(index == steps.count - 1 ? runway.agent : .clear))
                        .frame(width: 8, height: 8)
                    Text(step)
                        .font(.caption)
                        .foregroundStyle(index == steps.count - 1 ? Color.primary : Color.secondary)
                }
            }
        }
    }

    private var receiptsCard: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 14) {
                Text(String(localized: "今天新增"))
                    .font(.headline)
                if todayReceipts.isEmpty {
                    Text(String(localized: "还没有新的整理结果"))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 88, alignment: .topLeading)
                } else {
                    ForEach(todayReceipts.prefix(4), id: \.id) { task in
                        receiptRow(task)
                        if task.id != todayReceipts.prefix(4).last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }

    private func receiptRow(_ task: CaptureTask) -> some View {
        let receipt = Self.decodeReceipt(task.receiptJSON)
        return VStack(alignment: .leading, spacing: 8) {
            Text(receiptLine(task, receipt))
            if let receipt {
                Text("\(receipt.theme) · \(receipt.knowledgeCount) 个知识点")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let first = task.source?.knowledgeItems.first {
                HStack(spacing: 14) {
                    Button(String(localized: "立即试一题")) {
                        coordinator.startPreview(knowledgeID: first.id)
                        openWindow(id: "review")
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(runway.action)
                    .font(.subheadline.weight(.semibold))
                    Button(String(localized: "查看知识点")) {
                        onOpenKnowledge(first.id)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
                }
            }
        }
    }

    private var resultsCard: some View {
        RunwayCard {
            VStack(alignment: .leading, spacing: 12) {
                Text(String(localized: "今日复习结果"))
                    .font(.headline)
                ForEach(todayResults, id: \.attemptId) { row in
                    let item = knowledge.first(where: { $0.id == row.knowledgeId })
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.map { KnowledgeLexicon.keyword(for: $0, clipped: false) } ?? String(localized: "知识点"))
                            if let due = item?.dueAt {
                                Text("下次 \(due.formatted(date: .abbreviated, time: .shortened))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        Text(MasteryCopy.label(row.effectiveGrade))
                            .foregroundStyle(runway.agent)
                    }
                }
            }
        }
    }

    private var coachPose: CoachPose {
        if monitor.connection != .ready { return .waitYou }
        if forming.contains(where: { $0.status == "needs_attention" }) { return .waitYou }
        if !forming.isEmpty { return .working }
        if !dueItems.isEmpty { return .whistle }
        return .idle
    }

    private var agentRailStatus: String {
        if monitor.connection != .ready { return String(localized: "等服务恢复") }
        if let task = forming.first { return task.userStatus }
        if !dueItems.isEmpty { return tonightTitle }
        return String(localized: "待命")
    }

    private var tonightTitle: String {
        "今晚 \(tonightClock) 复习"
    }

    private var tonightClock: String {
        let minutes = settings?.dailyReminderMinutes ?? 21 * 60
        return String(format: "%d:%02d", minutes / 60, minutes % 60)
    }

    private func receiptLine(_ task: CaptureTask, _ receipt: ReceiptPayload?) -> String {
        let understood = receipt?.understoodAs ?? task.userStatus
        if task.intent == "learn_topic", let receipt {
            return "根据你确认的来源，整理了 \(receipt.theme) 的 \(receipt.knowledgeCount) 个知识点"
        }
        return "“\(understood)”"
    }

    private func saveDraft() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let url = Self.firstURL(in: text)
        let source = Source(inputType: url == nil ? "text" : "url", rawText: text, url: url)
        let task = CaptureTask()
        task.source = source
        CaptureProcessor.appendStatus(task.userStatus, to: task)
        modelContext.insert(source)
        modelContext.insert(task)
        try? modelContext.save()
        draft = ""
    }

    private func saveVoice(_ url: URL) {
        let source = Source(inputType: "voice", rawText: "", audioPath: url.path)
        let task = CaptureTask()
        task.source = source
        CaptureProcessor.appendStatus(task.userStatus, to: task)
        modelContext.insert(source)
        modelContext.insert(task)
        try? modelContext.save()
    }

    private func refreshPermissions() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: micAllowed = true
        default: micAllowed = false
        }
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            DispatchQueue.main.async {
                notifyAllowed = settings.authorizationStatus == .authorized
            }
        }
    }

    private struct ReceiptPayload: Codable {
        var understoodAs: String
        var theme: String
        var knowledgeCount: Int
        var attribution: String?
    }

    private static func decodeReceipt(_ json: String?) -> ReceiptPayload? {
        guard let json, let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(ReceiptPayload.self, from: data)
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
        let f = DateFormatter()
        f.calendar = Calendar.current
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: .now)
    }
}
