import SwiftData
import SwiftUI

enum LearningDecisionInbox {
    static func includes(_ task: LearningTask, sessions: [AgentSession]) -> Bool {
        sessions.contains { $0.id == task.sessionID && $0.status == "active" } &&
        (task.status == "needs_attention" || ["choose_sources", "choose_question", "confirm_memory"].contains(task.requiredActionType ?? ""))
    }
}

struct InboxView: View {
    var onOpenSession: (UUID) -> Void = { _ in }
    @Environment(\.modelContext) private var modelContext
    @Query(
        filter: #Predicate<CaptureTask> { $0.status == "needs_attention" || $0.status == "retryable_failed" },
        sort: \CaptureTask.updatedAt
    )
    private var tasks: [CaptureTask]
    @Query private var learningTasks: [LearningTask]
    @Query private var sessions: [AgentSession]
    @State private var pasteText = ""
    @State private var urlText = ""

    private var decisions: [LearningTask] {
        learningTasks.filter { LearningDecisionInbox.includes($0, sessions: sessions) }.sorted { $0.updatedAt > $1.updatedAt }
    }

    var body: some View {
        Group {
            if tasks.isEmpty && decisions.isEmpty {
                VStack(spacing: 14) {
                    MascotMotion(phase: .idle, ambient: true).frame(width: 150, height: 125)
                    Text(String(localized: "没有需要处理的内容。"))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 16) {
                        ForEach(decisions, id: \.id) { task in
                            Button { onOpenSession(task.sessionID) } label: {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(sessions.first { $0.id == task.sessionID }?.title ?? "学习会话").font(.headline)
                                    Text(task.requiredActionPrompt ?? task.userSummary).foregroundStyle(.secondary)
                                    Label("回到会话处理", systemImage: "arrow.right").font(.caption)
                                }.frame(maxWidth: .infinity, alignment: .leading).padding(14).contentShape(Rectangle())
                            }.buttonStyle(InteractionButtonStyle(padding: 0))
                        }
                        ForEach(tasks, id: \.id) { task in
                            RunwayCard {
                                inboxRow(task)
                            }
                        }
                    }
                    .padding(28)
                }
            }
        }
        .background(PaperSurface())
        .navigationTitle(String(localized: "待处理"))
    }

    @ViewBuilder
    private func inboxRow(_ task: CaptureTask) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title(for: task.errorCode))
                .font(.headline)
            Text(task.userStatus)
                .font(.subheadline)
                .foregroundStyle(task.status == "retryable_failed" ? Color.orange : .secondary)
            Text(task.source?.rawText.prefix(160) ?? "")
                .foregroundStyle(.secondary)
            if let code = task.errorCode, ["RT.CAPTURE.CONFLICT", "RT.CAPTURE.VERIFY_INSUFFICIENT"].contains(code) {
                actionRow {
                    Button(String(localized: "采用限定版本")) { Task { await act(task, "adopt_limited") } }
                    Button(String(localized: "改为来源观点")) { Task { await act(task, "as_source_view") } }
                    Button(String(localized: "继续暂停")) { Task { await act(task, "keep_paused") } }
                    deleteButton(task)
                }
            } else if task.errorCode == "RT.CAPTURE.FETCH_FAILED" || task.errorCode == "RT.CAPTURE.SSRF" {
                Text(task.errorCode == "RT.CAPTURE.SSRF"
                     ? String(localized: "这个地址不能抓取。请贴正文，或换一个公开链接。")
                     : String(localized: "网址已识别，但读不到该网页。请贴正文，或稍后再试。"))
                TextField(String(localized: "粘贴正文"), text: $pasteText, axis: .vertical)
                actionRow {
                    Button(String(localized: "用这段正文整理")) { Task { await act(task, "paste", rawText: pasteText) } }
                    Button(String(localized: "重新抓取")) { Task { await act(task, "reprocess") } }
                    deleteButton(task)
                }
            } else if task.errorCode == "RT.CAPTURE.NEED_SOURCE" || task.errorCode == "RT.CAPTURE.TOO_BROAD" {
                Text(task.errorCode == "RT.CAPTURE.TOO_BROAD"
                     ? String(localized: "目标过宽。请收窄，或贴材料、给公开链接。")
                     : String(localized: "还没有可引用的学习材料。我不会用自己的记忆当课文。"))
                TextField(String(localized: "贴上一段"), text: $pasteText, axis: .vertical)
                TextField(String(localized: "公开链接"), text: $urlText)
                actionRow {
                    Button(String(localized: "贴上一段")) { Task { await act(task, "paste", rawText: pasteText) } }
                    Button(String(localized: "给公开链接")) { Task { await act(task, "attach_url", url: urlText) } }
                    Button(String(localized: "帮我找来源")) { Task { await act(task, "find_sources") } }
                    deleteButton(task)
                }
            } else if task.errorCode == "RT.CAPTURE.CONFIRM_SOURCES" {
                Text(String(localized: "请确认要采用的公开来源"))
                ForEach(Self.candidates(task.payloadJSON), id: \.url) { item in
                    Button("\(item.title)\n\(item.url)") {
                        Task { await act(task, "confirm_sources", urls: [item.url]) }
                    }
                }
                deleteButton(task)
            } else if task.errorCode == "RT.CAPTURE.TRANSCRIBE_FAILED" {
                TextField(String(localized: "确认转写"), text: $pasteText, axis: .vertical)
                actionRow {
                    Button(String(localized: "确认转写")) { Task { await act(task, "confirm_transcript", transcript: pasteText) } }
                    deleteButton(task)
                }
            } else {
                Text("输入和已有进度已保留，可以重试这次整理。")
                    .foregroundStyle(.secondary)
                actionRow {
                    Button(String(localized: "重新整理")) { Task { await act(task, "reprocess") } }
                    deleteButton(task)
                }
            }
        }
    }

    private func deleteButton(_ task: CaptureTask) -> some View {
        Button(String(localized: "删除"), role: .destructive) {
            Task { await act(task, "delete") }
        }
    }

    private func actionRow(@ViewBuilder content: () -> some View) -> some View {
        HStack(spacing: 8) {
            content()
        }
        .buttonStyle(.bordered)
        .controlSize(.regular)
    }

    private func title(for code: String?) -> String {
        switch code {
        case "RT.CAPTURE.CONFLICT", "RT.CAPTURE.VERIFY_INSUFFICIENT": String(localized: "冲突")
        case "RT.CAPTURE.FETCH_FAILED", "RT.CAPTURE.SSRF": String(localized: "无法读取网页")
        case "RT.CAPTURE.NEED_SOURCE", "RT.CAPTURE.TOO_BROAD": String(localized: "缺少来源")
        case "RT.CAPTURE.CONFIRM_SOURCES": String(localized: "确认来源")
        case "RT.CAPTURE.TRANSCRIBE_FAILED": String(localized: "转写异常")
        case "RT.CAPTURE.SERVICE_UNAVAILABLE", "RT.CAPTURE.MODEL_FAILED", "RT.CAPTURE.ACK_FAILED", "RT.CAPTURE.LOCAL_SAVE_FAILED", "RT.CAPTURE.STRUCTURE_INVALID", "RT.CAPTURE.REQUEST_FAILED": String(localized: "需要重试")
        default: String(localized: "校验失败")
        }
    }

    private func act(
        _ task: CaptureTask,
        _ action: String,
        rawText: String = "",
        url: String = "",
        urls: [String] = [],
        transcript: String = ""
    ) async {
        if action == "delete" {
            task.status = "cancelled"
            task.userStatus = String(localized: "已取消")
            task.updatedAt = .now
            try? modelContext.save()
            try? await AgentAPI.captureAction(taskId: task.id, action: "delete")
            return
        }
        do {
            let view = try await AgentAPI.captureAction(
                taskId: task.id,
                action: action,
                rawText: rawText,
                url: url,
                urls: urls,
                transcript: transcript
            )
            if action == "paste" { task.source?.rawText = rawText }
            if action == "attach_url" {
                task.source?.url = url
                task.source?.inputType = "url"
            }
            if action == "confirm_transcript" {
                task.source?.rawText = transcript
            }
            CaptureProcessor.apply(view, to: task)
            try modelContext.save()
        } catch {
            task.status = "retryable_failed"
            task.errorCode = errorCode(for: error)
            task.userStatus = String(localized: "需要重试")
            task.updatedAt = .now
            CaptureProcessor.appendStatus(task.userStatus, to: task)
            try? modelContext.save()
        }
    }

    private func errorCode(for error: Error) -> String {
        CaptureAPIError.code(for: error, fallback: "RT.CAPTURE.SERVICE_UNAVAILABLE")
    }

    private struct Candidate: Decodable { var url: String; var title: String; var snippet: String }

    private static func candidates(_ json: String?) -> [Candidate] {
        guard let json, let data = json.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([Candidate].self, from: data)) ?? []
    }
}

