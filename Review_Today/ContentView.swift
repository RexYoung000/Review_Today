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
        case .learning: String(localized: "学习")
        case .library: String(localized: "知识库")
        case .inbox: String(localized: "待处理")
        }
    }

    var systemImage: String {
        switch self {
        case .today: "sun.max"
        case .learning: "bubble.left.and.bubble.right"
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
        if let run = runs.filter({ ["running", "accepted", "queued", "adjusting"].contains($0.status) })
            .max(by: { $0.updatedAt < $1.updatedAt }) {
            guard ConversationProcessor.queueControl(run, action: "stop", context: context) else { return false }
        }
        session.status = "archived"
        session.archivedAt = .now
        session.updatedAt = .now
        do { try context.save(); return true }
        catch { context.rollback(); return false }
    }

    @discardableResult
    static func restore(_ session: AgentSession, context: ModelContext) -> Bool {
        session.status = "active"
        session.archivedAt = nil
        session.updatedAt = .now
        do { try context.save(); return true }
        catch { context.rollback(); return false }
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
    @State private var searchText = ""
    @State private var showArchived = false
    @State private var hoveredSessionID: UUID?
    @State private var editingSessionID: UUID?
    @State private var undoSessionID: UUID?

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

            if selection == .learning {
                Divider().padding(.vertical, 12)
                sessionNavigation
            } else {
                Spacer(minLength: 12)
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
                Text("学习会话").font(.subheadline.weight(.semibold))
                Spacer()
                Button(action: createSession) { Image(systemName: "plus") }
                    .buttonStyle(.plain).help("新建学习会话")
            }
            .padding(.horizontal, 14)

            TextField("搜索会话", text: $searchText)
                .textFieldStyle(.roundedBorder)
                .padding(.horizontal, 10)

            Picker("会话状态", selection: $showArchived) {
                Text("进行中").tag(false)
                Text("已归档").tag(true)
            }
            .pickerStyle(.segmented).labelsHidden()
            .padding(.horizontal, 10)

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
        }
        .frame(maxHeight: .infinity)
    }

    private func sessionRow(_ session: AgentSession) -> some View {
        let selected = selectedSessionID == session.id
        let state = sessionState(session)
        return HStack(spacing: 4) {
            Button {
                selectedSessionID = session.id
                selection = .learning
            } label: {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: state.symbol)
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
        .contextMenu {
            if session.status == "active" { Button("归档", systemImage: "archivebox") { archive(session) } }
            else { Button("恢复", systemImage: "arrow.uturn.backward") { restore(session) } }
            Button("编辑标签", systemImage: "tag") { editingSessionID = session.id }
        }
        .accessibilityLabel("\(session.title)，\(state.label)，\(LearningWorkspace.modeLabel(session.modePreset))")
    }

    private func sidebarRow(_ item: SidebarItem) -> some View {
        let selected = selection == item
        return Button { selection = item } label: {
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
        let session = AgentSession()
        modelContext.insert(session)
        try? modelContext.save()
        showArchived = false
        selectedSessionID = session.id
        selection = .learning
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
        if ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) { return ("circle.dotted", "\(run.userSummary)", false) }
        return ("checkmark.circle", "已完成", false)
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
    @State private var monitor = AgentServiceMonitor()
    @Query private var inbox: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]

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
                .navigationSplitViewColumnWidth(min: 220, ideal: 280, max: 340)
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
                    InboxView()
                }
            }
            .background(PaperSurface())
        }
        .navigationSplitViewStyle(.balanced)
        .frame(minWidth: 760, minHeight: 620)
        .onChange(of: columnVisibility) { _, value in sidebarVisible = value != .detailOnly }
        .task { await ConversationSync().run(context: modelContext, monitor: monitor) }
        .task {
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
        inbox.filter { $0.status == "needs_attention" || $0.status == "retryable_failed" }.count
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
