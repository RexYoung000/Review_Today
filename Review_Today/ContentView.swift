import SwiftData
import SwiftUI
import UserNotifications
import Combine

struct ContentView: View {
    @Environment(\.brandMaterialPreview) private var materialPreview
    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    var coordinator: ReviewCoordinator
    @State private var captureDestination: UUID?
    @State private var selection: SidebarItem?
    @State private var learningFocusRequest = 0
    @State private var searchPresented = false
    @State private var creationError: String?
    @State private var draftEntrance = true
    @Environment(\.brandReduceMotion) private var reduceMotion
    @State private var selectedKnowledgeID: UUID?
    @State private var selectedLearningSessionID: UUID?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @AppStorage("reviewToday.sidebarVisible") private var sidebarVisible = true
    @State private var sidebarPolicy = SidebarVisibilityPolicy()
    @State private var sidebarScrollAnchor: UUID?
    @AppStorage("reviewToday.sidebarWidth") private var savedSidebarWidth = 280.0
    @State private var sidebarResizeStart: Double?
    @State private var draftStore = LearningDraftStore()
    @State private var activityCache = TodayActivityCache()
    @State private var monitor = AgentServiceMonitor()
    @Query private var inbox: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var learningTasks: [LearningTask]
    @Query private var learningSessions: [AgentSession]

    init(coordinator: ReviewCoordinator) {
        self.coordinator = coordinator
#if PERFORMANCE_QA
        _selection = State(initialValue: .learning)
        _selectedKnowledgeID = State(initialValue: nil)
#elseif DEBUG
        let fixtureEnabled = M1DebugFixture.enabled
        let fixtureSelection: SidebarItem = M1DebugFixture.mode == "learning" ? .learning : M1DebugFixture.mode == "today" ? .today : .library
        _selection = State(initialValue: fixtureEnabled ? fixtureSelection : .today)
        _selectedKnowledgeID = State(initialValue: fixtureEnabled ? M1DebugFixture.knowledgeID : nil)
#else
        _selection = State(initialValue: .today)
        _selectedKnowledgeID = State(initialValue: nil)
#endif
    }

    private var navigationSelection: Binding<SidebarItem?> {
        Binding(get: { selection }, set: { next in
            if next != selection { NavigationPerformance.begin(next?.rawValue ?? "today") }
            selection = next
        })
    }

