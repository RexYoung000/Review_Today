import AppKit
import AVFoundation
import SwiftData
import ScreenCaptureKit
import SwiftUI

/// Runs the actual product views against an in-memory store. All exports are
/// from this preview's own view, never another app or the daily database.
@MainActor @Observable
final class LibrarySessionQA {
    var paper = true
    var reduced = false
    var recording = false
    var message = ""

    private var previewWindow: NSWindow? {
        NSApp.keyWindow ?? NSApp.windows.first { $0.isVisible && $0.canBecomeKey }
    }

    private var folder: URL {
        URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent("docs/evidence/2026-09-25-knowledge-paper")
    }

    func resize(_ width: CGFloat, _ height: CGFloat) {
        guard let window = previewWindow else { return }
        window.setContentSize(NSSize(width: width, height: height)); window.center()
    }

    func snapshot() {
        guard let view = previewWindow?.contentView,
              let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try bitmap.representation(using: .png, properties: [:])?.write(to: folder.appendingPathComponent("native-\(Int(Date.now.timeIntervalSince1970)).png"))
        } catch { message = String(describing: error) }
    }

    func toggleRecording() {
        if recording { recording = false; return }
        guard let view = previewWindow?.contentView else { return }
        recording = true
        Task { @MainActor in
            do { try await record(view) }
            catch { message = String(describing: error); NSLog("QA export failed: %@", message) }
            recording = false
        }
    }

    private func record(_ view: NSView) async throws {
        guard let window = view.window else { throw CocoaError(.fileWriteUnknown) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        // SDK currentProcess explicitly restricts this inventory to content available
        // to this process without TCC consent. Never request whole-desktop access.
        let content = try await SCShareableContent.currentProcess
        guard let ownWindow = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) && $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier }) else { throw CocoaError(.fileReadNoPermission) }
        let url = folder.appendingPathComponent("native-interaction-\(Int(Date.now.timeIntervalSince1970)).mp4")
        let configuration = SCStreamConfiguration()
        configuration.width = Int(window.frame.width) / 2 * 2
        configuration.height = Int(window.frame.height) / 2 * 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)
        configuration.capturesAudio = false; configuration.captureMicrophone = false
        configuration.showsCursor = true; configuration.ignoreShadowsSingleWindow = true
        let stream = SCStream(filter: SCContentFilter(desktopIndependentWindow: ownWindow), configuration: configuration, delegate: nil)
        let outputConfiguration = SCRecordingOutputConfiguration()
        outputConfiguration.outputURL = url
        outputConfiguration.videoCodecType = .h264; outputConfiguration.outputFileType = .mp4
        let delegate = PreviewRecordingDelegate()
        let output = SCRecordingOutput(configuration: outputConfiguration, delegate: delegate)
        try stream.addRecordingOutput(output)
        try await stream.startCapture()
        let start = ProcessInfo.processInfo.systemUptime
        while recording && ProcessInfo.processInfo.systemUptime - start < 45 && delegate.error == nil {
            try await Task.sleep(for: .milliseconds(50))
        }
        try await stream.stopCapture()
        for _ in 0..<100 {
            if delegate.finished || delegate.error != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        if let error = delegate.error { throw error }
        guard delegate.finished else { throw CocoaError(.fileWriteUnknown) }
        let record = "Native current-process window recording; 30 fps target; actual presentation timestamps; \(configuration.width)x\(configuration.height); reduced=\(reduced); no audio.\n"
        try record.write(to: url.deletingPathExtension().appendingPathExtension("txt"), atomically: true, encoding: .utf8)
        message = url.lastPathComponent
    }

}


@MainActor
private final class PreviewRecordingDelegate: NSObject, SCRecordingOutputDelegate {
    var finished = false
    var error: Error?
    nonisolated func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) {
        Task { @MainActor in self.finished = true }
    }
    nonisolated func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: Error) {
        Task { @MainActor in self.error = error }
    }
}

@main
struct LibrarySessionPreviewApp: App {
    private let container: ModelContainer
    @State private var qa = LibrarySessionQA()
    @State private var coordinator = ReviewCoordinator()

