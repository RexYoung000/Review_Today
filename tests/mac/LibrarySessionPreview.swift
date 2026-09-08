import AppKit
import AVFoundation
import SwiftData
import ScreenCaptureKit
import SwiftUI

/// Runs the actual product views against an in-memory store. All exports are
/// from this preview's own view, never another app or the daily database.
@MainActor @Observable
final class LibrarySessionQA {
    var reduced = false
    var recording = false
    var message = ""

    private var folder: URL {
        URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent("docs/evidence/2026-09-08-library-sessions")
    }

    func resize(_ width: CGFloat, _ height: CGFloat) {
        guard let window = NSApp.keyWindow else { return }
        window.setContentSize(NSSize(width: width, height: height)); window.center()
    }

    func snapshot() {
        guard let view = NSApp.keyWindow?.contentView,
              let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try bitmap.representation(using: .png, properties: [:])?.write(to: folder.appendingPathComponent("native-\(Int(Date.now.timeIntervalSince1970)).png"))
        } catch { message = String(describing: error) }
    }

    func toggleRecording() {
        if recording { recording = false; return }
        guard let view = NSApp.keyWindow?.contentView else { return }
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
        unsetenv("REVIEW_TODAY_NATIVE_TEST_DIR")
        precondition(Bundle.main.bundleIdentifier == "Rex.Review-Today.LibrarySessionPreview")
        precondition(AppRuntime.current.isPreview && !AppRuntime.current.allowsSending)
        do {
            container = try M1DebugFixture.makeContainer(mode: "1")
            let context = container.mainContext
            let source = Source(inputType: "text", rawText: "原生交互验收的隔离样例，不是用户学习记录。")
            context.insert(source)
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
            for title in ["RAG 已归档基础", "RAG 已归档评估", "向量检索已归档"] {
                let session = AgentSession(title: title, modePreset: "auto")
                session.status = "archived"; session.archivedAt = .now; session.setAutomaticTopicTags(["隔离样例"])
                context.insert(session)
            }
            try context.save()
        } catch { fatalError("Isolated UI fixture failed: \(error)") }
    }

    var body: some Scene {
        WindowGroup("知识卡与会话 · 隔离原生验收") {
            ContentView(coordinator: coordinator).modelContainer(container).runwayAppearance()
                .environment(\.brandTrialStill, qa.reduced)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1280, height: 820).windowResizability(.contentMinSize)
        .commands {
            CommandMenu("验收") {
                Button("标准窗口") { qa.resize(1280, 820) }.keyboardShortcut("1", modifiers: [.command, .option])
                Button("最小窗口") { qa.resize(760, 620) }.keyboardShortcut("2", modifiers: [.command, .option])
                Button("切换深浅主题") { let appearance = AppearanceController.shared; appearance.setDark(!appearance.isDark, screenPoint: nil, reduceMotion: true) }.keyboardShortcut("d", modifiers: [.command, .option])
                Toggle("减少动态效果", isOn: $qa.reduced).keyboardShortcut("m", modifiers: [.command, .option])
                Button("保存本窗口截图") { qa.snapshot() }.keyboardShortcut("s", modifiers: [.command, .option])
                Button(qa.recording ? "停止本窗口录制" : "录制本窗口（最多45秒）") { qa.toggleRecording() }.keyboardShortcut("r", modifiers: [.command, .option])
            }
        }
    }
}
