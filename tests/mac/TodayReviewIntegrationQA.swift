import AppKit
import ScreenCaptureKit
import SwiftData
import SwiftUI

@main struct TodayReviewIntegrationQA: App {
    let container: ModelContainer
    @State private var coordinator = ReviewCoordinator()
    @State private var controller = ReviewController()
    @State private var dark = false
    @State private var reduced = false
    init() {
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "today", 1)
        unsetenv("REVIEW_TODAY_NATIVE_TEST_DIR"); unsetenv("REVIEW_TODAY_JEV_TEST")
        container = try! ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        context.insert(AppSettings())
        for index in 0..<4 {
            let titles = ["检索增强生成", "光合作用", "工作记忆", "HTTP 缓存"]
            let item = Knowledge(learningGoal: titles[index], knowledgeType: "concept", theme: titles[index], contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "合成标准", evidenceLocator: "独立 UI 验证")
            item.reviewEnrollment = "enrolled"; item.dueAt = Date(timeIntervalSince1970: Double(index))
            context.insert(item)
            let spec = AgentAPI.ScoringSpec(learningGoal: item.learningGoal, mustCover: ["独立要点"], acceptableParaphrases: [], commonMisconceptions: [], evidence: "合成标准", orderRules: "")
            let q = Question(variantIndex: 0, promptText: index == 0 ? "RAG 是怎样帮助模型回答问题的？" : "用自己的话解释「\(titles[index])」，再举一个你熟悉的例子。", scoringSpecJSON: try! ReviewLedger.encode(spec))
            q.knowledge = item; context.insert(q)
            let session = AgentSession(title: "理解\(titles[index])")
            session.updatedAt = .now.addingTimeInterval(-Double(index * 7200)); session.summaryText = "这次我们讨论了\(titles[index])的基本过程，以及它在实际情境中的用途。\n\n还可以从一个熟悉的例子出发，比较不同条件下会发生什么。"
            context.insert(session)
        }
        try! context.save()
    }
    var body: some Scene {
        WindowGroup("Review Today · 接入自测", id: "main") {
            VStack(spacing: 0) {
                controls
                ContentView(coordinator: coordinator)
            }.modelContainer(container).runwayAppearance().preferredColorScheme(dark ? .dark : .light)
                .environment(\.brandTrialStill, reduced)
                .task { configureJudge() }
        }.defaultSize(width: 1280, height: 820)
        Window("复习 · 接入自测", id: "review") {
            VStack(spacing: 0) { controls; ReviewView(coordinator: coordinator, controller: controller) }
                .modelContainer(container).runwayAppearance().preferredColorScheme(dark ? .dark : .light)
                .environment(\.brandTrialStill, reduced)
        }.defaultSize(width: 900, height: 820).windowResizability(.contentMinSize)
    }
    private var controls: some View {
        HStack {
            Text("接入自测 · 合成材料／受控判断／不采音／不调用模型").font(.caption2)
            Spacer()
            Toggle("深色", isOn: $dark).toggleStyle(.checkbox)
            Toggle("减少动态", isOn: $reduced).toggleStyle(.checkbox)
            Button("最小窗口") { NSApp.keyWindow?.setContentSize(NSSize(width: NSApp.keyWindow?.title.contains("复习") == true ? 700 : 760, height: 700)) }
            Button("默认窗口") { NSApp.keyWindow?.setContentSize(NSSize(width: NSApp.keyWindow?.title.contains("复习") == true ? 900 : 1280, height: 820)) }
            Button("截图") { Task { await snapshot() } }
        }.padding(8).controlSize(.small)
            .onChange(of: dark) { _, value in AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true) }
    }
    private func configureJudge() {
        // Voice fails before accessing audio hardware; the product recovery path is unchanged.
        controller.syncSession = { _ in throw ReviewFlowError.invalidResult }
        controller.confirmAttempt = { _, _ in }
        controller.requestTurn = { _, entry, _, text, action, eventID, _ in
            try await Task.sleep(for: .milliseconds(450))
            let intent = action == "hint" ? "hint" : action == "explain" ? "explain" : action == "clarify" ? "clarify" : text.contains("忘") ? "forgot" : "answer"
            let grade: String? = ["hint", "explain", "clarify"].contains(intent) ? nil : intent == "forgot" ? "again" : "good"
            let feedback = intent == "hint" ? "想想检索与生成之间传递的是什么。" : intent == "explain" ? "先检索相关资料，再让模型基于这些资料生成回答。你可以继续追问，也可以回顾下一题。" : intent == "forgot" ? "可以先想一想，也可以要一点提示。" : "这个思路说清楚了。"
            return (ReviewJudgment(intent: intent, grade: grade, feedback: feedback, coverage: [], misconceptions: [], clarificationRevealsAnswer: false, eventId: eventID, attemptId: entry.id, specVersion: entry.rubricVersion, model: "synthetic-ui", ruleVersion: "ui-1", durationMs: 450, actualCalls: 0, answerRevealed: false), "{}")
        }
    }
    private func snapshot() async {
        do {
            guard let window = NSApp.keyWindow else { return }
            let content = try await SCShareableContent.currentProcess
            guard let target = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else { return }
            let config = SCStreamConfiguration(); config.width = Int(window.frame.width * 2); config.height = Int(window.frame.height * 2); config.ignoreShadowsSingleWindow = true
            let image = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: target), configuration: config)
            let directory = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "QAEvidence") as! String)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let name = "\(Date.now.timeIntervalSince1970)-\(window.title.contains("复习") ? controller.phase : "today")-\(dark ? "dark" : "light").png"
            try NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!.write(to: directory.appendingPathComponent(name))
        } catch { print("Capture failed:", error) }
    }
}
