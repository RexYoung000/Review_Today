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
    @State private var localSaveError: String?

    private var settings: AppSettings? { settingsRows.first }
    private var developerMode: Bool { settings?.developerMode == true }

    private var dueItems: [Knowledge] {
        knowledge.filter { ReviewQueue.isDue($0, developerMode: developerMode) }
    }

    private var forming: [CaptureTask] {
        tasks.filter { !["completed", "cancelled"].contains($0.status) }
    }

    private var inboxCount: Int {
        tasks.filter { ["needs_attention", "retryable_failed"].contains($0.status) }.count
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
            VStack(alignment: .leading, spacing: Runway.gap) {
                statusBoard
                if let localSaveError {
                    Label(localSaveError, systemImage: "exclamationmark.triangle")
                        .font(.callout)
                        .foregroundStyle(Color.orange)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                AgentComposer(
                    draft: $draft,
                    turns: todayTurns,
                    forming: forming,
                    pose: coachPose,
                    recorder: recorder,
                    onSubmit: saveDraft,
                    onVoice: toggleVoice,
                    onOpenInbox: onOpenInbox,
                    onPreview: { id in
                        guard let item = knowledge.first(where: { $0.id == id }),
                              let question = KnowledgeLexicon.mainQuestion(for: item),
                              KnowledgeLexicon.previewUnavailableReason(for: item) == nil
                        else {
                            onOpenKnowledge(id)
                            return
                        }
                        coordinator.startPreview(knowledgeID: id, questionID: question.id)
                        openWindow(id: "review")
                    },
                    onOpenKnowledge: onOpenKnowledge,
                    receiptLine: { task in
                        receiptLine(task, Self.decodeReceipt(task.receiptJSON))
                    }
                )
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
            refreshPermissions()
        }
    }

    private var todayTurns: [CaptureTask] {
        (forming + todayReceipts).sorted { $0.createdAt < $1.createdAt }
    }

    private var statusBoard: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(dueItems.isEmpty ? String(localized: "今天无需复习") : tonightTitle)
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
                }
            }
            StatStrip(items: [
                StatCell(
                    id: "due",
                    value: dueItems.isEmpty ? "0" : "\(dueItems.count)",
                    title: String(localized: "今晚复习"),
                    action: dueItems.isEmpty ? nil : {
                        coordinator.startFormal(knowledgeIDs: dueItems.map(\.id))
                        openWindow(id: "review")
                    }
                ),
                StatCell(
                    id: "forming",
                    value: "\(forming.count)",
                    title: String(localized: "正在形成")
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

    private var coachPose: CoachPose {
        if monitor.connection != .ready { return .waitYou }
        if forming.contains(where: { ["needs_attention", "retryable_failed"].contains($0.status) }) { return .waitYou }
        if !forming.isEmpty { return .working }
        if !dueItems.isEmpty { return .whistle }
        return .idle
    }

    private var boardSubtitle: String {
        if monitor.connection != .ready { return String(localized: "等服务恢复") }
        if dueItems.isEmpty { return String(localized: "没有到期的知识") }
        return "预计约 \(dueItems.count) 分钟"
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

    private func toggleVoice() {
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            DispatchQueue.main.async { micAllowed = granted }
        }
        recorder.toggle()
        if !recorder.isRecording, let url = recorder.lastFileURL {
            saveVoice(url)
        }
    }

    private func saveDraft() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let url = Self.firstURL(in: text)
        let source = Source(inputType: url == nil ? "text" : "url", rawText: text, url: url)
        let task = CaptureTask()
        task.source = source
        CaptureProcessor.appendStatus(task.userStatus, to: task)
        do {
            try saveCapture(source: source, task: task)
            draft = ""
            localSaveError = nil
        } catch {
            modelContext.rollback()
            localSaveError = String(localized: "本机保存失败，请重试。")
        }
    }

    private func saveCapture(source: Source, task: CaptureTask) throws {
        modelContext.insert(source)
        modelContext.insert(task)
        try modelContext.save()
    }

    private func saveVoice(_ url: URL) {
        let source = Source(inputType: "voice", rawText: "", audioPath: url.path)
        let task = CaptureTask()
        task.source = source
        CaptureProcessor.appendStatus(task.userStatus, to: task)
        do {
            try saveCapture(source: source, task: task)
            localSaveError = nil
        } catch {
            modelContext.rollback()
            localSaveError = String(localized: "本机保存失败，请重试。")
        }
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
