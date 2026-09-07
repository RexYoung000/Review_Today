import SwiftData
import SwiftUI

struct LearningWorkspace: View {
    var monitor: AgentServiceMonitor
    @Binding var selectedSessionID: UUID?
    var entryFocusRequest = 0
    var onEntryFocusConsumed: () -> Void = {}
    var onOpenKnowledge: (UUID) -> Void

    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduceMotion
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \LearningTask.createdAt) private var tasks: [LearningTask]
    @Query(sort: \TaskEventRecord.seq) private var events: [TaskEventRecord]
    @Query(sort: \SourceReference.createdAt) private var sourceReferences: [SourceReference]
    @Query(sort: \KnowledgeReference.createdAt) private var knowledgeReferences: [KnowledgeReference]
    @Query(sort: \AgentRun.createdAt) private var runs: [AgentRun]
    @State private var queueInput = false
    @State private var draft = ""
    @State private var dictation = DictationController()
    @State private var dictationOriginal = ""
    @State private var localError: String?
    @State private var deletionImpact: SessionDeletionImpact?
    @State private var editingSessionID: UUID?
    @State private var inputHeight: CGFloat = 64
    @State private var inputFocused = false
    @State private var focusRequest = 0
    @State private var draftSessionID: UUID?
    @State private var draftSave: Task<Void, Never>?
    @State private var followsLatest = true
    @State private var userScrolling = false
    @State private var sentMessageID: UUID?
    @State private var stepMessageID: UUID?
    @State private var memoryDestination: (sessionID: UUID, messageID: UUID)?
    @State private var draftSettings: AppSettings?
    @State private var insertion: EditorInsertion?
    @State private var showKnowledgePicker = false
    @State private var quickStarts = AgentQuickStart.initial
    @State private var showSessionTags = false
    @State private var previewMotion = false
    private let runtime = AppRuntime.current

    private enum Layout {
        static let readingWidth: CGFloat = 820

        static func gutter(for width: CGFloat) -> CGFloat { width < 650 ? 16 : 24 }
    }

    private var selectedSession: AgentSession? {
        sessions.first { $0.id == selectedSessionID }
    }

    private var developerDiagnostics: Bool { draftSettings?.developerMode == true }

    private func messages(for id: UUID) -> [AgentMessage] {
        (try? modelContext.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == id }, sortBy: [SortDescriptor(\.createdAt)]))) ?? []
    }

    private var sessionTasks: [LearningTask] {
        guard let selectedSessionID else { return [] }
        return tasks.filter { $0.sessionID == selectedSessionID }.sorted { $0.createdAt < $1.createdAt }
    }

    @ViewBuilder
    private var learningChecklist: some View {
        if let session = selectedSession,
           let task = sessionTasks.last(where: { $0.learningPlanJSON != nil }),
           let plan = ConversationProcessor.object(task.learningPlanJSON),
           let steps = plan["steps"] as? [[String: Any]], !steps.isEmpty {
            let current = steps.first { $0["id"] as? String == plan["current_step_id"] as? String }
            VStack(alignment: .leading, spacing: 8) {
                Button {
                    session.learningChecklistExpanded.toggle()
                    try? modelContext.save()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: session.learningChecklistExpanded ? "chevron.down" : "chevron.right")
                        Text(task.status == "completed" ? "本次学习已结束" : "学习安排").fontWeight(.medium)
                        Text(current?["title"] as? String ?? plan["goal"] as? String ?? "").foregroundStyle(.secondary).lineLimit(1)
                        Spacer(minLength: 0)
                    }.font(.callout).padding(.vertical, 5).contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityValue(session.learningChecklistExpanded ? "已展开" : "已收起")
                if session.learningChecklistExpanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                                let state = step["state"] as? String ?? "pending"
                                let understanding = step["understanding"] as? String ?? "unknown"
                                let label = understanding == "verified" ? "已验证" : understanding == "self_reported" ? "自述理解" : state == "skipped" ? "跳过检查" : state == "explained" ? "已讲解" : "待学习"
                                Button {
                                    if let raw = (step["message_ids"] as? [String])?.first { stepMessageID = UUID(uuidString: raw) }
                                } label: {
                                    HStack(alignment: .firstTextBaseline, spacing: 9) {
                                        Text("\(index + 1)").monospacedDigit().foregroundStyle(.secondary).frame(width: 18)
                                        Text(step["title"] as? String ?? "学习步骤").lineLimit(2)
                                        Spacer(minLength: 8)
                                        Text(label).font(.caption).foregroundStyle(.secondary)
                                    }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 5).contentShape(Rectangle())
                                }.buttonStyle(.plain)
                                    .disabled((step["message_ids"] as? [String] ?? []).isEmpty)
                                    .help("查看对应内容，不会改变理解状态")
                            }
                        }
                    }.frame(height: min(CGFloat(steps.count) * 38, 160))
                    Text("点击步骤回看内容；要调整安排，直接告诉我。").font(.caption2).foregroundStyle(.secondary)
                }
            }.padding(.bottom, 10)
        }
    }

    @ViewBuilder
    private func learningOutcome(_ task: LearningTask) -> some View {
        if let outcome = ConversationProcessor.object(task.learningOutcomeJSON) {
            let verified = outcome["verified"] as? [String] ?? []
            let explained = outcome["explained"] as? [String] ?? []
            VStack(alignment: .leading, spacing: 8) {
                Text("本次学习小结").font(.headline)
                if !verified.isEmpty { Text("已验证：" + verified.joined(separator: "、")) }
                if !explained.isEmpty { Text("已讲解，仍可练习：" + explained.joined(separator: "、")) }
                if verified.isEmpty && explained.isEmpty { Text(task.understanding == "verified" ? "本次理解检查已通过。" : "内容已整理交付，尚未验证理解。") }
                Text(task.memoryCommitted || sessionTasks.contains(where: { $0.memoryCommitted && $0.draftTargetID == task.id.uuidString.lowercased() }) ? "已加入知识库" : "学习成果已保留在会话中；入库由你决定。")
                    .font(.caption).foregroundStyle(.secondary)
            }.font(.callout).frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 12)
                .overlay(alignment: .top) { Rectangle().fill(runway.hairline).frame(height: 1) }
        }
    }

    var body: some View {
        GeometryReader { geometry in
            workspace(width: geometry.size.width, height: geometry.size.height)
                .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .background(PaperSurface())
        .navigationTitle((selectedSession?.title ?? "Agent") + runtime.windowSuffix)
        .toolbar(removing: .title)
        .onAppear(perform: loadDraft)
        .onChange(of: entryFocusRequest, initial: true) { _, value in
            if value > 0 { focusRequest += 1; onEntryFocusConsumed() }
        }
        .onChange(of: selectedSessionID) { _, _ in
            dictation.leave()
            saveDraft()
            loadDraft()
            queueInput = false
            localError = nil
            followsLatest = true
            showSessionTags = false
            previewMotion = false
        }
        .onChange(of: draft) { _, _ in
            draftSave?.cancel()
            draftSave = Task {
                try? await Task.sleep(for: .milliseconds(250))
                guard !Task.isCancelled else { return }
                saveDraft()
            }
        }
        .onDisappear { dictation.leave(); saveDraft() }
        .onReceive(NotificationCenter.default.publisher(for: .dictationSessionsDeleted)) { note in
            if let ids = note.object as? Set<UUID>, let owner = dictation.owner, ids.contains(owner) { dictation.cancel() }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in dictation.leave(); saveDraft() }
        .sheet(item: $deletionImpact) { impact in
            SessionDeletionSheet(impact: impact) { _ in selectedSessionID = nil }
        }
        .sheet(isPresented: $showKnowledgePicker) {
            ComposerKnowledgePicker { card in
                insertion = EditorInsertion(text: "[\(card.title.isEmpty ? card.learningGoal : card.title)](reviewtoday://knowledge/\(card.id.uuidString.lowercased()))")
                showKnowledgePicker = false
            }
        }
        .environment(\.openURL, OpenURLAction { url in
            guard url.scheme == "reviewtoday" else { return .systemAction }
            let key = url.lastPathComponent
            if url.host == "knowledge", let id = UUID(uuidString: key) { onOpenKnowledge(id); return .handled }
            if url.host == "memory",
               let ref = runs.filter({ $0.sessionID == selectedSessionID }).flatMap({ LearningMemory.array($0.memoryReferencesJSON) }).first(where: { $0["id"] as? String == key }) {
                if let id = (ref["knowledge_id"] as? String).flatMap(UUID.init(uuidString:)) { onOpenKnowledge(id) }
                else if let id = (ref["session_id"] as? String).flatMap(UUID.init(uuidString:)) {
                    guard sessions.contains(where: { $0.id == id }) else { localError = "原会话已删除"; return .handled }
                    if let messageID = (ref["message_id"] as? String).flatMap(UUID.init(uuidString:)) {
                        memoryDestination = (id, messageID)
                    }
                    selectedSessionID = id
                    stepMessageID = (ref["message_id"] as? String).flatMap(UUID.init(uuidString:))
                }
                return .handled
            }
            return .discarded
        })
        .sheet(isPresented: Binding(
            get: { editingSessionID != nil },
            set: { if !$0 { editingSessionID = nil } }
        )) {
            if let id = editingSessionID, let session = sessions.first(where: { $0.id == id }) {
                SessionTagEditor(session: session)
            }
        }
    }

    private func workspace(width: CGFloat, height: CGFloat) -> some View {
        let gutter = Layout.gutter(for: width)
        let contentWidth = max(0, min(selectedSession == nil ? 820 : Layout.readingWidth, width - gutter * 2))
        return VStack(spacing: 0) {
          if selectedSession != nil { workspaceHeader(contentWidth: contentWidth) }
          if selectedSession == nil {
            serviceBanner
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(spacing: 16) {
                        VStack(alignment: .center, spacing: 6) {
                            Text("Review Today").font(.system(size: 30, weight: .semibold)).foregroundStyle(runway.ink)
                            Text("从一个问题开始，把理解留住。").font(.callout).foregroundStyle(.secondary)
                        }
                    }.multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.top, 24)
                    composer(contentWidth: contentWidth)
                    HStack {
                        Text("快捷开始").font(.subheadline.weight(.medium)).foregroundStyle(.secondary)
                        Spacer()
                        ChromeIconButton(title: "换一组快捷开始", symbol: "arrow.clockwise") {
                            quickStarts = AgentQuickStart.refreshed(after: quickStarts)
                        }
                    }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), spacing: 12)], spacing: 12) {
                        ForEach(quickStarts) { start in
                            QuickStartCard(start: start) {
                                if !dictation.busy { insertion = EditorInsertion(text: start.prompt, templateID: start.id) }
                            }
                        }
                    }
                }.frame(width: contentWidth).padding(.bottom, 24).frame(minHeight: height, alignment: .center).frame(maxWidth: .infinity)
            }
          } else {
            learningChecklist
                .frame(width: contentWidth).frame(maxWidth: .infinity)
            Divider()
            serviceBanner
            conversation(contentWidth: contentWidth)
            composer(contentWidth: contentWidth)
          }
        }
        .background(runway.canvas)
    }

    private func workspaceHeader(contentWidth: CGFloat) -> some View {
        HStack(spacing: 8) {
            Spacer(minLength: 0)
            if let session = selectedSession {
                ChromeIconButton(title: "会话标签", symbol: "tag", selected: showSessionTags) { showSessionTags.toggle() }
                    .popover(isPresented: $showSessionTags, arrowEdge: .top) {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("会话标签").font(.headline)
                            Text(session.displayTopicTags.isEmpty ? "尚无主题标签" : session.displayTopicTags.joined(separator: " · "))
                                .font(.callout).fixedSize(horizontal: false, vertical: true)
                            if session.status == "active" {
                                Button("编辑标签") { showSessionTags = false; editingSessionID = session.id }
                            }
                        }.padding(16).frame(width: 260).environment(\.runway, runway)
                    }
                if !session.memoryUseAllowed { MemoryExcludedMark() }
                ChromeIconButton(title: session.status == "active" ? "归档" : "恢复",
                                 symbol: session.status == "active" ? "archivebox" : "arrow.uturn.backward") {
                    if session.status == "active" { archive(session) } else { restore(session) }
                }
                sessionMenu(session).fixedSize()
            }
        }
        .frame(width: contentWidth).padding(.vertical, 12).frame(maxWidth: .infinity)
    }

    private func sessionMenu(_ session: AgentSession) -> some View {
        SingleLevelMenu(title: "会话操作", symbol: "ellipsis", arrowEdge: .top, items:
            [.init(id: "new", title: "新对话", symbol: "plus")] +
            (session.status == "active" ? [.init(id: "tags", title: "编辑主题标签", symbol: "tag"),
             .init(id: "memory", title: session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", symbol: "brain")] : [.init(id: "delete", title: "永久删除", symbol: "trash", destructive: true)])
        ) { action in
            switch action {
            case "new": selectedSessionID = nil
            case "tags": editingSessionID = session.id
            case "delete":
                do { deletionImpact = try SessionDeletion.impact([session.id], context: modelContext) }
                catch { localError = "无法确认删除范围，请重试。" }
            default:
                if !LearningMemory.setAllowed(!session.memoryUseAllowed, session: session, context: modelContext) { localError = "记忆设置未保存，请重试。" }
            }
        }
    }

    @ViewBuilder
    private var serviceBanner: some View {
        if runtime.isPreview {
            HStack(spacing: 10) {
                if previewMotion { DotsRing(color: runway.agent, reduced: reduceMotion).frame(width: 18, height: 18) }
                Text("界面预览 · 不可发送；输入仅在内存中，不保存到日常数据库。")
                Spacer(minLength: 4)
                Button(previewMotion ? "停止预览" : "预览动效（8 秒）") { previewMotion.toggle() }
            }.font(.caption).foregroundStyle(.secondary).padding(.horizontal, 24).padding(.vertical, 8)
                .task(id: previewMotion) {
                    guard previewMotion else { return }
                    try? await Task.sleep(for: .seconds(8))
                    if !Task.isCancelled { previewMotion = false }
                }
        } else if monitor.connection != .ready || !monitor.keyConfigured {
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
                    if developerDiagnostics && !monitor.technicalDetail.isEmpty {
                        DisclosureGroup("技术详情") {
                            Text(monitor.technicalDetail).font(.caption.monospaced()).textSelection(.enabled)
                        }.font(.caption).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if monitor.connection == .unavailable {
                    Button("重试连接") { monitor.retryLaunch() }
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
                                Text(MessageDeliveryPresentation.summary(message, session: selectedSession, monitor: monitor, runtime: runtime))
                                    .font(.caption).foregroundStyle(message.lastDeliveryError == nil ? runway.ink.opacity(0.6) : .orange)
                                if MessageDeliveryPresentation.canRetry(message, session: selectedSession, runtime: runtime) {
                                    Button("重试发送") {
                                        message.lastDeliveryError = nil
                                        do { try modelContext.save(); ConversationSync.wake() }
                                        catch { modelContext.rollback(); localError = "重试操作未保存，请再试。" }
                                    }.font(.caption)
                                }
                            }
                        }
                        if message.role == "user", let task = sessionTasks.first(where: { $0.inputMessageID == message.id }) {
                            taskCard(task, run: message.runID.flatMap { id in runs.first(where: { $0.id == id }) }, runEvents: runEvents, sessionMessages: sessionMessages)
                        }
                        if let task = sessionTasks.first(where: { ConversationProcessor.object($0.learningOutcomeJSON)?["message_id"] as? String == message.id.uuidString.lowercased() }) {
                            learningOutcome(task)
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
          .task(id: selectedSessionID) {
              await Task.yield() // the destination transcript must own the scroll IDs first
              guard !Task.isCancelled else { return }
              if let destination = memoryDestination, destination.sessionID == selectedSessionID,
                 sessionMessages.contains(where: { $0.id == destination.messageID }) {
                  followsLatest = false
                  proxy.scrollTo(destination.messageID, anchor: .top)
                  memoryDestination = nil
              } else { proxy.scrollTo("latest", anchor: .bottom) }
          }
          .onChange(of: sentMessageID) { _, id in
              if id != nil { proxy.scrollTo("latest", anchor: .bottom); followsLatest = true }
          }
          .onChange(of: stepMessageID) { _, id in
              if let id { followsLatest = false; proxy.scrollTo(id, anchor: .top) }
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
        VStack(alignment: .leading, spacing: 16) {
            Text("今天，想弄懂什么？").font(.title2.weight(.semibold))
            Text("从一个问题开始，或把资料放在这里。学习成果由你决定是否保存。")
                .font(.callout).foregroundStyle(.secondary)
            ForEach(["RAG 是什么？", "带我学习 RAG 的基本原理", "帮我准备 RAG 面试题"], id: \.self) { example in
                Button { guard !dictation.busy else { return }; draft = example; focusRequest += 1 } label: {
                    Label(example, systemImage: "arrow.up.left").font(.callout)
                }.buttonStyle(.borderless)
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
                  LearningAnswerText(content: message.content, availableWidth: bubbleWidth)
                      .foregroundStyle(runway.ink)
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

    private func taskCard(_ task: LearningTask, run: AgentRun?, runEvents: [SessionEventRecord], sessionMessages: [AgentMessage]) -> some View {
        let taskEvents = events.filter { $0.taskID == task.id }.sorted { $0.seq < $1.seq }
        let options = Self.options(task.requiredActionOptionsJSON)
        let taskAnswers = sessionMessages.filter { message in
            message.role != "user" && (message.taskID == task.id || runs.contains { $0.id == message.runID && $0.taskID == task.id })
        }
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                if let run, run.status != "completed" {
                    RunPhaseLine(run: run)
                } else {
                    Circle()
                        .fill(Self.tone(task.status) == .problem ? Color.orange : runway.information)
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
                if selectedSession?.status == "active" && (task.status == "retryable_failed" || task.status == "needs_attention") {
                    Button("重试") { taskControl(task, action: "retry") }
                        .buttonStyle(.borderless)
                    Button("取消目标") { taskControl(task, action: "cancel_task") }
                        .buttonStyle(.borderless)
                }
            }

            if selectedSession?.status == "active", let prompt = task.requiredActionPrompt, task.pendingActionID == nil {
                if !taskAnswers.contains(where: { AnswerDocument.containsQuestion(prompt, in: $0.content) }) {
                    Text(prompt)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
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
                                .fill(event.errorCode == nil ? runway.information : Color.orange)
                                .frame(width: 6, height: 6)
                                .padding(.top, 5)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(event.userSummary)
                                    .font(.caption.weight(.medium))
                                    .fixedSize(horizontal: false, vertical: true)
                                if developerDiagnostics { Text(event.node)
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true) }
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
                                if !event.detailSummary.isEmpty && (developerDiagnostics || event.errorCode == nil) {
                                    Text(event.detailSummary)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if developerDiagnostics, let error = event.errorCode {
                                    Text(error)
                                        .font(.caption2.monospaced())
                                        .foregroundStyle(.orange)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if developerDiagnostics, let recovery = event.recoveryAction {
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
                                if !event.detail.isEmpty && (developerDiagnostics || event.errorCode == nil) { Text(event.detail).font(.caption).foregroundStyle(.secondary) }
                                Text(eventInformation(event))
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

    private func eventInformation(_ event: SessionEventRecord) -> String {
        var values: [String] = []
        if developerDiagnostics { values += [event.stage, event.model] }
        if event.attempt > 1 { values.append("第 \(event.attempt) 次") }
        if let duration = event.durationMS { values.append("\(duration) ms") }
        return values.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var composerControls: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 4) { composerMenus; contextCapacity }
            VStack(alignment: .leading, spacing: 2) {
                composerMenus
                contextCapacity
            }
        }.font(.callout).controlSize(.small)
    }

    private var composerMenus: some View {
        HStack(spacing: 2) {
            SingleLevelMenu(title: "添加材料", symbol: "plus", items: [
                .init(id: "text", title: "添加文字", symbol: "text.alignleft"),
                .init(id: "link", title: "粘贴公开链接", symbol: "link"),
                .init(id: "knowledge", title: "引用已有知识卡", symbol: "books.vertical")
            ]) { id in
                switch id {
                case "text": focusRequest += 1
                case "link": insertion = EditorInsertion(text: NSPasteboard.general.string(forType: .string) ?? "")
                default: showKnowledgePicker = true
                }
            }
            SingleLevelMenu(title: "学习方式", symbol: "arrow.triangle.branch",
                label: Self.modeLabel(selectedSession?.modePreset ?? draftSettings?.agentDraftMode ?? "auto"),
                selectedID: selectedSession?.modePreset ?? draftSettings?.agentDraftMode ?? "auto",
                items: [
                    .init(id: "auto", title: "Auto", symbol: "sparkles", detail: "根据你的目标，选择合适的学习方式。"),
                    .init(id: "memory_organization", title: "知识整理", symbol: "point.3.connected.trianglepath.dotted", detail: "梳理知识和关系，是否入库由你决定。"),
                    .init(id: "source_learning", title: "资料学习", symbol: "doc.text", detail: "分段讲解资料，随时追问和检查理解。"),
                    .init(id: "topic_exploration", title: "主题探索", symbol: "safari", detail: "明确方向，建立学习地图并寻找材料。"),
                    .init(id: "problem_solving", title: "问题攻克", symbol: "bubble.left.and.text.bubble.right", detail: "先理解答案，再独立作答和追问练习。")
                ], onPointerSelection: { focusRequest += 1 }) { updatePreference(mode: $0) }
            let deep = (selectedSession?.thinkingStrength ?? draftSettings?.agentDraftThinking) == "deep"
            SingleLevelMenu(title: "思考强度", symbol: deep ? "sparkles" : "bolt",
                label: deep ? "深入思考" : "智能", selectedID: deep ? "deep" : "smart",
                items: [
                    .init(id: "smart", title: "智能", symbol: "bolt", detail: "适合日常问答与学习，响应更轻快。"),
                    .init(id: "deep", title: "深入思考", symbol: "sparkles", detail: "复杂问题展开分析，可能需要更久。")
                ], onPointerSelection: { focusRequest += 1 }) { updatePreference(strength: $0) }
        }.fixedSize(horizontal: true, vertical: false)
    }

    private var contextCapacity: some View {
        ContextCapacityIndicator(capacity: ContextCapacityPresentation(json: selectedSession?.contextCapacityJSON))
            .id(selectedSession?.id)
    }

    private func updatePreference(mode: String? = nil, strength: String? = nil) {
        do {
            let settings = try AgentComposerStore.settings(modelContext)
            if let strength { settings.lastThinkingStrength = strength }
            if let session = selectedSession {
                guard session.status == "active" else { return }
                if let mode { session.modePreset = mode }
                if let strength { session.thinkingStrength = strength }
                if let run = runs.last(where: { $0.sessionID == session.id }) {
                    guard ConversationProcessor.queueControl(run, action: mode != nil ? "set_mode" : "set_thinking",
                                                             mode: mode, thinkingStrength: strength, context: modelContext) else {
                        localError = "选择尚未保存，请重试。"; return
                    }
                } else { try modelContext.save() }
            } else {
                if let mode { settings.agentDraftMode = mode }
                if let strength { settings.agentDraftThinking = strength }
                try modelContext.save()
            }
        } catch { modelContext.rollback(); localError = "选择尚未保存，请重试。" }
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
            if selectedSession?.syncError != nil {
                Text("进度同步暂时中断，本机内容已保留。").font(.caption).foregroundStyle(.orange)
            }
            if let localError {
                Label(localError, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            if runtime.allowsSending, dictation.busy || dictation.pending || dictation.settling || dictation.error != nil || dictation.notice != nil {
                HStack(spacing: 8) {
                    MascotMotion(surface: .voice, phase: dictation.mascotPhase, level: dictation.level, reduced: reduceMotion)
                        .frame(width: 120, height: 65)
                    Text(dictation.title).font(.caption).foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }.accessibilityElement(children: .combine)
            }
            VStack(spacing: 4) {
                LearningTextInput(text: $draft, height: $inputHeight, focused: $inputFocused,
                                  focusRequest: focusRequest, sessionID: selectedSessionID ?? draftSettings?.agentDraftID,
                                  placeholder: activeActionPlaceholder, ink: NSColor(runway.ink), insertion: dictation.insertion ?? insertion, editable: !dictation.busy, onInsertionApplied: acceptDictation, onSubmit: submitDraft)
                    .frame(height: inputHeight)
                HStack {
                  composerControls.disabled(dictation.busy)
                  Spacer(minLength: 8)
                  if runtime.allowsSending { dictationControls }
                Button(action: submitDraft) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(runway.onAction)
                        .frame(width: 34, height: 34)
                        .background(runway.action, in: Circle())
                }
                .buttonStyle(.plain)
                .disabled(dictation.busy || !runtime.allowsSending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help(runtime.isPreview ? "界面预览不可发送" : "发送（Return 或 ⌘ Return）")
                .accessibilityLabel("发送")
                }
                .padding(.horizontal, 8)
            }
            .padding(10)
            .background(runway.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(inputFocused ? (runway.monochrome ? runway.agent : runway.agent.opacity(0.65)) : runway.controlBorder, lineWidth: inputFocused ? 1.5 : 1))
            HStack(spacing: 10) {
                if runtime.isPreview { Text("仅供排版检查 · 不发送、不持久保存") }
                Spacer()
                if runtime.allowsSending, let run = runs.last(where: { $0.sessionID == selectedSessionID }),
                   ["accepted", "running", "queued", "adjusting"].contains(run.status) {
                    Toggle("排队发送", isOn: $queueInput).toggleStyle(.checkbox)
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

    @ViewBuilder
    private var dictationControls: some View {
        if dictation.busy {
            if dictation.phase == .recording {
                Button("结束录音") { dictation.finish() }.buttonStyle(.borderless)
            }
            Button("取消听写") { dictation.cancel() }.buttonStyle(.borderless)
        } else {
            ChromeIconButton(title: dictation.pending ? "重新录制听写" : "开始听写", symbol: "mic") {
                insertion = nil; dictationOriginal = draft; dictation.start()
            }
                .help("录音发送至阿里云百炼北京地域识别，结束后回填草稿；最长 5 分钟")
            if dictation.pending {
                Button("重试听写") { insertion = nil; dictationOriginal = draft; dictation.retry() }.buttonStyle(.borderless)
                Button("删除录音") { dictation.cancel() }.buttonStyle(.borderless)
            }
        }
    }

    private func acceptDictation(_ text: String) {
        guard dictation.owner == (selectedSessionID ?? draftSettings?.agentDraftID), dictation.phase == .applying else { return }
        draftSave?.cancel()
        let session = sessions.first { $0.id == draftSessionID }
        if let session { session.composerDraft = text }
        else { draftSettings?.agentDraftText = text }
        do {
            try modelContext.save()
            draft = text; dictation.applied(saved: true)
        } catch {
            if let session { session.composerDraft = dictationOriginal }
            else { draftSettings?.agentDraftText = dictationOriginal }
            draft = dictationOriginal; dictation.applied(saved: false)
        }
    }

    private var activeActionPlaceholder: String {
        guard sessionTasks.contains(where: { $0.status == "awaiting_user" && $0.requiredActionPrompt != nil }) else {
            return "输入问题、资料、链接或 JD……"
        }
        return "输入回答或继续提问……"
    }

    private func submitDraft() {
        guard !dictation.busy else { return }
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }
        sendMessage(content)
    }

    private func sendMessage(_ content: String, operation: [String: Any]? = nil) {
        guard !dictation.busy else { return }
        guard runtime.allowsSending else { localError = "界面预览不发送消息，输入仅用于排版检查。"; return }
        let started = Date.now
        guard let session = selectedSession else {
            do {
                let (session, message) = try AgentComposerStore.sendFirst(content, context: modelContext)
                draft = ""
                draftSessionID = session.id
                selectedSessionID = session.id
                sentMessageID = message.id
                focusRequest += 1
                ConversationSync.wake()
            } catch { localError = "本机保存失败，草稿仍保留，请重试。" }
            return
        }
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
                if selectedSession?.status == "active" && ["interrupted", "retryable_failed", "terminal_failed"].contains(run.status) {
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
                        if !event.detail.isEmpty && (developerDiagnostics || event.errorCode == nil) { Text(event.detail).font(.caption) }
                        Text(eventInformation(event))
                            .font(.caption2.monospaced()).foregroundStyle(.secondary)
                        if developerDiagnostics, let error = event.errorCode { Text(error).font(.caption2.monospaced()).foregroundStyle(.orange) }
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
        if selectedSession?.status == "active", let pending = ConversationProcessor.object(selectedSession?.pendingOperationJSON),
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
        if let id = draftSessionID, let session = sessions.first(where: { $0.id == id }) {
            guard session.composerDraft != draft else { return }
            session.composerDraft = draft
        } else if let draftSettings { draftSettings.agentDraftText = draft }
        else { return }
        do { try modelContext.save() }
        catch { localError = "草稿尚未保存，请保留当前窗口并重试。" }
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

    private func loadDraft() {
        do {
            draftSettings = selectedSessionID == nil ? try AgentComposerStore.prepare(modelContext) : try AgentComposerStore.settings(modelContext)
            draftSessionID = selectedSessionID
            draft = selectedSession?.composerDraft ?? draftSettings?.agentDraftText ?? ""
            insertion = nil
            dictation.bind(selectedSessionID ?? draftSettings?.agentDraftID)
        } catch { localError = "草稿暂时无法载入，请重试。" }
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