    init() {
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "1", 1)
        setenv("REVIEW_TODAY_DECK_METRICS", "/tmp/review-today-deck-paint-ms.txt", 1)
        unsetenv("REVIEW_TODAY_NATIVE_TEST_DIR")
        precondition(Bundle.main.bundleIdentifier == "Rex.Review-Today.LibrarySessionPreview")
        precondition(AppRuntime.current.isPreview && !AppRuntime.current.allowsSending)
        do {
            container = try M1DebugFixture.makeContainer(mode: "1")
            let context = container.mainContext
            let source = Source(inputType: "text", rawText: "原生交互验收的隔离样例，不是用户学习记录。")
            context.insert(source)
            let rag = Knowledge(learningGoal: "解释 RAG 的主要优势", knowledgeType: "concept", theme: "检索增强生成（RAG）", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "隔离排版样例：RAG 使用可验证的外部来源组织回答；仍需核对来源、权限和生成质量。", evidenceLocator: "隔离验收样例", title: "RAG 的主要优势", explanation: "通过 RAG 将大语言模型建立在一组可验证的外部事实之上，有助于实现以下几个有益目标：\n\n1. 准确性\n2. 成本效益\n3. 开发人员控制台\n4. 数据主权和隐私")
            rag.source = source
            let ragSpec = AgentAPI.ScoringSpec(learningGoal: rag.learningGoal, mustCover: ["准确性：提供可引用来源，减少错误或误导性信息", "成本效益：避免高昂重训练/微调，更新来源更方便", "开发和维护更直接：便于获取反馈、故障排除和修复应用", "数据主权和隐私：敏感数据可保留在本地并按授权级别限制检索"], acceptableParaphrases: [], commonMisconceptions: ["把优势只说成更快", "忽略准确性与可验证来源之间的关系", "认为 RAG 天然消除所有隐私风险"], evidence: rag.evidenceExcerpt, orderRules: "按原文四类优势组织，至少覆盖准确性与成本效益。")
            let ragQuestion = Question(variantIndex: 0, promptText: "请根据原文列出的 RAG 主要优势，并分别说明这些优势是如何体现的。", scoringSpecJSON: String(decoding: try JSONEncoder().encode(ragSpec), as: UTF8.self))
            ragQuestion.knowledge = rag
            context.insert(rag); context.insert(ragQuestion)
            let titles = ["RAG 的检索与生成分别负责什么", "向量嵌入如何表达内容的语义", "长内容：混合检索、重排与来源校验怎样共同影响复杂问题的答案质量", "为什么检索结果还需要权限检查", "如何选择合适的文本分块", "如何区分召回率与准确率", "如何判断引用是否支持结论", "文档更新后的索引维护", "RAG 与微调的适用边界", "top-k 与重排的取舍", "知识截止日期与时效性"] + (1...12).map { "定位条滚动样例 \($0)" }
            for (index, title) in titles.enumerated() {
                let paragraph = "检索负责找到与当前问题相关、且用户有权访问的资料；生成负责依据这些资料组织回答。两者都需要评估，检索到内容不代表结论一定正确。"
                let item = Knowledge(learningGoal: "解释" + title, knowledgeType: "concept", theme: "检索增强生成（RAG）", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: paragraph, evidenceLocator: "隔离验收样例", title: title, explanation: index == 2 ? Array(repeating: paragraph, count: 10).joined(separator: "\n\n") : paragraph)
                item.source = source
                let spec = AgentAPI.ScoringSpec(learningGoal: item.learningGoal, mustCover: ["先检索相关资料", "检查来源与权限", "依据资料组织回答"], acceptableParaphrases: [], commonMisconceptions: ["把检索结果当作已验证结论", "把生成与更新模型参数混为一谈"], evidence: paragraph, orderRules: "先说明职责，再说明边界。")
                let question = Question(variantIndex: 0, promptText: "请结合一个例子，解释\(title)，并说明容易混淆的边界。", scoringSpecJSON: String(decoding: try JSONEncoder().encode(spec), as: UTF8.self))
                question.knowledge = item
                context.insert(item); context.insert(question)
            }
            let vectorText = "嵌入模型把问题和文本片段转换为数值向量。语义相近的内容，通常会在向量空间中更接近，因此可以通过相似度找到候选资料。\n\n向量数据库负责存储和索引这些向量，并支持近邻检索及元数据过滤。RAG 将取回的原文片段交给生成模型，作为组织回答的参考。\n\n相似度高不等于内容准确。检索结果仍需要检查来源、权限和时效性；向量检索也不会直接更新生成模型的参数。"
            let vector = Knowledge(learningGoal: "解释向量嵌入和向量数据库在 RAG 检索中的作用", knowledgeType: "concept", theme: "向量嵌入与检索", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: vectorText, evidenceLocator: "隔离设计样例", title: "向量嵌入和向量数据库在 RAG 检索中的作用", explanation: vectorText)
            vector.source = source
            let vectorSpec = AgentAPI.ScoringSpec(learningGoal: vector.learningGoal, mustCover: ["嵌入将问题和内容表示为数值向量", "通过向量相似度查找语义相关的候选资料", "向量数据库提供存储、索引与检索能力", "生成模型依据取回的原文组织回答"], acceptableParaphrases: [], commonMisconceptions: ["相似度高就代表内容真实", "向量数据库直接生成最终答案", "检索过程等同于训练模型"], evidence: vectorText, orderRules: "先解释内容如何表示，再说明检索与生成的衔接。")
            let vectorQuestion = Question(variantIndex: 0, promptText: "在 RAG 中，为什么要把内容转换为向量？向量数据库又如何帮助找到相关资料？", scoringSpecJSON: String(decoding: try JSONEncoder().encode(vectorSpec), as: UTF8.self))
            vectorQuestion.knowledge = vector
            context.insert(vector); context.insert(vectorQuestion)
            let incomplete = Knowledge(learningGoal: "缺失题目示例", knowledgeType: "concept", theme: "边界状态", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "", evidenceLocator: "", title: "只有资料，还没有检查题", explanation: "这条合成资料用来检查缺少题目、判断标准与来源时的显示。保存资料不等于已经掌握。")
            context.insert(incomplete)
            for title in ["RAG 已归档基础", "RAG 已归档评估", "向量检索已归档"] {
                let session = AgentSession(title: title, modePreset: "auto")
                session.status = "archived"; session.archivedAt = .now; session.setAutomaticTopicTags(["隔离样例"])
                context.insert(session)
            }
            try context.save()
        } catch { fatalError("Isolated UI fixture failed: \(error)") }
    }

    @MainActor private func addStressCards() {
        let context = container.mainContext
        let items = (try? context.fetch(FetchDescriptor<Knowledge>())) ?? []
        guard let original = items.first(where: { $0.explanation.count > 500 }), items.count < 100 else { return }
        for index in items.count..<100 {
            let card = Knowledge(learningGoal: "压力样例 \(index)", knowledgeType: original.knowledgeType, theme: original.theme, contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: original.evidenceExcerpt, evidenceLocator: "隔离性能样例", title: "压力样例 \(index)", explanation: original.explanation)
            card.source = original.source; context.insert(card)
            if let q = original.questions.first {
                let question = Question(variantIndex: 0, promptText: q.promptText, scoringSpecJSON: q.scoringSpecJSON)
                question.knowledge = card; context.insert(question)
            }
        }
        try? context.save()
    }

    var body: some Scene {
        WindowGroup("知识卡 · 轻纸面对照", id: "main") {
            VStack(spacing: 0) {
                ContentView(coordinator: coordinator)
                    .environment(\.knowledgePaper, qa.paper)
                    .environment(\.knowledgePrototype, true)
                    .environment(\.brandTrialStill, qa.reduced)
                HStack(spacing: 16) {
                    Text("知识卡设计 · 隔离小样").font(.caption).foregroundStyle(.secondary)
                    Picker("版本", selection: $qa.paper) {
                        Text("当前版").tag(false)
                        Text("轻纸面").tag(true)
                    }.pickerStyle(.segmented).frame(width: 170)
                    Spacer()
                    Button("浅深色") { let a = AppearanceController.shared; a.setDark(!a.isDark, screenPoint: nil, reduceMotion: true) }
                    Toggle("减少动态", isOn: $qa.reduced).toggleStyle(.checkbox)
                    Button("截图") { qa.snapshot() }
                    Button(qa.recording ? "停止录制" : "录制") { qa.toggleRecording() }.help(qa.message.isEmpty ? "录制本原型窗口，最多45秒" : qa.message)
                }.padding(.horizontal, 16).padding(.vertical, 8)
            }.modelContainer(container).runwayAppearance()
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1280, height: 820).windowResizability(.contentMinSize)
        .commands {
            CommandMenu("验收") {
                Toggle("轻纸面新版", isOn: $qa.paper).keyboardShortcut("b", modifiers: [.command, .option])
                Button("添加到100张知识（隔离数据）") { addStressCards() }
                Button("标准窗口") { qa.resize(1280, 820) }.keyboardShortcut("1", modifiers: [.command, .option])
                Button("最小窗口") { qa.resize(760, 620) }.keyboardShortcut("2", modifiers: [.command, .option])
                Button("切换深浅主题") { let appearance = AppearanceController.shared; appearance.setDark(!appearance.isDark, screenPoint: nil, reduceMotion: true) }.keyboardShortcut("d", modifiers: [.command, .option])
                Toggle("减少动态效果", isOn: $qa.reduced).keyboardShortcut("m", modifiers: [.command, .option])
                Button("保存本窗口截图") { qa.snapshot() }.keyboardShortcut("s", modifiers: [.command, .option])
                Button(qa.recording ? "停止本窗口录制" : "录制本窗口（最多45秒）") { qa.toggleRecording() }.keyboardShortcut("r", modifiers: [.command, .option])
            }
        }
        Settings { SettingsView().modelContainer(container).runwayAppearance() }
    }
}
