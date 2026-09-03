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

struct AppSidebar: View {
    @Binding var selection: SidebarItem?
    var inboxCount: Int
    @Environment(\.runway) private var runway

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                CoachMark(pose: .idle, size: 36)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Review\nToday")
                        .font(.headline)
                    Text(String(localized: "记忆教练"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                AnimatedThemeToggler()
            }
            .padding(.horizontal, 16)
            .padding(.top, 18)
            .padding(.bottom, 20)

            VStack(spacing: 4) {
                ForEach(SidebarItem.allCases) { item in
                    sidebarRow(item)
                }
            }
            .padding(.horizontal, 10)

            Spacer()

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
        .background {
            PaperSurface()
        }
    }

    private func sidebarRow(_ item: SidebarItem) -> some View {
        let selected = selection == item
        return Button {
            selection = item
        } label: {
            HStack {
                Label(item.title, systemImage: item.systemImage)
                Spacer()
                if item == .inbox, inboxCount > 0 {
                    Text("\(inboxCount)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(selected ? runway.ink : .secondary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(runway.field, in: Capsule())
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .foregroundStyle(selected ? runway.ink : Color.secondary)
            .background(selected ? runway.field : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct ContentView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    var coordinator: ReviewCoordinator
    @State private var selection: SidebarItem?
    @State private var selectedKnowledgeID: UUID?
    @State private var monitor = AgentServiceMonitor()
    @Query private var inbox: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]

    init(coordinator: ReviewCoordinator) {
        self.coordinator = coordinator
#if DEBUG
        let fixtureEnabled = M1DebugFixture.enabled
        _selection = State(initialValue: fixtureEnabled ? .library : .today)
        _selectedKnowledgeID = State(initialValue: fixtureEnabled ? M1DebugFixture.knowledgeID : nil)
#else
        _selection = State(initialValue: .today)
        _selectedKnowledgeID = State(initialValue: nil)
#endif
    }

    var body: some View {
        NavigationSplitView {
            AppSidebar(selection: $selection, inboxCount: inboxCount)
                .navigationSplitViewColumnWidth(min: 200, ideal: Runway.sidebarIdeal, max: 240)
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
                        onOpenLearning: { selection = .learning }
                    )
                case .learning:
                    LearningWorkspace(
                        monitor: monitor,
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
        .frame(minWidth: 980, minHeight: 680)
        .task {
            monitor.start()
            ReminderNotifications.request()
            while !Task.isCancelled {
                await ConversationProcessor.tick(context: modelContext, monitor: monitor)
                await HarnessProcessor.tick(context: modelContext, monitor: monitor)
                await CaptureProcessor.tick(context: modelContext, monitor: monitor)
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .onDisappear {
            monitor.stop()
        }
        .onAppear {
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
            ],
            inMemory: true
        )
}
