import SwiftData
import SwiftUI
import UniformTypeIdentifiers

struct LearningWorkspace: View {
    var draftStore: LearningDraftStore
    var monitor: AgentServiceMonitor
    @Binding var selectedSessionID: UUID?
    var captureDestination: UUID? = nil
    var entryFocusRequest = 0
    var onEntryFocusConsumed: () -> Void = {}
    var onNewSession: () -> Void = {}
    var onOpenKnowledge: (UUID) -> Void
    var onMessageSaved: (AgentMessage, Bool) -> Void = { _, _ in }

    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduceMotion
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \LearningTask.createdAt) private var tasks: [LearningTask]
    @Query(sort: \TaskEventRecord.seq) private var events: [TaskEventRecord]
    @Query(sort: \AgentRun.createdAt) private var runs: [AgentRun]
    @Query private var firstMessages: [AgentMessage]
    @Query private var captureReferences: [KnowledgeReference]
    @State private var queueInput = false
    @State private var draft = ""
    @State private var draftImages: [LearningImageAttachment] = []
    @State private var showImagePicker = false
    @State private var imagePickerOwner: UUID?
    @State private var imageImports = LearningImageImportQueue()
    @State private var imageDropTargeted = false
    @State private var editorImageDropTargeted = false
    @State private var dictation = DictationController()
    @State private var dictationOriginal = ""
    @State private var localError: String?
    @State private var deletionImpact: SessionDeletionImpact?
    @State private var editingSessionID: UUID?
    @State private var focusRequest = 0
    @State private var draftSessionID: UUID?
    @State private var draftSave: Task<Void, Never>?
    @State private var followsLatest = true
    @State private var userScrolling = false
    @State private var sentMessageID: UUID?
    @State private var activeCaptureID: UUID?
    @State private var stepMessageID: UUID?
    @State private var memoryDestination: (sessionID: UUID, messageID: UUID)?
    @State private var draftSettings: AppSettings?
    @State private var insertion: EditorInsertion?
    @State private var showKnowledgePicker = false
    @State private var quickStarts = AgentQuickStart.initial
    @State private var showSessionTags = false
    @State private var previewMotion = false
    @State private var titleMascot = AgentTitleMascotDriver()
    private let runtime = AppRuntime.current

    init(draftStore: LearningDraftStore = LearningDraftStore(), monitor: AgentServiceMonitor,
         selectedSessionID: Binding<UUID?>, captureDestination: UUID? = nil, entryFocusRequest: Int = 0,
         onEntryFocusConsumed: @escaping () -> Void = {}, onNewSession: @escaping () -> Void = {},
         onOpenKnowledge: @escaping (UUID) -> Void,
         onMessageSaved: @escaping (AgentMessage, Bool) -> Void = { _, _ in }) {
        self.captureDestination = captureDestination
        self.draftStore = draftStore; self.monitor = monitor; _selectedSessionID = selectedSessionID
        self.entryFocusRequest = entryFocusRequest; self.onEntryFocusConsumed = onEntryFocusConsumed
        self.onNewSession = onNewSession; self.onOpenKnowledge = onOpenKnowledge; self.onMessageSaved = onMessageSaved
        if let id = selectedSessionID.wrappedValue {
            _sessions = Query(filter: #Predicate<AgentSession> { $0.id == id })
            _tasks = Query(filter: #Predicate<LearningTask> { $0.sessionID == id }, sort: \LearningTask.createdAt)
            _events = Query(filter: #Predicate<TaskEventRecord> { $0.sessionID == id }, sort: \TaskEventRecord.seq)
            _runs = Query(filter: #Predicate<AgentRun> { $0.sessionID == id }, sort: \AgentRun.createdAt)
            var first = FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == id }, sortBy: [SortDescriptor(\.createdAt)])
            first.fetchLimit = 1
            _firstMessages = Query(first)
        } else {
            _sessions = Query(filter: #Predicate<AgentSession> { _ in false })
            _tasks = Query(filter: #Predicate<LearningTask> { _ in false })
            _events = Query(filter: #Predicate<TaskEventRecord> { _ in false })
            _runs = Query(filter: #Predicate<AgentRun> { _ in false })
            _firstMessages = Query(filter: #Predicate<AgentMessage> { _ in false })
        }
    }

    private enum Layout {
        static let readingWidth: CGFloat = 820

        static func gutter(for width: CGFloat) -> CGFloat { width < 650 ? 16 : 24 }
    }

    private var selectedSession: AgentSession? {
        sessions.first { $0.id == selectedSessionID }
    }

    private var captureOffers: [TopicCaptureOffer] {
        TopicCaptureOffer.read(selectedSession?.captureOffersJSON ?? "[]").map { original in
            var offer = original
            if let task = sessionTasks.first(where: { $0.id == offer.saveTaskID && $0.memoryCommitted }) {
                let ids = captureReferences.filter { $0.taskID == task.id }.map(\.knowledgeID)
                if !ids.isEmpty { offer.status = "saved"; offer.knowledgeIDs = ids; offer.error = nil }
            }
            return offer
        }
    }

    private var isStarting: Bool {
        selectedSession == nil || (selectedSession?.status == "active" && firstMessages.isEmpty)
    }

    private var developerDiagnostics: Bool { draftSettings?.developerMode == true }

    private func messages(for id: UUID) -> [AgentMessage] {
        (try? modelContext.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == id }, sortBy: [SortDescriptor(\.createdAt)]))) ?? []
    }

    private var sessionTasks: [LearningTask] {
        tasks
    }

    var body: some View {
        LearningImageDropContainer(enabled: acceptsImageInput, onTarget: { imageDropTargeted = $0 }, onDrop: dropImages) {
            GeometryReader { geometry in
                workspace(width: geometry.size.width, height: geometry.size.height)
                    .frame(width: geometry.size.width, height: geometry.size.height)
                    .background {
                        if isStarting { AgentTitlePointerRegion(driver: titleMascot).accessibilityHidden(true) }
                    }
            }
            .background(PaperSurface())
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .overlay {
            if acceptsImageInput && (imageDropTargeted || editorImageDropTargeted) {
                ZStack {
                    RoundedRectangle(cornerRadius: 18).fill(.regularMaterial)
                    RoundedRectangle(cornerRadius: 18).strokeBorder(Color.accentColor, style: StrokeStyle(lineWidth: 2, dash: [8, 5]))
                    VStack(spacing: 8) {
                        Image(systemName: "photo.on.rectangle.angled").font(.largeTitle)
                        Text("松开以添加图片").font(.headline)
                        Text("添加到当前草稿 · 每条最多 8 张").font(.subheadline).foregroundStyle(.secondary)
                    }
                }.padding(12).allowsHitTesting(false).accessibilityHidden(true)
            }
        }
        .onChange(of: selectedSession?.status) { _, status in
            if status != nil && status != "active" { imageImports.cancel(); imageDropTargeted = false; editorImageDropTargeted = false }
        }
        .navigationTitle((selectedSession?.title ?? "Agent") + runtime.windowSuffix)
        .toolbar(removing: .title)
        .onAppear(perform: loadDraft)
        .onChange(of: entryFocusRequest, initial: true) { _, value in
            if value > 0 { focusRequest += 1; onEntryFocusConsumed() }
        }
        .onChange(of: selectedSessionID) { _, _ in
            imageImports.cancel(); imageDropTargeted = false; editorImageDropTargeted = false
            localError = nil
            dictation.leave()
            saveDraft()
            loadDraft()
            queueInput = false
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
        .onReceive(NotificationCenter.default.publisher(for: .prepareNewConversation)) { _ in saveDraft() }
        .onDisappear { dictation.leave(); imageImports.cancel(); imageDropTargeted = false; editorImageDropTargeted = false; saveDraft() }
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
        .fileImporter(isPresented: $showImagePicker, allowedContentTypes: [.png, .jpeg], allowsMultipleSelection: true) { result in
            guard imagePickerOwner == draftSessionID else { return }
            switch result {
            case .success(let urls): importImages(urls.map { .file($0) })
            case .failure(let error): localError = error.localizedDescription
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
                    guard (try? modelContext.fetchCount(FetchDescriptor<AgentSession>(predicate: #Predicate { $0.id == id }))) ?? 0 > 0 else { localError = "原会话已删除"; return .handled }
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
        let contentWidth = max(0, min(isStarting ? 820 : Layout.readingWidth, width - gutter * 2))
        return VStack(spacing: 0) {
          if selectedSession != nil { workspaceHeader(contentWidth: contentWidth) }
          if isStarting {
            serviceBanner
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    AgentLandingTitle(driver: titleMascot)
                        .frame(maxWidth: .infinity).padding(.top, 24)
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
            LearningChecklist(session: selectedSession, tasks: sessionTasks, onSelectMessage: { stepMessageID = $0 }, onOpenSession: { selectedSessionID = $0 })
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
             .init(id: "memory", title: session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", symbol: "brain")] : []) + [.init(id: "delete", title: "删除会话", symbol: "trash", destructive: true)]
        ) { action in
            switch action {
            case "new": onNewSession()
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
                Text(runtime.isPerformanceQA ? "性能隔离验收 · 不可发送；输入仅保存在独立测试库。" : "界面预览 · 不可发送；输入仅在内存中，不保存到日常数据库。")
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
                        ForEach(captureOffers.filter { $0.anchorMessageID == message.id }) { offer in
                            TopicCapturePanel(offer: offer, focused: captureDestination == offer.id,
                                enabled: selectedSession?.status == "active" && runtime.allowsSending && !dictation.busy,
                                persistenceError: sessionTasks.first(where: { $0.id == offer.saveTaskID && !$0.memoryCommitted })?.errorCode,
                                deliveryError: sessionMessages.last(where: { ConversationProcessor.object($0.operationJSON)?["target_id"] as? String == offer.id.uuidString.lowercased() })?.lastDeliveryError, onAction: { rawKind in
                                    let enrollReview = rawKind == "capture_save_review"
                                    let kind = enrollReview ? "capture_save" : rawKind
                                    if kind == "capture_save" { followsLatest = false; activeCaptureID = offer.id }
                                    else { activeCaptureID = nil }
                                    sendBound(kind, title: kind == "capture_save" ? "录入这段知识" : kind == "capture_later" ? "稍后录入" : "跳过录入",
                                              target: offer.id.uuidString.lowercased(), version: offer.version, reviewRequested: enrollReview)
                                    if kind == "capture_save", localError == nil {
                                        Task { @MainActor in await Task.yield(); proxy.scrollTo(offer.id, anchor: .top) }
                                    }
                                    return localError == nil
                                }, onOpenKnowledge: onOpenKnowledge)
                                .id(offer.id)
                                .transition(.opacity.combined(with: .offset(y: reduceMotion ? 0 : 8)))
                        }
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
                        if message.role == "user", let task = sessionTasks.first(where: { $0.inputMessageID == message.id }),
                           !captureOffers.contains(where: { $0.saveTaskID == task.id }) {
                            taskCard(task, run: message.runID.flatMap { id in runs.first(where: { $0.id == id }) }, runEvents: runEvents, sessionMessages: sessionMessages)
                        }
                        if let task = sessionTasks.first(where: { ConversationProcessor.object($0.learningOutcomeJSON)?["message_id"] as? String == message.id.uuidString.lowercased() }) {
                            LearningOutcome(task: task, tasks: sessionTasks)
                        }
                    }
                }
                pendingOperation
                Color.clear.frame(height: 1).id("latest")
            }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: captureOffers.map(\.id))
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
              if let id = captureDestination, captureOffers.contains(where: { $0.id == id }) {
                  followsLatest = false
                  proxy.scrollTo(id, anchor: .center)
              } else if let destination = memoryDestination, destination.sessionID == selectedSessionID,
                 sessionMessages.contains(where: { $0.id == destination.messageID }) {
                  followsLatest = false
                  proxy.scrollTo(destination.messageID, anchor: .top)
                  memoryDestination = nil
              } else { proxy.scrollTo("latest", anchor: .bottom) }
          }
          .onChange(of: captureOffers) { _, values in
              if let id = activeCaptureID, values.contains(where: { $0.id == id && $0.status == "saving" }) {
                  proxy.scrollTo(id, anchor: .top)
              }
          }
          .onChange(of: captureDestination) { _, id in
              if let id { followsLatest = false; proxy.scrollTo(id, anchor: .center) }
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
            VStack(alignment: isUser ? .trailing : .leading, spacing: 5) {
              if isUser {
                  if message.imageAttachment != nil {
                      LearningMessageImages(data: message.imageAttachment, maximumWidth: bubbleWidth)
                  }
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
                  Text(message.responseState == "interrupted" ? "回复已中断" : "回复未完成").font(.caption2).foregroundStyle(.secondary)
              } else if message.responseState == "streaming" {
                  Text("正在回复").font(.caption2).foregroundStyle(.secondary)
              } else if message.responseState == "recovering" {
                  Text("正在整理完整回复").font(.caption2).foregroundStyle(.secondary)
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
        LearningTaskCard(task: task, run: run, runs: runs, events: events, runEvents: runEvents,
            sessionMessages: sessionMessages, isSessionActive: selectedSession?.status == "active",
            developerDiagnostics: developerDiagnostics, onControl: { taskControl(task, action: $0) },
            onRespond: { respond($0, to: task) })
    }

    private func eventInformation(_ event: SessionEventRecord) -> String {
        var values: [String] = []
        if developerDiagnostics { values += [event.stage, event.model] }
        if event.attempt > 1 { values.append("第 \(event.attempt) 次") }
        if developerDiagnostics, let duration = event.durationMS { values.append("\(duration) ms") }
        return values.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var composerControls: some View {
        ComposerControlsLayout { composerMenus; contextCapacity }
    }

    private var composerMenus: some View {
        HStack(spacing: 2) {
            SingleLevelMenu(title: "添加材料", symbol: "plus", items: [
                .init(id: "text", title: "添加文字", symbol: "text.alignleft"),
                .init(id: "link", title: "粘贴公开链接", symbol: "link"),
                .init(id: "image", title: "添加图片", symbol: "photo"),
                .init(id: "knowledge", title: "引用已有知识卡", symbol: "books.vertical")
            ]) { id in
                switch id {
                case "text": focusRequest += 1
                case "link": insertion = EditorInsertion(text: NSPasteboard.general.string(forType: .string) ?? "")
                case "image": imagePickerOwner = draftSessionID; showImagePicker = true
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
            if !draftImages.isEmpty {
                LearningImageGrid(images: draftImages) { index in
                    var updated = draftImages; updated.remove(at: index); updateImages(updated)
                }.disabled(dictation.busy)
                Text("已添加 \(draftImages.count) 张图片 · 发送后由 DeepSeek 理解")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if imageImports.isLoading { Text("正在准备图片…").font(.caption).foregroundStyle(.secondary) }
            LearningComposerInput(text: $draft, focusRequest: focusRequest,
                sessionID: selectedSessionID ?? draftSettings?.agentDraftID, placeholder: activeActionPlaceholder,
                insertion: dictation.insertion ?? insertion, editable: !dictation.busy,
                onInsertionApplied: acceptDictation, onSubmit: submitDraft,
                preservesFocusOnClick: titleMascot.preservesInputFocus, onImagePaste: pasteImage, onImageDrop: dropImages, onImageDragTarget: { editorImageDropTargeted = $0 }) {
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
                .disabled(dictation.busy || imageImports.isLoading || !runtime.allowsSending || (draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draftImages.isEmpty))
                .help(runtime.isPreview ? "界面预览不可发送" : "发送（Return 或 ⌘ Return）")
                .accessibilityLabel("发送")
                }
                .padding(.horizontal, 8)
            }
            HStack(spacing: 10) {
                if runtime.isPreview { Text(runtime.isPerformanceQA ? "独立测试数据 · 不发送" : "仅供排版检查 · 不发送、不持久保存") }
                Spacer()
                if runtime.allowsSending, let run = runs.last(where: { $0.sessionID == selectedSessionID }),
                   ["accepted", "running", "queued", "adjusting", "resuming"].contains(run.status) {
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
        guard !dictation.busy, !imageImports.isLoading else { return }
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty || !draftImages.isEmpty else { return }
        let defaultRequest = draftImages.count == 1 ? "请帮我理解这张图片中的内容" : "请帮我理解这些图片中的内容"
        sendMessage(content.isEmpty ? defaultRequest : content, image: LearningImageAttachment.encodeAll(draftImages))
    }

    private var acceptsImageInput: Bool {
        !dictation.busy && (selectedSessionID == nil || selectedSession?.status == "active")
    }

    private func reserveImages(_ count: Int) -> LearningImageImportQueue.Ticket? {
        guard acceptsImageInput else { return nil }
        do {
            if !imageImports.isLoading { localError = nil }
            return try imageImports.reserve(count, existing: draftImages.count)
        } catch { localError = error.localizedDescription; return nil }
    }

    private func pasteImage(_ pasteboard: NSPasteboard) -> Bool {
        guard acceptsImageInput, LearningImageImport.containsImages(pasteboard) else { return false }
        do { importImages(try LearningImageImport.pasteboardInputs(pasteboard)) }
        catch { localError = LearningImageImport.failure(error).localizedDescription }
        return true
    }

    private func importImages(_ inputs: [LearningImageImport.Input]) {
        guard let ticket = reserveImages(inputs.count) else { return }
        let owner = draftSessionID
        Task {
            let result = await Task.detached(priority: .userInitiated) { Result { try inputs.map { try $0.load() } } }.value
            finishImages(ticket, result: result, owner: owner)
        }
    }

    private func dropImages(_ pasteboard: NSPasteboard) -> Bool {
        guard acceptsImageInput, LearningImageImport.containsDropImages(pasteboard) else { return false }
        do {
            let capacity = LearningImageAttachment.maximumCount - draftImages.count - imageImports.pendingCount
            let plan = try LearningImageImport.captureDrop(pasteboard, capacity: capacity)
            guard let ticket = reserveImages(plan.reservationCount) else { return false }
            let owner = draftSessionID
            LearningImageImport.loadDrop(plan) { result in finishImages(ticket, result: result, owner: owner) }
            return true
        } catch {
            localError = "这批图片未添加：" + error.localizedDescription
            return false
        }
    }

    private func finishImages(_ ticket: LearningImageImportQueue.Ticket, result: Result<[LearningImageAttachment], Error>, owner: UUID?) {
        let results = imageImports.finish(ticket, with: result)
        guard owner == draftSessionID, selectedSessionID == nil || selectedSession?.status == "active" else { return }
        var images = draftImages
        var failures: [String] = []
        for result in results {
            switch result {
            case .success(let added): images.append(contentsOf: added)
            case .failure(let error): failures.append(error.localizedDescription)
            }
        }
        if images != draftImages { updateImages(images, clearError: false) }
        if !failures.isEmpty { localError = "这批图片未添加：" + failures.joined(separator: "；") }
    }

    private func updateImages(_ images: [LearningImageAttachment], clearError: Bool = true) {
        draftImages = images
        do {
            try draftStore.saveImage(LearningImageAttachment.encodeAll(images), sessionID: draftSessionID, context: modelContext)
            if clearError { localError = nil }
            focusRequest += 1
        } catch { localError = "图片草稿尚未保存，请保留当前窗口并重试。" }
    }

    private func sendMessage(_ content: String, operation: [String: Any]? = nil, reviewRequested: Bool = false, image: Data? = nil, consumesDraft: Bool = true) {
        guard !dictation.busy else { return }
        guard runtime.allowsSending else { localError = "界面预览不发送消息，输入仅用于排版检查。"; return }
        let started = Date.now
        guard let session = selectedSession else {
            do {
                let (session, message) = try AgentComposerStore.sendFirst(content, context: modelContext, image: image)
                draft = ""
                draftImages = []; draftStore.imageSent(sessionID: nil)
                draftSessionID = session.id
                selectedSessionID = session.id
                sentMessageID = message.id
                focusRequest += 1
                onMessageSaved(message, false)
                ConversationSync.wake()
            } catch { localError = "本机保存失败，草稿仍保留，请重试。" }
            return
        }
        guard session.status == "active" else {
            localError = "请先恢复归档的会话，再继续输入。"
            return
        }
        if operation == nil && messages(for: session.id).isEmpty {
            do {
                let message = try AgentComposerStore.sendInitial(content, in: session, context: modelContext, image: image)
                draft = ""; sentMessageID = message.id; localError = nil
                draftImages = []; draftStore.imageSent(sessionID: session.id)
                focusRequest += 1
                onMessageSaved(message, false)
                ConversationSync.wake()
            } catch { localError = "本机保存失败，输入仍保留，请重试。" }
            return
        }
        let message = AgentMessage(sessionID: session.id, role: "user", content: content,
                                   contentType: TodayView.firstURL(in: content) == nil ? "text" : "url")
        message.clientMessageID = message.id
        message.deliveryMode = queueInput ? "queue" : "steer"
        message.operationJSON = operation.map(ConversationProcessor.json)
        message.reviewRequested = reviewRequested
        message.imageAttachment = image
        if image != nil { message.contentType = "image" }
        modelContext.insert(message)
        if !queueInput, let active = runs.last(where: { $0.sessionID == session.id && ["running", "accepted", "adjusting"].contains($0.status) }) {
            active.status = "adjusting"
            active.userSummary = "已收到补充，正在调整"
            for response in messages(for: session.id) where response.runID == active.id && ["streaming", "recovering"].contains(response.responseState) {
                response.responseState = "interrupted"
            }
        }
        session.updatedAt = .now
        if session.title == "新学习 Session" || (session.title == "新会话" && messages(for: session.id).filter { $0.role == "user" }.count <= 1) { session.title = String(content.prefix(28)) }
        do {
            if operation == nil && consumesDraft { session.composerDraft = ""; session.composerImage = nil }
            try modelContext.save()
            if operation == nil && consumesDraft { draft = ""; draftImages = []; draftStore.imageSent(sessionID: session.id) }
            message.localSavedMS = Int(Date.now.timeIntervalSince(started) * 1000)
            queueInput = false
            localError = nil
            if operation?["kind"] as? String != "capture_save" {
                sentMessageID = message.id
                focusRequest += 1
            }
            onMessageSaved(message, operation?["kind"] as? String == "save")
            ConversationSync.wake()
        } catch {
            modelContext.rollback()
            localError = "本机保存失败，输入仍保留，请重试。"
        }
    }

    private func respond(_ content: String, to task: LearningTask) {
        // All free text is semantically interpreted, never inferred from a button label.
        sendMessage(content, consumesDraft: false)
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
            RunDetails(run: run.status == "completed" ? nil : run) {
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
                if developerDiagnostics, let first = run.firstTextMS {
                    Text("首段生成：\(first) ms · 历次执行耗时：\(run.attemptDurationsJSON) ms")
                        .font(.caption2.monospaced()).foregroundStyle(.secondary)
                }
                if developerDiagnostics, let response = sessionMessages.first(where: { $0.runID == run.id && $0.role != "user" }),
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
           let kind = pending["kind"] as? String, kind != "save",
           let target = pending["target_id"] as? String,
           let version = pending["version"] as? Int {
            VStack(alignment: .leading, spacing: 8) {
                if kind == "new_session" {
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

    private func sendBound(_ kind: String, title: String, target: String, version: Int, selection: [String] = [], reviewRequested: Bool = false) {
        sendMessage(title, operation: ["kind": kind, "target_id": target, "version": version, "selection": selection], reviewRequested: reviewRequested)
    }

    private func saveDraft() {
        draftSave?.cancel()
        guard draftSettings != nil else { return }
        do { try draftStore.save(draft, sessionID: draftSessionID, context: modelContext) }
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
            draftImages = LearningImageAttachment.decodeAll(try draftStore.image(sessionID: draftSessionID, context: modelContext))
            draft = draftStore.unsavedText(sessionID: draftSessionID) ?? selectedSession?.composerDraft ?? draftSettings?.agentDraftText ?? ""
            if draftStore.unsavedText(sessionID: draftSessionID) != nil {
                do { try draftStore.save(draft, sessionID: draftSessionID, context: modelContext) }
                catch { localError = "草稿尚未保存，输入已恢复，请保留当前窗口并重试。" }
            }
            insertion = nil
            dictation.bind(selectedSessionID ?? draftSettings?.agentDraftID)
        } catch { localError = "草稿暂时无法载入，请重试。" }
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
