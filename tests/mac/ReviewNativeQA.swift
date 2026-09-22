import AppKit
import SwiftUI
import SwiftData
import ScreenCaptureKit

@main struct ReviewNativeQA: App {
    let container: ModelContainer
    init() {
        let directory = "/tmp/review-today-native-voice-" + UUID().uuidString
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", directory, 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "18865", 1)
        unsetenv("REVIEW_TODAY_M1_UI_FIXTURE")
        container = try! M1DebugFixture.makeValidationContainer(URL(fileURLWithPath: directory))
        let context = container.mainContext
        if (try! context.fetch(FetchDescriptor<Knowledge>())).isEmpty {
            for index in 0..<3 {
                let rag = index == 1
                let evidence = rag ? "RAG 先检索相关资料，再基于检索到的上下文生成回答。" : "植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。"
                let item = Knowledge(learningGoal: rag ? "解释 RAG 的基本过程" : "解释光合作用的原料与产物", knowledgeType: "concept", theme: rag ? "RAG" : "植物", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: evidence, evidenceLocator: "隔离合成资料")
                item.reviewEnrollment = "enrolled"; item.dueAt = Date(timeIntervalSince1970: Double(index))
                context.insert(item)
                let spec = AgentAPI.ScoringSpec(learningGoal: item.learningGoal, mustCover: rag ? ["检索相关资料", "依据检索结果生成回答"] : ["利用光能", "二氧化碳和水生成有机物并释放氧气"], acceptableParaphrases: [], commonMisconceptions: rag ? ["RAG 就是训练模型权重"] : ["以氧气作为主要原料"], evidence: evidence, orderRules: "")
                let q = Question(variantIndex: 0, promptText: rag ? "RAG 怎样帮助模型回答问题？" : "光合作用利用什么能量，原料和产物是什么？", scoringSpecJSON: try! ReviewLedger.encode(spec))
                q.knowledge = item; context.insert(q)
            }
            try! context.save()
        }
    }
    var body: some Scene {
        WindowGroup("复习流程 · 隔离验证") { ReviewQARoot().modelContainer(container).runwayAppearance() }
            .defaultSize(width: 850, height: 760)
    }
}

struct ReviewQARoot: View {
    @Environment(\.modelContext) var context
    @State var controller = ReviewController()
    @State var coordinator = ReviewCoordinator()
    @State var dark = false
    @State var note = "合成资料 · 独立数据库 · 使用真实评价模型"
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(note).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("自动文字验证") { Task { await check() } }
                Toggle("深色", isOn: $dark).toggleStyle(.checkbox)
                Button("窄窗") { NSApp.keyWindow?.setContentSize(NSSize(width: 660, height: 560)) }
                Button("截图") { Task { await snapshot() } }
            }.padding(8).controlSize(.small)
            ReviewView(coordinator: coordinator, controller: controller)
        }.preferredColorScheme(dark ? .dark : .light)
            .onChange(of: dark) { _, value in AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true) }
    }
    func check() async {
        func submit(_ text: String, action: String = "utterance") async throws {
            controller.submit(text, action: action)
            for _ in 0..<600 where controller.busy { try await Task.sleep(for: .milliseconds(100)) }
            if controller.busy || controller.errorText != nil { throw ReviewFlowError.invalidResult }
        }
        func require(_ value: Bool) throws { if !value { throw ReviewFlowError.invalidResult } }
        do {
            controller.start(usingVoice: false)
            let sid = controller.session!.id
            try await submit("植物利用光能。")
            try require(controller.phase == "help")
            try await submit("请给一点提示。", action: "hint")
            try await submit("植物利用光能，把二氧化碳和水转化为有机物，释放氧气。")
            try require(controller.completed.first?.effectiveGrade == "again")
            let queue = controller.entries.map(\.attemptID)
            controller.pause(); controller.configure(context, coordinator: coordinator)
            controller.start(usingVoice: false, resume: true)
            try require(controller.entries.map(\.attemptID) == queue && controller.session!.id == sid)
            controller.skipOrContinue()
            try await submit("利用太阳光，将二氧化碳和水变成糖类，并放出氧气。")
            try require(controller.phase == "summary" && controller.completed.count == 2 && controller.skipped == 1)
            let first = controller.entries.first!
            controller.beginCorrection(first)
            try await submit("植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。")
            let row = controller.completed.first { $0.attemptId == first.attemptID }!
            let state = try context.fetch(FetchDescriptor<FsrsState>()).first { $0.knowledgeId == first.knowledgeID }!
            try require(row.correctionRevision == 1 && state.reps == 1 && row.effectiveGrade == "good")
            try context.save()
            let result: [String: Any] = ["session_id": sid.uuidString, "completed": controller.completed.count, "skipped": controller.skipped, "assisted": controller.assisted, "corrected_reps": state.reps, "correction_revision": row.correctionRevision, "passed": true]
            let root = Bundle.main.object(forInfoDictionaryKey: "QAProjectRoot") as! String
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted,.sortedKeys]).write(to: URL(fileURLWithPath: root+"/docs/evidence/2026-09-23-review-voice/native-real-result.json"))
            note = "真实文字闭环通过 · 保存 2 · 跳过 1 · 纠正只重算一次"
            await snapshot()
        } catch { note = "验证失败：" + error.localizedDescription; print(note) }
    }
    func snapshot() async {
        do {
            guard let window = NSApp.keyWindow ?? NSApp.windows.first(where: { $0.title == "复习流程 · 隔离验证" }) else { return }
            let content = try await SCShareableContent.currentProcess
            guard let target = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else { return }
            let config = SCStreamConfiguration(); config.width = Int(window.frame.width); config.height = Int(window.frame.height); config.ignoreShadowsSingleWindow = true
            let image = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: target), configuration: config)
            let root = Bundle.main.object(forInfoDictionaryKey: "QAProjectRoot") as! String
            let name = "native-\(controller.phase)-\(dark ? "dark" : "light")-\(Int(window.frame.width)).png"
            try NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: root+"/docs/evidence/2026-09-23-review-voice/"+name))
        } catch { print("Screenshot failure: \(error)") }
    }
}
