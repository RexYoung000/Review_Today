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
            if M1DebugFixture.enabled {
                container = try M1DebugFixture.makeContainer()
                return
            }
#endif
            container = try ModelContainer(
                for: Source.self,
                Knowledge.self,
                Question.self,
                CaptureTask.self,
                AppSettings.self,
                FsrsState.self,
                ReviewSession.self,
                ReviewAttempt.self
            )
        } catch {
            fatalError("SwiftData container failed: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView(coordinator: coordinator)
                .runwayAppearance()
        }
        .modelContainer(container)

        WindowGroup(String(localized: "复习"), id: "review") {
            ReviewView(coordinator: coordinator)
                .modelContainer(container)
                .runwayAppearance()
        }
        .restorationBehavior(.disabled)

#if DEBUG
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

        MenuBarExtra(String(localized: "Review Today"), systemImage: "sun.max") {
            MenuBarCapture()
                .modelContainer(container)
                .runwayAppearance()
        }
    }
}

private struct MenuBarCapture: View {
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \CaptureTask.updatedAt, order: .reverse) private var tasks: [CaptureTask]
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(String(localized: "记住点什么"))
                .font(.headline)
            TextField(String(localized: "输入文字或粘贴链接……"), text: $text)
            Button(String(localized: "记住")) {
                let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !value.isEmpty else { return }
                let url = TodayView.firstURL(in: value)
                let source = Source(inputType: url == nil ? "text" : "url", rawText: value, url: url)
                let task = CaptureTask()
                task.source = source
                CaptureProcessor.appendStatus(task.userStatus, to: task)
                modelContext.insert(source)
                modelContext.insert(task)
                try? modelContext.save()
                text = ""
            }
            .keyboardShortcut(.return)
            Divider()
            if let latest = tasks.first(where: { $0.status != "cancelled" }) {
                Text(latest.userStatus)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else {
                Text(String(localized: "还没有采集"))
                    .foregroundStyle(.secondary)
            }
            Button(String(localized: "打开主窗口")) {
                NSApp.activate(ignoringOtherApps: true)
            }
        }
        .padding(12)
        .frame(width: 280)
    }
}
