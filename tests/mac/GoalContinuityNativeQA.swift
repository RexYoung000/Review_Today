import AppKit
import SwiftUI
import SwiftData
import ScreenCaptureKit

/// Actual production workspace, isolated durable state; synthetic learning records.
@main struct GoalContinuityNativeQA: App {
    let container: ModelContainer
    let origin: AgentSession
    let destination: AgentSession
    init() {
        let directory = "/tmp/review-today-goal-native-" + UUID().uuidString
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", directory, 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "18742", 1)
        unsetenv("REVIEW_TODAY_M1_UI_FIXTURE")
        try! FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true)
        container = try! ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: URL(fileURLWithPath: directory + "/test.store")))
        let context = container.mainContext
        origin = AgentSession(title: "RAG 基础 · 历史会话"); destination = AgentSession(title: "继续 RAG · 当前进度")
        context.insert(origin); context.insert(destination)
        let oldMessage = AgentMessage(sessionID: origin.id, role: "coach", content: "第一步：资料切分与建立索引。把资料切成可检索的小段，保留原始来源。", deliveryStatus: "accepted")
        let newMessage = AgentMessage(sessionID: destination.id, role: "coach", content: "接着上次的「理解 RAG」继续。上次进度：资料切分与建立索引。\n\n第二步：检索与重排\n\n先召回可能相关的资料，再比较它们是否能回答当前问题。\n\n（隔离验证的合成学习记录。）", deliveryStatus: "accepted")
        context.insert(oldMessage); context.insert(newMessage)
        let first = LearningTask(sessionID: origin.id, inputMessageID: oldMessage.id, status: "awaiting_user")
        let next = LearningTask(sessionID: destination.id, inputMessageID: newMessage.id, status: "awaiting_user")
        let steps: [[String: Any]] = [
            ["id":"one","title":"资料切分与建立索引","state":"explained","understanding":"unknown","message_ids":[oldMessage.id.uuidString.lowercased()],"message_sessions":[oldMessage.id.uuidString.lowercased():origin.id.uuidString.lowercased()]],
            ["id":"two","title":"检索与重排","state":"explained","understanding":"unknown","message_ids":[newMessage.id.uuidString.lowercased()]],
            ["id":"three","title":"基于证据生成答案","state":"pending","understanding":"unknown","message_ids":[]]]
        var oldSteps = steps
        oldSteps[1]["state"] = "pending"; oldSteps[1]["message_ids"] = [] as [String]
        first.learningPlanJSON = ConversationProcessor.json(["goal":"理解 RAG","steps":oldSteps,"current_step_id":"one"])
        next.learningPlanJSON = ConversationProcessor.json(["goal":"理解 RAG","steps":steps,"current_step_id":"two"])
        let value: [String: Any] = ["goal_id":first.id.uuidString.lowercased(),"owner_task_id":next.id.uuidString.lowercased(),"owner_session_id":destination.id.uuidString.lowercased(),"version":2]
        next.goalOwnershipJSON = ConversationProcessor.json(value)
        context.insert(first); context.insert(next)
        try! LearningGoalContinuity.apply([value], context: context)
        origin.learningChecklistExpanded = true; destination.learningChecklistExpanded = true
        try! context.save()
    }
    var body: some Scene {
        WindowGroup { GoalQARoot(origin: origin, destination: destination).modelContainer(container).runwayAppearance() }
            .defaultSize(width: 1040, height: 820)
    }
}
struct GoalQARoot: View {
    let origin: AgentSession
    let destination: AgentSession
    @State private var selected: UUID?
    @State private var monitor = AgentServiceMonitor()
    @State private var dark = false
    @State private var reduced = false
    var body: some View {
        VStack(spacing: 0) {
            Text("隔离验证 · 合成学习记录 · 正式对话界面 · 不访问日常数据").font(.caption).foregroundStyle(.secondary).padding(6)
            HStack {
                Button("历史会话") { selected = origin.id }
                Button("当前进度") { selected = destination.id }
                Toggle("深色", isOn: $dark)
                Toggle("减少动态", isOn: $reduced)
                Button("窄窗") { NSApp.keyWindow?.setContentSize(NSSize(width: 720,height: 680)) }
                Button("截图") { snapshot() }
            }.controlSize(.small).padding(8)
            LearningWorkspace(monitor: monitor, selectedSessionID: $selected, onOpenKnowledge: { _ in }).id(selected)
        }.frame(minWidth: 700,minHeight: 600).preferredColorScheme(dark ? .dark : .light).environment(\.brandTrialStill,reduced)
            .onAppear { selected = origin.id; monitor.useFixturePresentation() }
            .onChange(of: dark) { _, value in AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true) }
    }
    func snapshot() {
        Task { @MainActor in
            do {
                guard let window = NSApp.keyWindow else { return }
                let content = try await SCShareableContent.currentProcess
                guard let target = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else { return }
                let config = SCStreamConfiguration(); config.width = Int(window.frame.width); config.height = Int(window.frame.height)
                config.ignoreShadowsSingleWindow = true
                let image = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: target), configuration: config)
                let root = Bundle.main.object(forInfoDictionaryKey: "QAProjectRoot") as! String
                let name = selected == origin.id ? "native-history" : "native-current"
                let suffix = dark ? "-dark-narrow" : "-light"
                let path = URL(fileURLWithPath: root).appendingPathComponent("docs/evidence/2026-09-17-dialogue-continuation/\(name)\(suffix).png")
                try NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!.write(to:path)
                print("QA snapshot: \(path.path)");fflush(stdout)
            } catch { print("QA screenshot failed: \(error)") }
        }
    }
}