    var body: some View {
        HStack(spacing: 0) {
            if columnVisibility != .detailOnly {
                AppSidebar(selection: navigationSelection, selectedSessionID: $selectedLearningSessionID,
                           scrollAnchor: $sidebarScrollAnchor, onCollapse: { setSidebar(expanded: false) }, onStartLearning: startLearning, onSearch: { searchPresented = true }, inboxCount: inboxCount)
                    .navigationPaintProbe(selection?.rawValue ?? "today", stage: "feedback")
                    .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
                    .padding(8)
                    .frame(width: min(340, max(250, savedSidebarWidth)))
                Color.clear.frame(width: 6).contentShape(Rectangle())
                    .onHover { hovering in
                        if hovering { NSCursor.resizeLeftRight.push() } else { NSCursor.pop() }
                    }
                    .gesture(DragGesture().onChanged { value in
                        if sidebarResizeStart == nil { sidebarResizeStart = min(340, max(250, savedSidebarWidth)) }
                        savedSidebarWidth = min(340, max(250, (sidebarResizeStart ?? 280) + value.translation.width))
                    }.onEnded { _ in sidebarResizeStart = nil })
                    .accessibilityLabel("侧栏宽度")
                    .accessibilityValue("\(Int(min(340, max(250, savedSidebarWidth))))")
                    .accessibilityAdjustableAction { direction in
                        savedSidebarWidth = min(340, max(250, min(340, max(250, savedSidebarWidth)) + (direction == .increment ? 20 : -20)))
                    }
            } else {
                SidebarIconRail(selection: navigationSelection, selectedSessionID: $selectedLearningSessionID,
                                onExpand: { setSidebar(expanded: true) },
                                onSessions: { setSidebar(expanded: true) }, onNewSession: { setSidebar(expanded: true); startLearning() }, inboxCount: inboxCount)
                    .navigationPaintProbe(selection?.rawValue ?? "today", stage: "feedback")
                    .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous)).padding(8)
            }
            ZStack { detailContent }
                .navigationPaintProbe(selection?.rawValue ?? "today", stage: "page")
                .overlay(PageArrivalFade(page: selection ?? .today).allowsHitTesting(false).accessibilityHidden(true))
                .modifier(PageArrivalLift(page: selection ?? .today))
                .opacity(selection == .learning && !draftEntrance ? 0 : 1)
                .offset(y: selection == .learning && !draftEntrance ? 8 : 0)
                .padding(.top, 20).frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(PaperSurface())
        .background(ReviewMaintenance())
        .background(TodayActivitySource(cache: activityCache))
#if PERFORMANCE_QA
        .onReceive(NotificationCenter.default.publisher(for: NavigationPerformance.navigate)) { note in
            guard let raw = note.object as? String, let next = SidebarItem(rawValue: raw) else { return }
            if next == .learning { selectedLearningSessionID = nil }
            navigationSelection.wrappedValue = next
        }
#endif
        .accessibilityHidden(searchPresented)
        .overlay {
            if searchPresented {
                SessionSearchOverlay(onOpen: { session in
                    selectedLearningSessionID = session.id; selection = .learning; searchPresented = false
                }, onClose: {
                    searchPresented = false
                    NotificationCenter.default.post(name: .sessionSearchClosed, object: nil)
                })
            }
        }
        .background(ConversationWindowTarget { id in
            selectedLearningSessionID = id; selection = .learning; searchPresented = false
        })
        .onReceive(NotificationCenter.default.publisher(for: .dictationSessionsDeleted)) { note in
            if let ids = note.object as? Set<UUID> { draftStore.discard(ids) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .localDataDidReset)) { note in
            selectedKnowledgeID = nil
            if note.object as? LocalResetKind == .all {
                selectedLearningSessionID = nil; captureDestination = nil; draftEntrance = true
                selection = .today
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .reviewReturnToToday)) { _ in
            selection = .today
        }
        .toolbar(.hidden, for: .windowToolbar)
        .ignoresSafeArea(.container, edges: .top)
        .toolbar(removing: .sidebarToggle)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if AppRuntime.current.mode != .normal {
                Text(AppRuntime.current.isPerformanceQA ? "性能隔离验收 · 独立测试库，不连接模型" : AppRuntime.current.isPreview ? "界面预览 · 仅内存数据，不连接模型" : AppRuntime.current.isJevTest ? monitor.jevTestNotice : "真实模型隔离验收 · 独立数据，不写入日常知识库")
                    .font(.caption2).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity).padding(.vertical, 4)
                    .background(PaperSurface())
            }
        }
        .frame(minWidth: 760, minHeight: 620)
        .onGeometryChange(for: Bool.self) { $0.size.width < 900 } action: { narrow in
            sidebarPolicy.resize(narrow: narrow)
            columnVisibility = sidebarPolicy.expanded ? .all : .detailOnly
        }
        .task {
#if DEBUG || PERFORMANCE_QA
            if AppRuntime.current.isPreview { monitor.useFixturePresentation(); return }
#endif
            await ConversationSync().run(context: modelContext, monitor: monitor)
        }
        .task {
#if DEBUG || PERFORMANCE_QA
            if AppRuntime.current.isPreview { monitor.useFixturePresentation(); return }
#endif
            monitor.start()
            if AppRuntime.current.mode == .normal { ReminderNotifications.request() }
            while !Task.isCancelled {
                await HarnessProcessor.tick(context: modelContext, monitor: monitor)
                await CaptureProcessor.tick(context: modelContext, monitor: monitor)
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .alert("无法新建会话", isPresented: Binding(get: { creationError != nil }, set: { if !$0 { creationError = nil } })) {
            Button("好", role: .cancel) { creationError = nil }
        } message: { Text(creationError ?? "") }
        .onDisappear { monitor.stop() }
        .onAppear {
            do { try AgentComposerStore.preserveLandingDraft(context: modelContext) }
            catch { creationError = "原有草稿暂时无法保存为会话，请重试。" }
            sidebarPolicy.preferredExpanded = sidebarVisible
            columnVisibility = sidebarPolicy.expanded ? .all : .detailOnly
#if DEBUG
            if M1DebugFixture.enabled {
                if M1DebugFixture.mode == "review" {
                    coordinator.startPreview(knowledgeID: M1DebugFixture.knowledgeID, questionID: M1DebugFixture.questionID)
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
            NotificationRelay.shared.onSnooze = { minutes in handleSnooze(minutes) }
            NotificationRelay.shared.onSkip = { skipToday() }
        }
    }

    private func startLearning() {
        let alreadyLearning = selection == .learning
        NotificationCenter.default.post(name: .prepareNewConversation, object: nil)
        do {
            try AgentComposerStore.preserveLandingDraft(context: modelContext)
            let session = try AgentComposerStore.createSession(context: modelContext)
            selectedLearningSessionID = session.id
            sidebarScrollAnchor = session.id
            selection = .learning
            searchPresented = false
            learningFocusRequest += 1
            if !reduceMotion && alreadyLearning {
                draftEntrance = false
                Task { @MainActor in
                    await Task.yield()
                    withAnimation(.easeOut(duration: 0.18)) { draftEntrance = true }
                }
            }
        } catch { creationError = "新会话未保存，请重试。已有输入仍保留。" }
    }

    private func setSidebar(expanded: Bool) {
        sidebarPolicy.choose(expanded: expanded)
        sidebarVisible = expanded
        columnVisibility = sidebarPolicy.expanded ? .all : .detailOnly
    }

    private var detailContent: some View {
        Group {
                switch selection ?? .today {
                case .today:
                    TodayView(
                        activityCache: activityCache,
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
                        draftStore: draftStore,
                        monitor: monitor,
                        selectedSessionID: $selectedLearningSessionID,
                        captureDestination: captureDestination,
                        entryFocusRequest: learningFocusRequest,
                        onEntryFocusConsumed: { learningFocusRequest = 0 },
                        onNewSession: startLearning,
                        onOpenKnowledge: { id in
                            selectedKnowledgeID = id
                            selection = .library
                        }
                    )
                case .library:
                    LibraryView(selectedID: $selectedKnowledgeID, coordinator: coordinator, onStartLearning: startLearning)
                case .inbox:
                    InboxView(onOpenSession: { id in captureDestination = nil; selectedLearningSessionID = id; selection = .learning },
                              onOpenCapture: { session, offer in captureDestination = offer; selectedLearningSessionID = session; selection = .learning })
                }
            }
    }

    private var inboxCount: Int {
        inbox.filter { $0.status == "needs_attention" || $0.status == "retryable_failed" }.count +
        learningTasks.filter { LearningDecisionInbox.includes($0, sessions: learningSessions) }.count +
        learningSessions.filter { $0.status == "active" }.reduce(0) { $0 + TopicCaptureOffer.read($1.captureOffersJSON).filter(\.needsAttention).count }
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
                SessionFolder.self,
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
