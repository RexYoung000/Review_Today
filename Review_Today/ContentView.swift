import SwiftData
import SwiftUI
import UserNotifications

enum SidebarItem: String, Hashable, CaseIterable, Identifiable {
    case today
    case learning
    case library
    case inbox

    var id: String { rawValue }

    var title: String {
        switch self {
        case .today: String(localized: "今天")
        case .learning: "Agent"
        case .library: String(localized: "知识库")
        case .inbox: String(localized: "待处理")
        }
    }

    var systemImage: String {
        switch self {
        case .today: "sun.max"
        case .learning: "terminal"
        case .library: "books.vertical"
        case .inbox: "tray"
        }
    }
}

@MainActor
enum LearningSessionActions {
    @discardableResult
    static func archive(_ session: AgentSession, context: ModelContext) -> Bool {
        let sid = session.id
        let runs = (try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
        for run in runs where ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) {
            if let started = run.startedAt { run.elapsedMS = max(0, Int(Date.now.timeIntervalSince(started) * 1000)) }
            run.startedAt = nil
            run.status = "interrupted"
            run.revision += 1
            run.userSummary = "已停止；会话已归档"
        }
        let messages = (try? context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
        for message in messages {
            if message.responseState == "streaming" { message.responseState = "interrupted" }
            if message.deliveryStatus == "local" { message.deliveryStatus = "held" }
        }
        for control in (try? context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { $0.sessionID == sid && !$0.sent }))) ?? [] {
            control.sent = true // superseded by the atomic Session lifecycle action
            control.lastError = "RT.SESSION.ARCHIVED"
        }
        session.runPaused = true
        session.pendingOperationJSON = nil
        appendLifecycle("archive", session: session)
        session.status = "archived"
        session.archivedAt = .now
        session.updatedAt = .now
        do { try context.save(); ConversationSync.wake(); return true }
        catch { context.rollback(); return false }
    }

    @discardableResult
    static func restore(_ session: AgentSession, context: ModelContext) -> Bool {
        appendLifecycle("restore", session: session)
        session.status = "active"
        session.runPaused = true
        session.archivedAt = nil
        session.updatedAt = .now
        do { try context.save(); ConversationSync.wake(); return true }
        catch { context.rollback(); return false }
    }

    private static func appendLifecycle(_ action: String, session: AgentSession) {
        session.lifecycleRevision += 1
        var actions = (session.lifecycleActionsJSON.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [[String: Any]]) ?? []
        actions.append(["action_id": UUID().uuidString.lowercased(), "action": action, "lifecycle_revision": session.lifecycleRevision])
        session.lifecycleActionsJSON = ConversationProcessor.json(actions)
    }
}

struct SessionTagEditor: View {
    @Bindable var session: AgentSession
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Query private var references: [KnowledgeReference]
    @Query private var knowledge: [Knowledge]
    @State private var tagsText: String

