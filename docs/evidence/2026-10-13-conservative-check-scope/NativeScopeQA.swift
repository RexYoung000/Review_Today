import AppKit
import SwiftUI
import SwiftData

/// Production conversation UI with a synthetic service session and private store.
@main struct NativeScopeQA: App {
    let container: ModelContainer
    let session: AgentSession

    init() {
        let directory = URL(fileURLWithPath: ProcessInfo.processInfo.environment["REVIEW_TODAY_NATIVE_TEST_DIR"]!)
        precondition(AppRuntime.current.mode == .modelValidation)
        container = try! M1DebugFixture.makeValidationContainer(directory)
        let context = container.mainContext
        let page = try! JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("bootstrap.json"))) as! [String: Any]
        let id = UUID(uuidString: page["session_id"] as! String)!
        let existing = (try! context.fetch(FetchDescriptor<AgentSession>())).first(where: { $0.id == id })
        session = existing
            ?? AgentSession(id: id, title: "本节综合检查 · 隔离验证", modePreset: "source_learning")
        if existing == nil {
            context.insert(session)
            try! ConversationProcessor.persist(page, session: session, context: context)
        }
        session.learningChecklistExpanded = true
        try! context.save()
    }

    var body: some Scene {
        WindowGroup("综合检查 · 隔离验证") {
            ScopeQARoot(sessionID: session.id).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

struct ScopeQARoot: View {
    let sessionID: UUID
    @Environment(\.modelContext) private var modelContext
    @State private var selected: UUID?
    @State private var monitor = AgentServiceMonitor()
    @State private var dark = false
    @State private var reduced = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("隔离验证 · 合成讲义 · 真实入口与评分 · 不访问日常数据").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark)
                Toggle("减少动态", isOn: $reduced)
                Button("窄窗") { NSApp.keyWindow?.setContentSize(NSSize(width: 760, height: 700)) }
            }.controlSize(.small).padding(8)
            LearningWorkspace(monitor: monitor, selectedSessionID: $selected, onOpenKnowledge: { _ in })
        }.frame(minWidth: 700, minHeight: 620)
            .preferredColorScheme(dark ? .dark : .light)
            .environment(\.brandTrialStill, reduced)
            .onAppear { selected = sessionID; monitor.start() }
            .task { await ConversationSync().run(context: modelContext, monitor: monitor) }
            .onChange(of: dark) { _, value in
                AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true)
            }
    }
}
