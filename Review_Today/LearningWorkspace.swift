import SwiftData
import SwiftUI

struct LearningWorkspace: View {
    var monitor: AgentServiceMonitor
    @Binding var selectedSessionID: UUID?
    var onOpenKnowledge: (UUID) -> Void

    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \LearningTask.createdAt) private var tasks: [LearningTask]
    @Query(sort: \TaskEventRecord.seq) private var events: [TaskEventRecord]
    @Query(sort: \SourceReference.createdAt) private var sourceReferences: [SourceReference]
    @Query(sort: \KnowledgeReference.createdAt) private var knowledgeReferences: [KnowledgeReference]
    @Query(sort: \AgentRun.createdAt) private var runs: [AgentRun]
    @State private var queueInput = false
    @State private var draft = ""
    @State private var localError: String?
    @State private var editingSessionID: UUID?
    @State private var inputHeight: CGFloat = 64
    @State private var inputFocused = false
    @State private var focusRequest = 0
    @State private var draftSessionID: UUID?
    @State private var draftSave: Task<Void, Never>?
    @State private var followsLatest = true
    @State private var userScrolling = false
    @State private var sentMessageID: UUID?

    private enum Layout {
        static let readingWidth: CGFloat = 820

        static func gutter(for width: CGFloat) -> CGFloat { width < 650 ? 16 : 24 }
    }

    private var selectedSession: AgentSession? {
        sessions.first { $0.id == selectedSessionID }
    }

    private func messages(for id: UUID) -> [AgentMessage] {
        (try? modelContext.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == id }, sortBy: [SortDescriptor(\.createdAt)]))) ?? []
    }

    private var sessionTasks: [LearningTask] {
        guard let selectedSessionID else { return [] }
        return tasks.filter { $0.sessionID == selectedSessionID }.sorted { $0.createdAt < $1.createdAt }
    }

    var body: some View {
        GeometryReader { geometry in
            workspace(width: geometry.size.width)
                .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .background(PaperSurface())
        .navigationTitle(String(localized: "学习"))
        .onAppear(perform: selectInitialSession)
        .onChange(of: sessions.map(\.id)) { _, _ in selectInitialSession() }
        .onChange(of: selectedSessionID) { _, id in
            saveDraft()
            draftSessionID = id
            draft = sessions.first(where: { $0.id == id })?.composerDraft ?? ""
            queueInput = false
            localError = nil
            followsLatest = true
        }
        .onChange(of: draft) { _, _ in
            draftSave?.cancel()
            draftSave = Task {
                try? await Task.sleep(for: .milliseconds(250))
                guard !Task.isCancelled else { return }
                saveDraft()
            }
        }
        .onDisappear { saveDraft() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in saveDraft() }
        .sheet(isPresented: Binding(
            get: { editingSessionID != nil },
            set: { if !$0 { editingSessionID = nil } }
        )) {
            if let id = editingSessionID, let session = sessions.first(where: { $0.id == id }) {
                SessionTagEditor(session: session)
            }
        }
    }

    private func workspace(width: CGFloat) -> some View {
        let gutter = Layout.gutter(for: width)
        let contentWidth = max(0, min(Layout.readingWidth, width - gutter * 2))
        return VStack(spacing: 0) {
            workspaceHeader
            Divider()
            serviceBanner
            conversation(contentWidth: contentWidth)
            composer(contentWidth: contentWidth)
        }
        .background(runway.canvas)
    }

    private var workspaceHeader: some View {
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
                if let session = selectedSession {
                    Button {
                        if session.status == "active" { archive(session) }
                        else { restore(session) }
                    } label: {
                        Label(session.status == "active" ? "归档" : "恢复", systemImage: session.status == "active" ? "archivebox" : "arrow.uturn.backward")
                    }
                    .buttonStyle(.borderless)
                    sessionMenu(session)
                }
            }

            HStack(spacing: 12) {
                if let session = selectedSession {
                    ForEach(Array(session.displayTopicTags.prefix(3)), id: \.self) { tag in
                        MetaTag(title: tag)
                    }
                    if session.displayTopicTags.count > 3 {
                        Text("+\(session.displayTopicTags.count - 3)").font(.caption2).foregroundStyle(.secondary)
                    }
                    Button { editingSessionID = session.id } label: { Image(systemName: "tag") }
                        .buttonStyle(.plain).help("编辑主题标签")
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
            Button("编辑主题标签") { editingSessionID = session.id }
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
        } else if !monitor.capabilityNotice.isEmpty || !monitor.streamNotice.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                if !monitor.capabilityNotice.isEmpty {
                    Text(monitor.capabilityNotice)
                }
                if !monitor.streamNotice.isEmpty {
                    Text(monitor.streamNotice)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20).padding(.vertical, 6)
        }
    }

    private func conversation(contentWidth: CGFloat) -> some View {
        SessionTranscriptData(sessionID: selectedSessionID) { messages, events in
            transcript(messages, runEvents: events, contentWidth: contentWidth)
        }
    }

    private func transcript(_ sessionMessages: [AgentMessage], runEvents: [SessionEventRecord], contentWidth: CGFloat) -> some View {
        return ScrollViewReader { proxy in
          ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                if sessionMessages.isEmpty {
                    emptyConversation
                } else {
                    ForEach(sessionMessages, id: \.id) { message in
                        messageBubble(message, contentWidth: contentWidth)
                            .id(message.id)
                        if message.role == "user" {
                            let task = sessionTasks.first(where: { $0.inputMessageID == message.id })
                            if task == nil, let runID = message.runID,
                               let run = runs.first(where: { $0.id == runID }),
                               sessionMessages.last(where: { $0.role == "user" && $0.runID == runID })?.id == message.id {
                                runFeedback(run, sessionMessages: sessionMessages, runEvents: runEvents)
                            } else if message.runID == nil && message.taskID == nil {
                                Text(monitor.connection == .ready ? "已保存在本机，准备发送" : "已保存在本机，等待学习服务启动")
                                    .font(.caption).foregroundStyle(.secondary)
                                if let error = message.lastDeliveryError {
                                    Text("提交尚未成功，输入保留：\(error)").font(.caption).foregroundStyle(.orange)
                                }
                            }
                        }
                        if message.role == "user", let task = sessionTasks.first(where: { $0.inputMessageID == message.id }) {
                            taskCard(task, run: message.runID.flatMap { id in runs.first(where: { $0.id == id }) }, runEvents: runEvents)
                        }
                    }
                }
                pendingOperation
                Color.clear.frame(height: 1).id("latest")
            }
            .frame(width: contentWidth)
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity)
          }
          .onScrollGeometryChange(for: Bool.self) { geometry in
              geometry.contentSize.height - geometry.visibleRect.maxY < 48
          } action: { _, nearBottom in
              // Content growth alone is not the user scrolling away from bottom.
              if userScrolling || nearBottom { followsLatest = nearBottom }
          }
          .onScrollPhaseChange { _, phase in userScrolling = phase == .interacting || phase == .decelerating }
          .onChange(of: sessionMessages.last?.content) { _, _ in
              if followsLatest { proxy.scrollTo("latest", anchor: .bottom) }
          }
          .onChange(of: selectedSessionID) { _, _ in proxy.scrollTo("latest", anchor: .bottom) }
          .onChange(of: sentMessageID) { _, id in
              if let id { proxy.scrollTo(id, anchor: .bottom); followsLatest = true }
          }
          .overlay(alignment: .bottomTrailing) {
              if !followsLatest && !sessionMessages.isEmpty {
                  Button { proxy.scrollTo("latest", anchor: .bottom); followsLatest = true } label: {
                      Label("回到最新", systemImage: "arrow.down")
                  }
                  .buttonStyle(.bordered).controlSize(.small)
                  .padding(12)
              }
          }
        }
    }

    private var emptyConversation: some View {
        RunwayCard {
            HStack(alignment: .top, spacing: 14) {
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
            VStack(alignment: .leading, spacing: 5) {
              if isUser {
                  Text(.init(message.content))
                      .font(.body).foregroundStyle(runway.ink).textSelection(.enabled)
                      .fixedSize(horizontal: false, vertical: true)
                      .padding(.horizontal, 14).padding(.vertical, 10)
                      .background(runway.field, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                      .frame(maxWidth: bubbleWidth, alignment: .trailing)
              } else {
                  Text(.init(message.content))
                      .font(.body).foregroundStyle(runway.ink).textSelection(.enabled)
                      .fixedSize(horizontal: false, vertical: true)
                      .frame(maxWidth: bubbleWidth, alignment: .leading)
              }
              if ["interrupted", "failed"].contains(message.responseState) {
                  Text("未完成 · 内容保留，不作为正式结果").font(.caption2).foregroundStyle(.secondary)
              } else if message.responseState == "streaming" {
                  Text("正在输出 · 尚未完成校验").font(.caption2).foregroundStyle(.secondary)
              }
            }
        }
        .frame(width: contentWidth, alignment: isUser ? .trailing : .leading)
        .onAppear {
            if message.firstDisplayedAt == nil {
                message.firstDisplayedAt = .now
                if isUser { message.localEchoMS = Int(Date.now.timeIntervalSince(message.createdAt) * 1000) }
                try? modelContext.save()
            }
        }
    }

    private func taskCard(_ task: LearningTask, run: AgentRun?, runEvents: [SessionEventRecord]) -> some View {
        let taskEvents = events.filter { $0.taskID == task.id }.sorted { $0.seq < $1.seq }
        let options = Self.options(task.requiredActionOptionsJSON)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                if let run, run.status != "completed" {
                    RunPhaseLine(run: run)
                } else {
                    Circle()
                        .fill(Self.tone(task.status) == .problem ? Color.orange : runway.agent)
                        .frame(width: 6, height: 6)
                        .padding(.top, 5)
                    Text(task.userSummary)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
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

            RunDetails(title: run?.status == "completed" && (run?.elapsedMS ?? 0) > 0
                       ? String(format: "已完成 · %.1f 秒 · 运行详情", Double(run!.elapsedMS) / 1000)
                       : "运行详情") {
                VStack(alignment: .leading, spacing: 8) {
                    let sessionEvents = run.map { item in runEvents.filter { $0.runID == item.id } } ?? []
                    if taskEvents.isEmpty && sessionEvents.isEmpty {
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
                    if !sessionEvents.isEmpty {
                        ForEach(sessionEvents, id: \.id) { event in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(event.summary).font(.caption.weight(.medium))
                                if !event.detail.isEmpty { Text(event.detail).font(.caption).foregroundStyle(.secondary) }
                                Text([event.stage, event.model, event.durationMS.map { "\($0) ms" } ?? ""].filter { !$0.isEmpty }.joined(separator: " · "))
                                    .font(.caption2.monospaced()).foregroundStyle(.secondary)
                            }.padding(.vertical, 2)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 6)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(runway.field.opacity(0.55), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
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

    @ViewBuilder
    private func composer(contentWidth: CGFloat) -> some View {
        if selectedSession?.status == "archived" {
            HStack {
                Label("已归档 · 会话只读", systemImage: "archivebox")
                    .font(.callout).foregroundStyle(.secondary)
                Spacer()
                if let session = selectedSession { Button("撤销") { restore(session) } }
            }
            .frame(width: contentWidth).padding(.vertical, 16).frame(maxWidth: .infinity)
        } else {
        VStack(alignment: .leading, spacing: 8) {
            if let syncError = selectedSession?.syncError {
                Text("正在恢复进度同步：\(syncError)").font(.caption).foregroundStyle(.orange)
            }
            if let localError {
                Label(localError, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            VStack(spacing: 4) {
                LearningTextInput(text: $draft, height: $inputHeight, focused: $inputFocused,
                                  focusRequest: focusRequest, sessionID: selectedSessionID,
                                  placeholder: activeActionPlaceholder, ink: NSColor(runway.ink), onSubmit: submitDraft)
                    .frame(height: inputHeight)
                HStack {
                  Text("Return 发送 · Shift Return 换行")
                      .font(.caption2).foregroundStyle(.secondary)
                  Spacer(minLength: 8)
                Button(action: submitDraft) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(runway.onAction)
                        .frame(width: 34, height: 34)
                        .background(runway.action, in: Circle())
                }
                .buttonStyle(.plain)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help("发送（Return 或 ⌘ Return）")
                .accessibilityLabel("发送")
                }
                .padding(.horizontal, 8)
            }
            .padding(10)
            .background(runway.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(inputFocused ? runway.agent.opacity(0.65) : runway.hairline, lineWidth: inputFocused ? 1.5 : 1))
            HStack(spacing: 10) {
                Text("草稿仅保存在当前会话 · 输入先保存在本机")
                Spacer()
                Toggle("排队发送", isOn: $queueInput).toggleStyle(.checkbox)
                if let run = runs.last(where: { $0.sessionID == selectedSessionID }),
                   ["accepted", "running", "queued", "adjusting"].contains(run.status) {
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
        let started = Date.now
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
        if !queueInput, let active = runs.last(where: { $0.sessionID == session.id && ["running", "accepted", "adjusting"].contains($0.status) }) {
            active.status = "adjusting"
            active.userSummary = "已收到补充，正在调整"
            for response in messages(for: session.id) where response.runID == active.id && response.responseState == "streaming" {
                response.responseState = "interrupted"
            }
        }
        session.updatedAt = .now
        if session.title == "新学习 Session" { session.title = String(content.prefix(28)) }
        do {
            if operation == nil { session.composerDraft = "" }
            try modelContext.save()
            if operation == nil { draft = "" }
            message.localSavedMS = Int(Date.now.timeIntervalSince(started) * 1000)
            queueInput = false
            localError = nil
            sentMessageID = message.id
            focusRequest += 1
            ConversationSync.wake()
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

    private func runFeedback(_ run: AgentRun, sessionMessages: [AgentMessage], runEvents: [SessionEventRecord]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
          if run.status != "completed" {
            HStack(alignment: .top) {
                RunPhaseLine(run: run)
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
          }
            RunDetails(title: run.status == "completed" ? (run.elapsedMS > 0 ? String(format: "已完成 · %.1f 秒 · 运行详情", Double(run.elapsedMS) / 1000) : "已完成 · 运行详情") : "运行详情") {
                ForEach(runEvents.filter { $0.runID == run.id && $0.stage != "response.delta" }, id: \.id) { event in
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
                if let first = run.firstTextMS {
                    Text("首段生成：\(first) ms · 历次执行耗时：\(run.attemptDurationsJSON) ms")
                        .font(.caption2.monospaced()).foregroundStyle(.secondary)
                }
                if let response = sessionMessages.first(where: { $0.runID == run.id && $0.role != "user" }),
                   let received = response.firstReceivedAt, let displayed = response.firstDisplayedAt {
                    Text("首段收到至呈现：\(max(0, Int(displayed.timeIntervalSince(received) * 1000))) ms")
                        .font(.caption2.monospaced()).foregroundStyle(.secondary)
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

    private func saveDraft() {
        draftSave?.cancel()
        guard let id = draftSessionID, let session = sessions.first(where: { $0.id == id }), session.composerDraft != draft else { return }
        session.composerDraft = draft
        do { try modelContext.save() }
        catch { localError = "草稿尚未保存，请保留当前窗口并重试。" }
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
        selectedSessionID = session.id
        return session
    }

    private func handoffSummary(from source: AgentSession) -> String {
        let latestInput = messages(for: source.id)
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
        if !LearningSessionActions.archive(session, context: modelContext) {
            localError = "归档尚未保存，请重试。"
        }
    }

    private func restore(_ session: AgentSession) {
        guard LearningSessionActions.restore(session, context: modelContext) else {
            localError = "恢复尚未保存，请重试。"
            return
        }
        selectedSessionID = session.id
    }

    private func selectInitialSession() {
        if let selectedSessionID, sessions.contains(where: { $0.id == selectedSessionID }) { return }
        self.selectedSessionID = sessions.first(where: { $0.status == "active" })?.id ?? sessions.first?.id
    }

    private func updateSessionSummary(_ session: AgentSession) {
        let rows = ((try? modelContext.fetch(FetchDescriptor<AgentMessage>())) ?? [])
            .filter { $0.sessionID == session.id && $0.responseState == "complete" }
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

/// Incremental changes invalidate only the selected transcript, not all stored
/// sessions or the composer. Run phase timers live in their own small view.
private struct SessionTranscriptData<Content: View>: View {
    @Query private var messages: [AgentMessage]
    @Query private var events: [SessionEventRecord]
    var content: ([AgentMessage], [SessionEventRecord]) -> Content

    init(sessionID: UUID?, @ViewBuilder content: @escaping ([AgentMessage], [SessionEventRecord]) -> Content) {
        let id = sessionID ?? UUID(uuidString: "00000000-0000-0000-0000-000000000000")!
        _messages = Query(filter: #Predicate<AgentMessage> { $0.sessionID == id }, sort: \AgentMessage.createdAt)
        _events = Query(filter: #Predicate<SessionEventRecord> { $0.sessionID == id && $0.stage != "response.delta" }, sort: \SessionEventRecord.seq)
        self.content = content
    }
    var body: some View { content(messages, events) }
}
