import AppKit
import SwiftData
import SwiftUI

struct GlassMaterialPreviewRoot: View {
    @Bindable private var appearance = AppearanceController.shared
    @State private var coordinator = ReviewCoordinator()
    @State private var solidSurfaces = false
    @State private var stillMotion = false
    @State private var compareOriginal = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                Text("玻璃材质小样").font(.callout.weight(.semibold))
                Spacer(minLength: 8)
                Toggle("对照原版", isOn: $compareOriginal)
                Toggle("减少透明度", isOn: $solidSurfaces)
                Toggle("减少动态效果", isOn: $stillMotion)
            }
            .toggleStyle(.checkbox).font(.caption).padding(.horizontal, 18).padding(.vertical, 10)
            .background(appearance.isDark ? Color(white: 0.105) : Color(white: 0.98))
            Divider()
            ContentView(coordinator: coordinator)
                .environment(\.glassPreview, !compareOriginal)
                .environment(\.runway, compareOriginal ? appearance.colors : .glassPreview(dark: appearance.isDark))
                .environment(\.glassPreviewReduceTransparency, solidSurfaces)
                .environment(\.glassPreviewReduceMotion, stillMotion)
        }
        .environment(appearance)
        .preferredColorScheme(appearance.isDark ? .dark : .light)
        .onAppear { appearance.applyAppKit() }
    }
}

@main
struct GlassMaterialPreviewApp: App {
    private let container: ModelContainer

    init() {
        // This executable always selects a memory fixture before consulting AppRuntime.
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "learning", 1)
        unsetenv("REVIEW_TODAY_NATIVE_TEST_DIR")
        precondition(Bundle.main.bundleIdentifier == "Rex.Review-Today.GlassPreview")
        precondition(AppRuntime.current.isPreview && !AppRuntime.current.allowsSending)
        do {
            container = try M1DebugFixture.makeContainer(mode: "learning")
            let sessions = try container.mainContext.fetch(FetchDescriptor<AgentSession>())
            if let lesson = sessions.first(where: { $0.title.contains("讲解中") }) {
                let id = lesson.id
                let messages = try container.mainContext.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == id }))
                messages.first(where: { $0.role == "assistant" })?.content = AnswerReadabilitySamples.lesson
                lesson.title = "RAG：理解检索与生成的边界"
                try container.mainContext.save()
            }
        } catch { fatalError("Cannot create isolated glass preview: \(error)") }
    }

    var body: some Scene {
        WindowGroup("Review Today · 玻璃材质小样") {
            GlassMaterialPreviewRoot().modelContainer(container)
        }
        .defaultSize(width: 1280, height: 820)
        .windowResizability(.contentMinSize)
        .commands {
            CommandMenu("小样") {
                Button("默认窗口 1280 × 820") { GlassPreviewWindow.resize(1280, 820) }
                    .keyboardShortcut("1", modifiers: [.command, .option])
                Button("最小窗口 760 × 660") { GlassPreviewWindow.resize(760, 660) }
                    .keyboardShortcut("2", modifiers: [.command, .option])
                Button("宽窗口 1440 × 900") { GlassPreviewWindow.resize(1440, 900) }
                    .keyboardShortcut("3", modifiers: [.command, .option])
            }
        }
    }
}

@MainActor
private enum GlassPreviewWindow {
    // Accessibility-triggered buttons can run while this app has no key window.
    private static var previewWindow: NSWindow? {
        NSApp.keyWindow ?? NSApp.windows.first { $0.isVisible && $0.contentView != nil && $0.canBecomeKey }
    }

    static func resize(_ width: CGFloat, _ height: CGFloat) {
        guard let window = previewWindow else { return }
        window.setContentSize(NSSize(width: width, height: height))
        window.center()
    }

}
