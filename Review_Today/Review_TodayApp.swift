import AppKit
import SwiftData
import SwiftUI

@main
struct Review_TodayApp: App {
    let container: ModelContainer
    @State private var coordinator = ReviewCoordinator()

    init() {
        do {
#if DEBUG
            if let directory = AppRuntime.current.validationDirectory {
                container = try M1DebugFixture.makeValidationContainer(directory)
                return
            }
            if M1DebugFixture.enabled {
                container = try M1DebugFixture.makeContainer()
                return
            }
#endif
            try ReviewMigration.backupIfNeeded(ModelConfiguration().url)
            container = try ModelContainer(
                for: Source.self,
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
                SessionEventRecord.self
            )
        } catch {
            fatalError("SwiftData container failed: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup("Review Today", id: "main") {
            ContentView(coordinator: coordinator)
                .environment(\.knowledgePaper, true)
                .runwayAppearance()
        }
        .modelContainer(container)
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1280, height: 820)
        .windowResizability(.contentMinSize)

        Window(String(localized: "复习"), id: "review") {
            ReviewView(coordinator: coordinator)
                .modelContainer(container)
                .runwayAppearance()
        }
        .defaultSize(width: 900, height: 820)
        .windowResizability(.contentMinSize)
        .restorationBehavior(.disabled)

#if DEBUG
        WindowGroup("已确认动效 · 原生验证", id: "mascot-motion-preview") {
            MascotMotionPreview().runwayAppearance()
        }
        .defaultSize(width: 760, height: 600)

        WindowGroup(String(localized: "吉祥物动画 POC"), id: "mascot-animation-poc") {
            MascotAnimationPOCView()
                .runwayAppearance()
        }
        .defaultSize(width: 920, height: 680)
#endif

        Settings {
            SettingsView()
                .runwayAppearance()
        }
        .modelContainer(container)

        MenuBarExtra(String(localized: "Review Today"), image: "BrandMenuMark") {
            MenuBarCapture()
                .modelContainer(container)
                .runwayAppearance()
        }
    }
}

private struct MenuBarCapture: View {
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \LearningTask.updatedAt, order: .reverse) private var tasks: [LearningTask]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(String(localized: "学习进度"))
                .font(.headline)
            Divider()
            if let latest = tasks.first(where: { $0.status != "cancelled" }),
               let session = sessions.first(where: { $0.id == latest.sessionID }) {
                Text(session.title)
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                Text(latest.userSummary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else {
                Text(String(localized: "还没有学习 Session"))
                    .foregroundStyle(.secondary)
            }
            Button(String(localized: "打开主窗口")) {
                NSApp.activate(ignoringOtherApps: true)
                NSApp.windows.first(where: { $0.canBecomeMain })?.makeKeyAndOrderFront(nil)
            }
        }
        .padding(12)
        .frame(width: 280)
    }
}