struct SettingsView: View {
    @Environment(\.modelContext) private var modelContext
    @Query private var rows: [AppSettings]

    var body: some View {
        NavigationStack {
            Form {
                if let settings = rows.first {
                    SettingsForm(settings: settings)
                } else {
                    ProgressView()
                        .onAppear { seed() }
                }
            }
            .formStyle(.grouped)
            .frame(minWidth: 420, minHeight: 240)
        }
    }

    private func seed() {
        guard rows.isEmpty else { return }
        modelContext.insert(AppSettings())
        try? modelContext.save()
    }
}

private struct SettingsForm: View {
    @Bindable var settings: AppSettings
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Section(String(localized: "外观")) {
            HStack {
                Text(String(localized: "浅色 / 深色"))
                Spacer()
                AnimatedThemeToggler()
            }
        }
        Section(String(localized: "一般")) {
            DatePicker(
                String(localized: "每日提醒时间"),
                selection: reminderBinding,
                displayedComponents: .hourAndMinute
            )
            Picker(String(localized: "复习语言"), selection: $settings.reviewLanguageOverride) {
                Text(String(localized: "系统默认")).tag("system")
                Text(String(localized: "用中文复习")).tag("zh")
                Text(String(localized: "用目标语言复习")).tag("target")
            }
        }
        Section(String(localized: "开发")) {
            Toggle(String(localized: "开发模式"), isOn: $settings.developerMode)
            if settings.developerMode {
                NavigationLink(String(localized: "Agent 运行记录")) {
                    AgentRunLogView()
                }
#if DEBUG
                Button("查看已确认动效（原生）") { openWindow(id: "mascot-motion-preview") }
                Button(String(localized: "打开吉祥物动画 POC")) {
                    openWindow(id: "mascot-animation-poc")
                }
#endif
            }
        }
    }

    private var reminderBinding: Binding<Date> {
        Binding(
            get: {
                Calendar.current.date(
                    from: DateComponents(
                        hour: settings.dailyReminderMinutes / 60,
                        minute: settings.dailyReminderMinutes % 60
                    )
                ) ?? .now
            },
            set: { date in
                let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
                settings.dailyReminderMinutes = (parts.hour ?? 21) * 60 + (parts.minute ?? 0)
            }
        )
    }
}

struct AgentRunLogView: View {
    @Query(sort: \CaptureTask.updatedAt, order: .reverse) private var tasks: [CaptureTask]

    var body: some View {
        List(tasks, id: \.id) { task in
            VStack(alignment: .leading, spacing: 6) {
                Text(task.userStatus)
                Text("\(task.status) · \(task.errorCode ?? "ok")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                let steps = CaptureProgress.steps(for: task)
                if steps.count > 1 {
                    ForEach(Array(steps.enumerated()), id: \.offset) { _, step in
                        Text(step)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                if let events = task.eventsJSON, !events.isEmpty {
                    Text(events)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .lineLimit(6)
                }
            }
        }
        .navigationTitle(String(localized: "Agent 运行记录"))
    }
}
