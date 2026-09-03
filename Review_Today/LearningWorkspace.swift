import SwiftData
import SwiftUI

struct LearningWorkspace: View {
    var monitor: AgentServiceMonitor
    var onOpenKnowledge: (UUID) -> Void

    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \AgentMessage.createdAt) private var messages: [AgentMessage]
    @Query(sort: \LearningTask.createdAt) private var tasks: [LearningTask]
    @Query(sort: \TaskEventRecord.seq) private var events: [TaskEventRecord]
    @Query(sort: \SourceReference.createdAt) private var sourceReferences: [SourceReference]
    @Query(sort: \KnowledgeReference.createdAt) private var knowledgeReferences: [KnowledgeReference]
    @Query(sort: \AgentRun.createdAt) private var runs: [AgentRun]
    @Query(sort: \SessionEventRecord.seq) private var runEvents: [SessionEventRecord]
    @State private var queueInput = false
    @State private var selectedSessionID: UUID?
    @State private var draft = ""
    @State private var showArchived = false
    @State private var localError: String?
    @State private var showsSessionPicker = false

    private enum Layout {
        static let expandedWidth: CGFloat = 900
        static let railWidth: CGFloat = 240
        static let readingWidth: CGFloat = 820

        static func gutter(for width: CGFloat) -> CGFloat { width < 650 ? 16 : 24 }
    }

    private var visibleSessions: [AgentSession] {
        sessions.filter { showArchived ? $0.status == "archived" : $0.status == "active" }
    }

    private var selectedSession: AgentSession? {
        sessions.first { $0.id == selectedSessionID }
    }

    private var sessionMessages: [AgentMessage] {
        guard let selectedSessionID else { return [] }
        return messages.filter { $0.sessionID == selectedSessionID }.sorted { $0.createdAt < $1.createdAt }
    }

    private var sessionTasks: [LearningTask] {
        guard let selectedSessionID else { return [] }
        return tasks.filter { $0.sessionID == selectedSessionID }.sorted { $0.createdAt < $1.createdAt }
    }

    var body: some View {
        // Bound the workspace to the actual viewport; nested split-view minimums
        // otherwise let long message content expand the entire navigation shell.
        GeometryReader { geometry in
            let expanded = geometry.size.width >= Layout.expandedWidth
            let workspaceWidth = max(0, geometry.size.width - (expanded ? Layout.railWidth + 1 : 0))
            HStack(spacing: 0) {
                if expanded {
                    sessionRail.frame(width: Layout.railWidth)
                    Rectangle().fill(runway.hairline).frame(width: 1)
                }
                workspace(width: workspaceWidth, compact: !expanded)
                    .frame(width: workspaceWidth)
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .onChange(of: expanded) { _, expanded in
                if expanded { showsSessionPicker = false }
            }
        }
        .background(PaperSurface())
        .navigationTitle(String(localized: "学习"))
        .onAppear(perform: selectInitialSession)
        .onChange(of: showArchived) { _, _ in selectInitialSession() }
        .onChange(of: sessions.map(\.id)) { _, _ in selectInitialSession() }
    }

    private var sessionRail: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("学习会话")
                    .font(.headline)
                    .foregroundStyle(runway.ink)
                Spacer()
                Button(action: { createSession() }) {
                    Image(systemName: "plus")
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)
                .help("新建 Session")
                .accessibilityLabel("新建学习 Session")
            }
            .padding(.horizontal, 14)
            .padding(.top, 16)

            Picker("Session 状态", selection: $showArchived) {
                Text("进行中").tag(false)
                Text("已归档").tag(true)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 12)

            ScrollView {
                LazyVStack(spacing: 5) {
                    ForEach(visibleSessions, id: \.id) { session in
                        Button {
                            selectedSessionID = session.id
                            showsSessionPicker = false
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(session.title)
                                    .font(.callout.weight(.medium))
                                    .foregroundStyle(runway.ink)
                                    .lineLimit(2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                HStack(spacing: 5) {
                                    Text(Self.modeLabel(session.modePreset))
                                    Text("·")
                                    Text(session.updatedAt, style: .relative)
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                            }
                            .padding(10)
                            .background(
                                selectedSessionID == session.id ? runway.field : Color.clear,
                                in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                            )
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    if visibleSessions.isEmpty {
                        Label(
                            showArchived ? "还没有归档的会话" : "从一个问题开始",
                            systemImage: showArchived ? "archivebox" : "bubble.left.and.bubble.right"
                        )
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.top, 24)
                    }
                }
                .padding(.horizontal, 8)
            }
        }
        .background(runway.canvas)
    }

    private func workspace(width: CGFloat, compact: Bool) -> some View {
        let gutter = Layout.gutter(for: width)
        let contentWidth = max(0, min(Layout.readingWidth, width - gutter * 2))
        return VStack(spacing: 0) {
            workspaceHeader(compact: compact)
            Divider()
            serviceBanner
            conversation(contentWidth: contentWidth)
            composer(contentWidth: contentWidth)
        }
        .background(runway.canvas)
    }

    private func workspaceHeader(compact: Bool) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(selectedSession?.title ?? "新的学习 Session")
                        .font(.title2.bold())
                        .foregroundStyle(runway.ink)
                        .lineLimit(2)
                        .help(selectedSession?.title ?? "新的学习 Session")
                    Text("回答、学习路径和工作过程都保存在这里")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if let session = selectedSession { sessionMenu(session) }
            }

            HStack(spacing: 12) {
                if compact {
                    Button { showsSessionPicker.toggle() } label: {
                        Label("学习会话", systemImage: "list.bullet")
                    }
                    .popover(isPresented: $showsSessionPicker, arrowEdge: .bottom) {
                        sessionRail.frame(width: 300, height: 460)
                    }
                    .accessibilityLabel("打开学习会话列表")
                }
                Spacer(minLength: 0)
                if let session = selectedSession {
                    Text("模式").font(.caption).foregroundStyle(.secondary)
                    Picker("模式", selection: Binding(
                        get: { session.modePreset },
                        set: { value in
                            session.modePreset = value
                            session.updatedAt = .now
                            if let run = runs.last(where: { $0.sessionID == session.id }) {
                                ConversationProcessor.queueControl(run, action: "set_mode", mode: value, context: modelContext)
                            }
                            try? modelContext.save()
                        }
                    )) {
                        Text("Auto").tag("auto")
                        Text("知识整理").tag("memory_organization")
                        Text("资料学习").tag("source_learning")
                        Text("主题探索").tag("topic_exploration")
                        Text("问题攻克").tag("problem_solving")
                    }
                    .labelsHidden()
                    .frame(width: 120)
                    .help("作用于当前目标的下一步，保留已有资料与进度；Auto 自动安排同目标内的能力")
                }
            }
            .controlSize(.small)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    private func sessionMenu(_ session: AgentSession) -> some View {
        Menu {
            Button("新建学习 Session") { createSession() }
            Button("带上下文新建 Session") { createSession(handoffFrom: session) }
            if session.status == "active" {
                Button("归档 Session") { archive(session) }
            } else {
                Button("恢复 Session") { restore(session) }
            }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
        .menuStyle(.borderlessButton)
        .frame(width: 28, height: 26)
        .accessibilityLabel("Session 操作")
    }

    @ViewBuilder
    private var serviceBanner: some View {
        if monitor.connection != .ready || !monitor.keyConfigured {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: monitor.connection == .unavailable ? "exclamationmark.triangle" : "clock.arrow.circlepath")
                    .foregroundStyle(monitor.connection == .unavailable ? Color.orange : runway.agent)
                    .padding(.top, 1)
                VStack(alignment: .leading, spacing: 2) {
                    Text(monitor.launchStatus)
                        .font(.callout.weight(.medium))
                        .fixedSize(horizontal: false, vertical: true)
                    if !monitor.launchDetail.isEmpty {
                        Text(monitor.launchDetail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .help(monitor.launchDetail)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if monitor.connection == .unavailable {
                    Button("重试") { monitor.retryLaunch() }
                        .buttonStyle(.borderless)
                        .fixedSize()
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(runway.field)
        }
    }

    private func conversation(contentWidth: CGFloat) -> some View {
        ScrollViewReader { proxy in
          ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                if sessionMessages.isEmpty {
                    emptyConversation
                } else {
                    ForEach(sessionMessages, id: \.id) { message in
                        messageBubble(message, contentWidth: contentWidth)
                            .id(message.id)
                        if message.role == "user" {
                            if let runID = message.runID,
                               let run = runs.first(where: { $0.id == runID }),
                               sessionMessages.last(where: { $0.role == "user" && $0.runID == runID })?.id == message.id {
                                runFeedback(run)
                            } else if message.runID == nil && message.taskID == nil {
                                Text(monitor.connection == .ready ? "已保存在本机，准备发送" : "已保存在本机，等待学习服务启动")
                                    .font(.caption).foregroundStyle(.secondary)
                                if let error = message.lastDeliveryError {
                                    Text("提交尚未成功，输入保留：\(error)").font(.caption).foregroundStyle(.orange)
                                }
                            }
                        }
                        if message.role == "user",
                           let task = sessionTasks.first(where: { $0.inputMessageID == message.id }) {
                            taskCard(task)
                        }
                    }
                }
                pendingOperation
            }
            .frame(width: contentWidth)
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity)
          }
          .onChange(of: sessionMessages.map(\.id)) { _, _ in
              if let last = sessionMessages.last {
                  proxy.scrollTo(last.id, anchor: last.role == "user" ? .bottom : .top)
              }
          }
        }
    }

    private var emptyConversation: some View {
        RunwayCard {
            HStack(alignment: .top, spacing: 14) {
                CoachMark(pose: .idle, size: 42)
                VStack(alignment: .leading, spacing: 8) {
                    Text("把你真正想解决的学习问题发过来")
                        .font(.headline)
                    Text("可以是一个主题、一份资料、一道面试题，或完整 JD。问题攻克会先给基础答案，再带你校准、独立作答，最后由你决定是否形成记忆。")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.top, 32)
    }

    private func messageBubble(_ message: AgentMessage, contentWidth: CGFloat) -> some View {
        let isUser = message.role == "user"
        let bubbleWidth = max(0, contentWidth - 40)
        return HStack(alignment: .top, spacing: 10) {
            if !isUser { CoachMark(pose: .idle, size: 30) }
            Text(.init(message.content))
                .font(.body)
                .foregroundStyle(runway.ink)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(
                    message.role == "user" ? runway.field : runway.card,
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .strokeBorder(message.role == "user" ? Color.clear : runway.hairline)
                )
                .frame(maxWidth: bubbleWidth, alignment: isUser ? .trailing : .leading)
        }
        .frame(width: contentWidth, alignment: isUser ? .trailing : .leading)
    }

    private func taskCard(_ task: LearningTask) -> some View {
        let taskEvents = events.filter { $0.taskID == task.id }.sorted { $0.seq < $1.seq }
        let options = Self.options(task.requiredActionOptionsJSON)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                Circle()
                    .fill(Self.tone(task.status) == .problem ? Color.orange : runway.agent)
                    .frame(width: 6, height: 6)
                    .padding(.top, 5)
                Text(task.userSummary)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 8) {
                MetaTag(title: Self.modeLabel(task.mode))
                if task.conversationManaged {
                    Text(task.understanding == "verified" ? "已验证理解" : task.understanding == "self_reported" ? "自述理解 · 未验证" : "尚未验证理解")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Spacer()
                if task.status == "retryable_failed" || task.status == "needs_attention" {
                    Button("重试") { taskControl(task, action: "retry") }
                        .buttonStyle(.borderless)
                    Button("取消目标") { taskControl(task, action: "cancel_task") }
                        .buttonStyle(.borderless)
                }
            }

            if let prompt = task.requiredActionPrompt, task.pendingActionID == nil {
                Text(prompt)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .fixedSize(horizontal: false, vertical: true)
                if !options.isEmpty && !task.conversationManaged {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(options, id: \.self) { option in
                            Button {
                                respond(option, to: task)
                            } label: {
                                HStack(spacing: 8) {
                                    Text(Self.optionLabel(option))
                                        .font(.callout.weight(.medium))
                                        .foregroundStyle(runway.ink)
                                        .fixedSize(horizontal: false, vertical: true)
                                        .multilineTextAlignment(.leading)
                                    Spacer(minLength: 4)
                                    Image(systemName: "arrow.right")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 9)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(runway.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }

            DisclosureGroup {
                VStack(alignment: .leading, spacing: 8) {
                    if taskEvents.isEmpty {
                        Text("等待第一个运行事件")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(taskEvents, id: \.eventID) { event in
                        HStack(alignment: .top, spacing: 8) {
                            Circle()
                                .fill(event.errorCode == nil ? runway.agent : Color.orange)
                                .frame(width: 6, height: 6)
                                .padding(.top, 5)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(event.userSummary)
                                    .font(.caption.weight(.medium))
                                    .fixedSize(horizontal: false, vertical: true)
                                Text(event.node)
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                                ViewThatFits(in: .horizontal) {
                                    eventTiming(event)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(event.occurredAt, format: .dateTime.hour().minute().second())
                                        if let duration = event.durationMS { Text("\(duration) ms") }
                                        if event.attempt > 1 { Text("第 \(event.attempt) 次") }
                                    }
                                }
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                                if !event.detailSummary.isEmpty {
                                    Text(event.detailSummary)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if let error = event.errorCode {
                                    Text(error)
                                        .font(.caption2.monospaced())
                                        .foregroundStyle(.orange)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if let recovery = event.recoveryAction {
                                    Text("恢复动作：\(recovery)")
                                        .font(.caption2.monospaced())
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 6)
            } label: {
                Text("运行详情")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(13)
        .background(runway.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(runway.hairline))
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("学习任务：\(task.userSummary)")
    }

    private func eventTiming(_ event: TaskEventRecord) -> some View {
        HStack(spacing: 6) {
            Text(event.occurredAt, format: .dateTime.hour().minute().second())
            if let duration = event.durationMS { Text("\(duration) ms") }
            if event.attempt > 1 { Text("第 \(event.attempt) 次") }
        }
    }

    private func composer(contentWidth: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let syncError = selectedSession?.syncError {
                Text("正在恢复进度同步：\(syncError)").font(.caption).foregroundStyle(.orange)
            }
            if let localError {
                Label(localError, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            HStack(alignment: .bottom, spacing: 10) {
                ZStack(alignment: .topLeading) {
                    if draft.isEmpty {
                        Text(activeActionPlaceholder)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 8)
                            .lineLimit(2)
                            .allowsHitTesting(false)
                    }
                    TextEditor(text: $draft)
                        .scrollContentBackground(.hidden)
                        .frame(height: 72)
                        .padding(.horizontal, 1)
                        .accessibilityLabel("学习输入")
                }
                Button(action: submitDraft) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(runway.onAction)
                        .frame(width: 34, height: 34)
                        .background(runway.action, in: Circle())
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.return, modifiers: [.command])
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("发送")
            }
            .padding(10)
            .background(runway.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(runway.hairline))
            HStack(spacing: 10) {
                Text("⌘ Return 发送 · 输入先保存在本机")
                Spacer()
                Toggle("排队发送", isOn: $queueInput).toggleStyle(.checkbox)
                if let run = runs.last(where: { $0.sessionID == selectedSessionID }),
                   ["accepted", "running", "queued"].contains(run.status) {
                    Button("停止回复") { ConversationProcessor.queueControl(run, action: "stop", context: modelContext) }
                        .buttonStyle(.borderless)
                }
            }
            .font(.caption2).foregroundStyle(.secondary)
        }
        .frame(width: contentWidth)
        .padding(.top, 8)
        .padding(.bottom, 18)
        .frame(maxWidth: .infinity)
    }

    private var activeActionPlaceholder: String {
        guard let task = sessionTasks.last(where: { $0.status == "awaiting_user" }),
              let prompt = task.requiredActionPrompt else {
            return "输入问题、资料、链接或 JD……"
        }
        return prompt
    }

    private func submitDraft() {
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }
        sendMessage(content)
    }

    private func sendMessage(_ content: String, operation: [String: Any]? = nil) {
        let session = selectedSession ?? createSession()
        guard session.status == "active" else {
            localError = "请先恢复归档的会话，再继续输入。"
            return
        }
        let message = AgentMessage(sessionID: session.id, role: "user", content: content,
                                   contentType: TodayView.firstURL(in: content) == nil ? "text" : "url")
        message.clientMessageID = message.id
        message.deliveryMode = queueInput ? "queue" : "steer"
        message.operationJSON = operation.map(ConversationProcessor.json)
        modelContext.insert(message)
        session.updatedAt = .now
        if session.title == "新学习 Session" { session.title = String(content.prefix(28)) }
        do {
            try modelContext.save()
            draft = ""
            queueInput = false
            localError = nil
        } catch {
            modelContext.rollback()
            localError = "本机保存失败，输入仍保留，请重试。"
        }
    }

    private func respond(_ content: String, to task: LearningTask) {
        // All free text is semantically interpreted, never inferred from a button label.
        sendMessage(content)
    }

    private func taskControl(_ task: LearningTask, action: String) {
        if let run = runs.last(where: { $0.sessionID == task.sessionID && $0.taskID == task.id }) {
            ConversationProcessor.queueControl(run, action: action, context: modelContext)
        } else {
            HarnessProcessor.queueAction(task, type: action == "cancel_task" ? "cancel" : action, content: "", context: modelContext)
        }
    }

    private func runFeedback(_ run: AgentRun) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Label(run.userSummary, systemImage: run.errorCode == nil ? "circle.dotted" : "exclamationmark.circle")
                    .font(.caption).foregroundStyle(run.errorCode == nil ? runway.agent : .orange)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                if ["interrupted", "retryable_failed", "terminal_failed"].contains(run.status) {
                    Button(run.status == "interrupted" ? "恢复" : "重试") {
                        ConversationProcessor.queueControl(run, action: run.status == "interrupted" ? "resume" : "retry", context: modelContext)
                    }.buttonStyle(.borderless)
                }
                if run.taskID != nil && run.status != "stopping" {
                    Button("取消目标") { ConversationProcessor.queueControl(run, action: "cancel_task", context: modelContext) }
                        .buttonStyle(.borderless)
                }
            }
            DisclosureGroup("运行详情") {
                ForEach(runEvents.filter { $0.runID == run.id }, id: \.id) { event in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(event.summary).font(.caption.weight(.medium))
                        if !event.detail.isEmpty { Text(event.detail).font(.caption) }
                        Text([event.stage, event.model, "第 \(max(1, event.attempt)) 次",
                              event.durationMS.map { "\($0) ms" } ?? ""].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption2.monospaced()).foregroundStyle(.secondary)
                        if let error = event.errorCode { Text(error).font(.caption2.monospaced()).foregroundStyle(.orange) }
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 3)
                }
            }
            .font(.caption)
        }
        .padding(.horizontal, 6)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var pendingOperation: some View {
        if let pending = ConversationProcessor.object(selectedSession?.pendingOperationJSON),
           let kind = pending["kind"] as? String,
           let target = pending["target_id"] as? String,
           let version = pending["version"] as? Int {
            VStack(alignment: .leading, spacing: 8) {
                if kind == "save" {
                    Text("整理版本 \(version) · 尚未入库").font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Button("加入知识库与复习") { sendBound("save", title: "加入知识库与复习", target: target, version: version) }
                        Button("暂不保存") { sendBound("reject_save", title: "暂不保存", target: target, version: version) }
                    }
                } else if kind == "new_session" {
                    HStack {
                        Button("新建学习会话") { sendBound(kind, title: "新建学习会话", target: target, version: version) }
                        Button("继续放在这里") { sendBound("continue_session", title: "继续放在这里", target: target, version: version) }
                    }
                } else if kind == "select_sources" {
                    Button("确认资料包，开始学习") {
                        sendBound(kind, title: "确认资料包", target: target, version: version, selection: pending["options"] as? [String] ?? [])
                    }
                } else if kind == "select_question" {
                    ForEach(pending["options"] as? [String] ?? [], id: \.self) { option in
                        Button(option) { sendBound(kind, title: option, target: target, version: version, selection: [option]) }
                    }
                }
            }
            .controlSize(.small)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func sendBound(_ kind: String, title: String, target: String, version: Int, selection: [String] = []) {
        sendMessage(title, operation: ["kind": kind, "target_id": target, "version": version, "selection": selection])
    }

    @discardableResult
    private func createSession(handoffFrom source: AgentSession? = nil) -> AgentSession {
        let session = AgentSession(
            title: source == nil ? "新学习 Session" : "从「\(source!.title)」继续",
            sourceSessionID: source?.id
        )
        if let source {
            session.summaryText = handoffSummary(from: source)
        }
        modelContext.insert(session)
        try? modelContext.save()
        showArchived = false
        selectedSessionID = session.id
        showsSessionPicker = false
        return session
    }

    private func handoffSummary(from source: AgentSession) -> String {
        let latestInput = messages
            .filter { $0.sessionID == source.id && $0.role == "user" }
            .sorted { $0.createdAt < $1.createdAt }
            .last?.content
        let unresolved = tasks
            .filter { $0.sessionID == source.id && !["completed", "cancelled", "terminal_failed"].contains($0.status) }
            .map(\.userSummary)
            .prefix(3)
        let sources = sourceReferences
            .filter { $0.sessionID == source.id }
            .map(\.url)
            .prefix(4)
        let knowledgeIDs = knowledgeReferences
            .filter { $0.sessionID == source.id }
            .map { $0.knowledgeID.uuidString.lowercased() }
            .prefix(5)
        return [
            "来源 Session ID：\(source.id.uuidString.lowercased())",
            "来源目标：\(source.title)",
            "确认决定：模式为 \(Self.modeLabel(source.modePreset))",
            "最近输入：\(latestInput ?? "暂无")",
            "资料引用：\(sources.isEmpty ? "暂无" : sources.joined(separator: "，"))",
            "知识引用：\(knowledgeIDs.isEmpty ? "暂无" : knowledgeIDs.joined(separator: "，"))",
            "未解决问题：\(unresolved.isEmpty ? "暂无" : unresolved.joined(separator: "；"))",
        ].joined(separator: "\n")
    }

    private func archive(_ session: AgentSession) {
        if let run = runs.last(where: { $0.sessionID == session.id && ["running", "accepted", "queued"].contains($0.status) }) {
            ConversationProcessor.queueControl(run, action: "stop", context: modelContext)
        }
        session.status = "archived"
        session.archivedAt = .now
        session.updatedAt = .now
        try? modelContext.save()
        selectInitialSession()
    }

    private func restore(_ session: AgentSession) {
        session.status = "active"
        session.archivedAt = nil
        session.updatedAt = .now
        showArchived = false
        selectedSessionID = session.id
        try? modelContext.save()
    }

    private func selectInitialSession() {
        if let selectedSessionID, visibleSessions.contains(where: { $0.id == selectedSessionID }) { return }
        self.selectedSessionID = visibleSessions.first?.id
    }

    private func updateSessionSummary(_ session: AgentSession) {
        let rows = ((try? modelContext.fetch(FetchDescriptor<AgentMessage>())) ?? [])
            .filter { $0.sessionID == session.id }
            .sorted { $0.createdAt < $1.createdAt }
        guard rows.count > 20 else { return }
        let older = rows.dropLast(10).suffix(40)
        let summary = older.map { row in
            let role = row.role == "user" ? "用户" : "教练"
            return "\(role)：\(row.content.prefix(240))"
        }.joined(separator: "\n")
        session.summaryText = String(summary.suffix(10_000))
        session.updatedAt = .now
        let existing = ((try? modelContext.fetch(FetchDescriptor<SessionSummaryRecord>())) ?? [])
            .first { $0.sessionID == session.id }
        let record = existing ?? SessionSummaryRecord(sessionID: session.id)
        if existing == nil { modelContext.insert(record) }
        record.version += existing == nil ? 0 : 1
        record.goal = session.title
        record.confirmedDecisionsJSON = "[\"模式：\(Self.modeLabel(session.modePreset))\"]"
        record.updatedAt = .now
        try? modelContext.save()
    }

    private static func options(_ raw: String?) -> [String] {
        guard let raw, let data = raw.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([String].self, from: data)) ?? []
    }

    private static func optionLabel(_ option: String) -> String {
        guard let url = URL(string: option), let host = url.host else { return option }
        let path = url.lastPathComponent.removingPercentEncoding ?? url.lastPathComponent
        return path.isEmpty ? host : "\(host) · \(String(path.prefix(54)))"
    }

    static func modeLabel(_ mode: String) -> String {
        switch mode {
        case "memory_organization": return "知识整理"
        case "source_learning": return "资料学习"
        case "topic_exploration": return "主题探索"
        case "problem_solving": return "问题攻克"
        default: return "Auto"
        }
    }

    private static func tone(_ status: String) -> StatusChip.Tone {
        switch status {
        case "completed": return .ready
        case "retryable_failed", "needs_attention", "terminal_failed": return .problem
        case "awaiting_user": return .wait
        default: return .quiet
        }
    }
}