    init(session: AgentSession) {
        self.session = session
        _tagsText = State(initialValue: session.displayTopicTags.joined(separator: "，"))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("编辑会话标签").font(.headline)
            TextField("用逗号分隔，最多 5 个", text: $tagsText)
                .textFieldStyle(.roundedBorder)
            Text("人工标签会覆盖自动标签；Agent 不会静默改回。")
                .font(.caption).foregroundStyle(.secondary)
            if !knowledgeTags.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("关联知识标签 · 只读").font(.caption.weight(.semibold))
                    Text(knowledgeTags.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            HStack {
                Button("恢复自动标签") {
                    session.restoreAutomaticTopicTags()
                    tagsText = session.automaticTopicTags.joined(separator: "，")
                    try? modelContext.save()
                }
                .disabled(session.manualTopicTags == nil)
                Spacer()
                Button("取消") { dismiss() }
                Button("保存") {
                    session.setManualTopicTags(parsedTags)
                    try? modelContext.save()
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 380)
    }

    private var parsedTags: [String] {
        tagsText.components(separatedBy: CharacterSet(charactersIn: "，,\n"))
    }

    private var knowledgeTags: [String] {
        let ids = Set(references.filter { $0.sessionID == session.id }.map(\.knowledgeID))
        return Array(Set(knowledge.filter { ids.contains($0.id) }.map(\.theme).filter { !$0.isEmpty })).sorted()
    }
}

struct AppSidebar: View {
    @Binding var selection: SidebarItem?
    @Binding var selectedSessionID: UUID?
    var inboxCount: Int
    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \AgentRun.updatedAt, order: .reverse) private var runs: [AgentRun]
    @Query(sort: \LearningTask.updatedAt, order: .reverse) private var tasks: [LearningTask]
    @State private var searchText = ""
    @State private var showArchived = false
    @State private var hoveredSessionID: UUID?
    @State private var editingSessionID: UUID?
    @State private var undoSessionID: UUID?
    @State private var searchVisible = false
    @State private var multiSelect = false
    @State private var selectedIDs = Set<UUID>()
    @State private var rangeAnchor: UUID?
    @State private var batchError: String?
    @State private var visibleRowIDs = Set<UUID>()
    @State private var selectionDelays: [UUID: Double] = [:]
    @State private var undoBatchIDs = Set<UUID>()
    @FocusState private var sessionListFocused: Bool
    @AppStorage("reviewToday.sessionsExpanded") private var sessionsExpanded = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var visibleSessions: [AgentSession] {
        sessions.filter { session in
            let statusMatch = showArchived ? session.status == "archived" : session.status == "active"
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
            return statusMatch && (query.isEmpty || session.title.localizedCaseInsensitiveContains(query) ||
                                   session.displayTopicTags.contains(where: { $0.localizedCaseInsensitiveContains(query) }))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            brand
            VStack(spacing: 4) {
                ForEach(SidebarItem.allCases) { item in sidebarRow(item) }
            }
            .padding(.horizontal, 10)

            Divider().padding(.vertical, 12)
            sessionNavigation

            if !undoBatchIDs.isEmpty {
                HStack {
                    Text("已归档 \(undoBatchIDs.count) 个会话")
                    Spacer()
                    Button("撤销") {
                        undoBatchIDs = Set(undoBatchIDs.filter { id in
                            guard let session = sessions.first(where: { $0.id == id }), session.status == "archived" else { return false }
                            return !LearningSessionActions.restore(session, context: modelContext)
                        })
                    }.buttonStyle(.borderless)
                }.font(.caption).padding(10)
            }

            if let undoSessionID, let session = sessions.first(where: { $0.id == undoSessionID }) {
                HStack(spacing: 8) {
                    Text("已归档").font(.caption)
                    Spacer()
                    Button("撤销") {
                        if LearningSessionActions.restore(session, context: modelContext) {
                            showArchived = false
                            selectedSessionID = session.id
                            self.undoSessionID = nil
                        }
                    }
                    .buttonStyle(.borderless)
                }
                .padding(10)
                .background(runway.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .padding(.horizontal, 10)
                .padding(.bottom, 6)
            }

            SettingsLink {
                Label(String(localized: "设置"), systemImage: "gearshape")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .contentShape(Rectangle())
                    .foregroundStyle(Color.secondary)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 10)
            .padding(.bottom, 16)
        }
        .background { PaperSurface() }
        .sheet(isPresented: Binding(
            get: { editingSessionID != nil },
            set: { if !$0 { editingSessionID = nil } }
        )) {
            if let id = editingSessionID, let session = sessions.first(where: { $0.id == id }) {
                SessionTagEditor(session: session)
            }
        }
    }

    private var brand: some View {
        HStack(spacing: 10) {
            CoachMark(pose: .idle, size: 36)
            VStack(alignment: .leading, spacing: 1) {
                Text("Review\nToday").font(.headline)
                Text(String(localized: "记忆教练")).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            AnimatedThemeToggler()
        }
        .padding(.horizontal, 16)
        .padding(.top, 18)
        .padding(.bottom, 20)
    }

    private var sessionNavigation: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button { sessionsExpanded.toggle() } label: {
                    Label("会话", systemImage: sessionsExpanded ? "chevron.down" : "chevron.right")
                        .font(.subheadline.weight(.medium))
                }.buttonStyle(.plain).accessibilityValue(sessionsExpanded ? "已展开" : "已收起")
                Spacer(minLength: 4)
                Button { searchVisible.toggle(); if !searchVisible { searchText = "" } } label: { Image(systemName: "magnifyingglass") }
                    .buttonStyle(.plain).help("搜索会话").accessibilityLabel("搜索会话")
                Button { showArchived.toggle(); selectedIDs.removeAll() } label: { Image(systemName: showArchived ? "archivebox.fill" : "archivebox") }
                    .buttonStyle(.plain).help(showArchived ? "显示进行中会话" : "显示已归档会话")
                    .accessibilityLabel("切换归档视图").accessibilityValue(showArchived ? "已归档" : "进行中")
                Button { multiSelect.toggle(); selectedIDs.removeAll() } label: { Image(systemName: "checklist") }
                    .buttonStyle(.plain).help("多选会话").accessibilityLabel("多选会话")
                Button(action: createSession) { Image(systemName: "plus") }
                    .buttonStyle(.plain).help("新对话").accessibilityLabel("新对话")
            }
            .padding(.horizontal, 14)

            if searchVisible {
              TextField("搜索会话", text: $searchText)
                .textFieldStyle(.roundedBorder)
                .padding(.horizontal, 10)
            }
            if showArchived { Text("已归档").font(.caption).foregroundStyle(.secondary).padding(.horizontal, 14) }
            if multiSelect {
                HStack(spacing: 8) {
                    Button(selectedIDs.count == visibleSessions.count ? "取消全选" : "全选") { selectAll() }
                    Text("\(selectedIDs.count)").monospacedDigit()
                    Spacer(minLength: 0)
                    Button(showArchived ? "恢复" : "归档") { batchArchive() }.disabled(selectedIDs.isEmpty)
                    Button { multiSelect = false; selectedIDs.removeAll() } label: { Image(systemName: "xmark") }.help("退出多选")
                }.font(.caption).buttonStyle(.borderless).padding(.horizontal, 12)
            }
            if let batchError { Text(batchError).font(.caption).foregroundStyle(.orange).padding(.horizontal, 12) }
            if sessionsExpanded {
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(visibleSessions, id: \.id) { session in sessionRow(session) }
                    if visibleSessions.isEmpty {
                        ContentUnavailableView(
                            showArchived ? "没有归档会话" : "开始一个学习会话",
                            systemImage: showArchived ? "archivebox" : "bubble.left.and.bubble.right"
                        )
                        .controlSize(.small).padding(.top, 18)
                    }
                }
                .padding(.horizontal, 8)
            }
            .scrollIndicators(.automatic)
            .focusable().focusEffectDisabled().focused($sessionListFocused)
            .onKeyPress("a", phases: .down) { press in
                guard multiSelect && press.modifiers.contains(.command) else { return .ignored }
                selectAll(); return .handled
            }
            .onKeyPress(.escape) {
                guard multiSelect else { return .ignored }
                multiSelect = false; selectedIDs.removeAll(); return .handled
            }
            } else { Spacer(minLength: 0) }
        }
        .frame(maxHeight: .infinity)
    }

    private func sessionRow(_ session: AgentSession) -> some View {
        let selected = multiSelect ? selectedIDs.contains(session.id) : selectedSessionID == session.id && selection == .learning
        let state = sessionState(session)
        return HStack(spacing: 4) {
            Button {
                if multiSelect || NSEvent.modifierFlags.contains(.command) || NSEvent.modifierFlags.contains(.shift) {
                    multiSelect = true
                    sessionListFocused = true
                    selectionDelays = [:]
                    if NSEvent.modifierFlags.contains(.shift), let anchor = rangeAnchor,
                       let a = visibleSessions.firstIndex(where: { $0.id == anchor }), let b = visibleSessions.firstIndex(where: { $0.id == session.id }) {
                        selectedIDs.formUnion(visibleSessions[min(a,b)...max(a,b)].map(\.id))
                    } else if !selectedIDs.insert(session.id).inserted { selectedIDs.remove(session.id) }
                    rangeAnchor = session.id
                } else { selectedSessionID = session.id; selection = .learning }
            } label: {
                HStack(alignment: .top, spacing: 8) {
                    Group {
                      if multiSelect { SelectionDot(selected: selected, delay: selectionDelays[session.id] ?? 0) }
                      else { Image(systemName: state.symbol) }
                    }
                        .font(.caption).foregroundStyle(state.problem ? Color.orange : .secondary)
                        .frame(width: 13).padding(.top, 3)
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 6) {
                            Text(session.title).font(.callout.weight(.medium)).lineLimit(1)
                            if selected { Image(systemName: "checkmark").font(.caption2) }
                            Spacer(minLength: 4)
                            Text(state.label).font(.caption2).foregroundStyle(state.problem ? Color.orange : .secondary).lineLimit(1)
                        }
                        .foregroundStyle(runway.ink)
                        HStack(spacing: 5) {
                            ForEach(Array(session.displayTopicTags.prefix(2)), id: \.self) { tag in
                                Text(tag).lineLimit(1)
                            }
                            if session.displayTopicTags.count > 2 { Text("+\(session.displayTopicTags.count - 2)") }
                            if !session.displayTopicTags.isEmpty { Text("·") }
                            Text(LearningWorkspace.modeLabel(session.modePreset))
                        }
                        .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 8).padding(.vertical, 9)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if hoveredSessionID == session.id, session.status == "active" {
                Button { archive(session) } label: { Image(systemName: "archivebox") }
                    .buttonStyle(.plain).help("归档")
            }
        }
        .padding(.trailing, 7)
        .background(selected ? runway.field : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(alignment: .leading) {
            if selected { Capsule().fill(runway.agent).frame(width: 3).padding(.vertical, 8) }
        }
        .onHover { hoveredSessionID = $0 ? session.id : nil }
        .onAppear { visibleRowIDs.insert(session.id) }
        .onDisappear { visibleRowIDs.remove(session.id) }
        .contextMenu {
            if session.status == "active" { Button("归档", systemImage: "archivebox") { archive(session) } }
            else { Button("恢复", systemImage: "arrow.uturn.backward") { restore(session) } }
            Button("编辑标签", systemImage: "tag") { editingSessionID = session.id }
            Button(session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", systemImage: "brain") {
                if !LearningMemory.setAllowed(!session.memoryUseAllowed, session: session, context: modelContext) { batchError = "记忆设置未保存，请重试。" }
            }
            Button("选择此会话", systemImage: "checkmark.circle") { multiSelect = true; selectedIDs.insert(session.id) }
        }
        .accessibilityLabel("\(session.title)，\(state.label)，\(LearningWorkspace.modeLabel(session.modePreset))")
    }

    private func sidebarRow(_ item: SidebarItem) -> some View {
        let selected = selection == item
        return Button { if item == .learning { selectedSessionID = nil }; selection = item } label: {
            HStack {
                Label(item.title, systemImage: item.systemImage)
                Spacer()
                if item == .inbox, inboxCount > 0 {
                    Text("\(inboxCount)").font(.caption.weight(.semibold))
                        .padding(.horizontal, 7).padding(.vertical, 2).background(runway.field, in: Capsule())
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .foregroundStyle(selected ? runway.ink : Color.secondary)
            .background(selected ? runway.field : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func createSession() {
        showArchived = false
        selectedSessionID = nil
        selection = .learning
    }

    private func selectAll() {
        let selecting = selectedIDs.count != visibleSessions.count
        selectionDelays = Dictionary(uniqueKeysWithValues: visibleSessions.filter { visibleRowIDs.contains($0.id) }.enumerated().map { ($0.element.id, min(Double($0.offset) * 0.012, 0.09)) })
        selectedIDs = selecting ? Set(visibleSessions.map(\.id)) : []
    }

    private func batchArchive() {
        var failed = Set<UUID>()
        var archived = Set<UUID>()
        for session in visibleSessions where selectedIDs.contains(session.id) {
            let saved = showArchived ? LearningSessionActions.restore(session, context: modelContext) : LearningSessionActions.archive(session, context: modelContext)
            if !saved { failed.insert(session.id) }
            else if !showArchived { archived.insert(session.id) }
        }
        undoBatchIDs = archived
        selectedIDs = failed
        batchError = failed.isEmpty ? nil : "\(failed.count) 个会话未保存，请重试。已成功的操作不会重复执行。"
        if failed.isEmpty { multiSelect = false }
    }

    private func archive(_ session: AgentSession) {
        if LearningSessionActions.archive(session, context: modelContext) { undoSessionID = session.id }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(6))
            if undoSessionID == session.id { undoSessionID = nil }
        }
    }

    private func restore(_ session: AgentSession) {
        if LearningSessionActions.restore(session, context: modelContext) {
            showArchived = false
            selectedSessionID = session.id
        }
    }

    private func sessionState(_ session: AgentSession) -> (symbol: String, label: String, problem: Bool) {
        guard session.status == "active" else { return ("archivebox", "已归档", false) }
        guard let run = runs.first(where: { $0.sessionID == session.id }) else { return ("circle", "尚未运行", false) }
        if ["retryable_failed", "terminal_failed"].contains(run.status) { return ("exclamationmark.triangle", "运行失败", true) }
        if ["interrupted", "cancelled"].contains(run.status) { return ("pause.circle", "已停止", false) }
        if ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) { return ("circle.dotted", "\(run.userSummary)", false) }
        if let task = tasks.first(where: { $0.sessionID == session.id }), task.status == "awaiting_user" {
            return ("bubble.left", task.requiredActionType == "submit_answer" ? "等待作答" : "可继续学习", false)
        }
        return ("checkmark.circle", "本轮已回应", false)
    }
}

struct ContentView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    var coordinator: ReviewCoordinator
    @State private var selection: SidebarItem?
    @State private var selectedKnowledgeID: UUID?
    @State private var selectedLearningSessionID: UUID?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @AppStorage("reviewToday.sidebarVisible") private var sidebarVisible = true
    @State private var automaticallyCollapsed = false
    @AppStorage("reviewToday.sidebarWidth") private var savedSidebarWidth = 280.0
    @State private var saveWidthTask: Task<Void, Never>?
    @State private var monitor = AgentServiceMonitor()
    @Query private var inbox: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var learningTasks: [LearningTask]
    @Query private var learningSessions: [AgentSession]

    init(coordinator: ReviewCoordinator) {
        self.coordinator = coordinator
#if DEBUG
        let fixtureEnabled = M1DebugFixture.enabled
        let fixtureSelection: SidebarItem = M1DebugFixture.mode == "learning" ? .learning : M1DebugFixture.mode == "today" ? .today : .library
        _selection = State(initialValue: fixtureEnabled ? fixtureSelection : .today)
        _selectedKnowledgeID = State(initialValue: fixtureEnabled ? M1DebugFixture.knowledgeID : nil)
#else
        _selection = State(initialValue: .today)
        _selectedKnowledgeID = State(initialValue: nil)
#endif
    }

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            AppSidebar(selection: $selection, selectedSessionID: $selectedLearningSessionID, inboxCount: inboxCount)
                .navigationSplitViewColumnWidth(min: 220, ideal: min(340, max(220, savedSidebarWidth)), max: 340)
                .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width in
                    guard (220...340).contains(width), abs(savedSidebarWidth - width) > 1 else { return }
                    saveWidthTask?.cancel()
                    saveWidthTask = Task {
                        try? await Task.sleep(for: .milliseconds(250))
                        if !Task.isCancelled { savedSidebarWidth = width }
                    }
                }
        } detail: {
            Group {
                switch selection ?? .today {
                case .today:
                    TodayView(
                        coordinator: coordinator,
                        onOpenKnowledge: { id in
                            selectedKnowledgeID = id
                            selection = .library
                        },
                        onOpenInbox: { selection = .inbox },
                        onOpenLibrary: { selection = .library },
                        onOpenLearning: { id in
                            selectedLearningSessionID = id
                            selection = .learning
                        }
                    )
                case .learning:
                    LearningWorkspace(
                        monitor: monitor,
                        selectedSessionID: $selectedLearningSessionID,
                        onOpenKnowledge: { id in
                            selectedKnowledgeID = id
                            selection = .library
                        }
                    )
                case .library:
                    LibraryView(selectedID: $selectedKnowledgeID, coordinator: coordinator)
                case .inbox:
                    InboxView(onOpenSession: { id in selectedLearningSessionID = id; selection = .learning })
                }
            }
            .background(PaperSurface())
        }
        .navigationSplitViewStyle(.balanced)
        .frame(minWidth: 760, minHeight: 620)
        .onChange(of: columnVisibility) { _, value in
            if value != .detailOnly { automaticallyCollapsed = false }
            if !automaticallyCollapsed { sidebarVisible = value != .detailOnly }
        }
        .onGeometryChange(for: Bool.self) { $0.size.width < 900 } action: { narrow in
            if narrow && columnVisibility != .detailOnly {
                automaticallyCollapsed = true
                columnVisibility = .detailOnly
            } else if !narrow && automaticallyCollapsed {
                automaticallyCollapsed = false
                columnVisibility = sidebarVisible ? .all : .detailOnly
            }
        }
        .task {
#if DEBUG
            if M1DebugFixture.enabled { monitor.useFixturePresentation(); return }
#endif
            await ConversationSync().run(context: modelContext, monitor: monitor)
        }
        .task {
#if DEBUG
            if M1DebugFixture.enabled { monitor.useFixturePresentation(); return }
#endif
            monitor.start()
            ReminderNotifications.request()
            while !Task.isCancelled {
                await HarnessProcessor.tick(context: modelContext, monitor: monitor)
                await CaptureProcessor.tick(context: modelContext, monitor: monitor)
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .onDisappear {
            monitor.stop()
        }
        .onAppear {
            columnVisibility = sidebarVisible ? .all : .detailOnly
#if DEBUG
            if M1DebugFixture.enabled {
                if M1DebugFixture.mode == "review" {
                    coordinator.startPreview(
                        knowledgeID: M1DebugFixture.knowledgeID,
                        questionID: M1DebugFixture.questionID
                    )
                    openWindow(id: "review")
                } else if M1DebugFixture.mode == "retry" {
                    coordinator.startFormal(knowledgeIDs: [M1DebugFixture.knowledgeID])
                    openWindow(id: "review")
                } else {
                    Task { @MainActor in
                        try? await Task.sleep(for: .milliseconds(600))
                        dismissWindow(id: "review")
                    }
                }
            }
#endif
            UNUserNotificationCenter.current().delegate = NotificationRelay.shared
            NotificationRelay.shared.onStart = { startDueReview() }
            NotificationRelay.shared.onSnooze = { minutes in
                handleSnooze(minutes)
            }
            NotificationRelay.shared.onSkip = { skipToday() }
        }
    }

    private var inboxCount: Int {
        inbox.filter { $0.status == "needs_attention" || $0.status == "retryable_failed" }.count +
        learningTasks.filter { LearningDecisionInbox.includes($0, sessions: learningSessions) }.count
    }

    private func startDueReview() {
        let developer = settingsRows.first?.developerMode == true
        let due = knowledge.filter { ReviewQueue.isDue($0, developerMode: developer) }
        guard !due.isEmpty else { return }
        coordinator.startFormal(knowledgeIDs: due.map(\.id))
        openWindow(id: "review")
    }

    private func handleSnooze(_ minutes: Int) {
        guard let settings = settingsRows.first else { return }
        let key = TodayView.todayStamp()
        if settings.snoozeDay != key {
            settings.snoozeDay = key
            settings.snoozeCount = 0
        }
        guard settings.snoozeCount < 2 else { return }
        settings.snoozeCount += 1
        ReminderNotifications.snooze(minutes: minutes)
        try? modelContext.save()
    }

    private func skipToday() {
        settingsRows.first?.skipToday = TodayView.todayStamp()
        try? modelContext.save()
    }
}

final class NotificationRelay: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationRelay()
    var onStart: (() -> Void)?
    var onSnooze: ((Int) -> Void)?
    var onSkip: (() -> Void)?

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        switch response.actionIdentifier {
        case "start", UNNotificationDefaultActionIdentifier:
            onStart?()
        case "later15":
            onSnooze?(15)
        case "later60":
            onSnooze?(60)
        case "skip":
            onSkip?()
        default:
            break
        }
        completionHandler()
    }
}

#Preview {
    ContentView(coordinator: ReviewCoordinator())
        .runwayAppearance()
        .modelContainer(
            for: [
                Source.self,
                Knowledge.self,
                Question.self,
                CaptureTask.self,
                AppSettings.self,
                FsrsState.self,
                ReviewSession.self,
                ReviewAttempt.self,
                AgentSession.self,
                AgentMessage.self,
                LearningTask.self,
                TaskEventRecord.self,
                SourceReference.self,
                KnowledgeReference.self,
                SessionSummaryRecord.self,
                AgentRun.self,
                AgentRunControl.self,
                SessionEventRecord.self,
            ],
            inMemory: true
        )
}
