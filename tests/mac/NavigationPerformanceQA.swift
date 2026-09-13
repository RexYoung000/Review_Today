import AppKit
import SwiftUI
import SwiftData
import ScreenCaptureKit
import CoreMedia

@MainActor @Observable
final class NavigationQA {
    var status = "就绪：测试使用独立数据库，不连接学习服务"
    var running = false
    var reduced = false
    let directory: URL
    let dataset: String
    init() {
        directory = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PerformanceDirectory") as! String)
        dataset = Bundle.main.object(forInfoDictionaryKey: "PerformanceDataset") as! String
    }
    func recordMotion(reduced: Bool) {
        guard !running, let window = NSApp.windows.first(where: { $0.canBecomeMain }) else { return }
        running = true; self.reduced = reduced
        NSApp.activate(ignoringOtherApps: true); window.makeKeyAndOrderFront(nil)
        status = reduced ? "录制四页切换：减少动态" : "录制四页切换：标准动效"
        Task { @MainActor in
            do {
                try await Task.sleep(for: .milliseconds(300))
                let url = try await PageMotionCapture().record(window: window, directory: directory, reduced: reduced)
                status = "录制完成：" + url.lastPathComponent
            } catch { status = "录制失败：" + String(describing: error) }
            running = false
        }
    }
    func exportInteractions() {
        do {
            let record: [String: Any] = ["dataset": dataset, "navigation_and_menus": NavigationPerformance.rows,
                "activations": NavigationPerformance.activationRows,
                "boundary": "handler/activation notification to native draw; excludes OS input delivery and scanout"]
            try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
                .write(to: directory.appendingPathComponent("interactions.json"), options: .atomic)
            status = "菜单与窗口恢复记录已保存"
        } catch { status = "保存交互记录失败：\(error)" }
    }
    func runMenus() {
        guard !running else { return }
        running = true
        Task { @MainActor in
            NotificationCenter.default.post(name: NavigationPerformance.navigate, object: "learning")
            try? await Task.sleep(for: .seconds(1))
            NavigationPerformance.rows = []
            for title in ["添加材料", "学习方式", "思考强度"] {
                for index in 0..<31 {
                    status = "菜单绘制诊断：\(title) \(index + 1)/31（每条记录前台状态）"
                    let count = NavigationPerformance.completed
                    NotificationCenter.default.post(name: NavigationPerformance.menu, object: title, userInfo: ["open": true])
                    let started = ProcessInfo.processInfo.systemUptime
                    while NavigationPerformance.completed == count && ProcessInfo.processInfo.systemUptime - started < 10 {
                        try? await Task.sleep(for: .milliseconds(20))
                    }
                    NotificationCenter.default.post(name: NavigationPerformance.menu, object: title, userInfo: ["open": false])
                    guard NavigationPerformance.completed != count else {
                        status = "菜单绘制超时；保留已有交互记录"; exportInteractions(); running = false; return
                    }
                    try? await Task.sleep(for: .milliseconds(200))
                }
            }
            exportInteractions(); running = false
        }
    }
    func run(foregroundRequired: Bool = true) {
        guard !running else { return }
        running = true
        NSApp.activate(ignoringOtherApps: true)
        NSApp.windows.first(where: { $0.canBecomeMain })?.makeKeyAndOrderFront(nil)
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(300))
            guard NSApp.isActive || !foregroundRequired else { status = "请激活本窗口后再采样"; running = false; return }
            NavigationPerformance.rows = []
            for index in 0..<62 {
                status = "原生绘制采样 \(index + 1)/62"
                let count = NavigationPerformance.completed
                NotificationCenter.default.post(name: NavigationPerformance.navigate, object: index.isMultiple(of: 2) ? "today" : "learning")
                let started = ProcessInfo.processInfo.systemUptime
                while NavigationPerformance.completed == count && ProcessInfo.processInfo.systemUptime - started < 120 {
                    try? await Task.sleep(for: .milliseconds(20))
                }
                if NavigationPerformance.completed == count { status = "未收到目标页面绘制，采样中止"; running = false; return }
                try? await Task.sleep(for: .milliseconds(200))
            }
            do {
                let record: [String: Any] = ["dataset": dataset, "boundary": "selection handler to AppKit draw; not physical scanout",
                    "warmup_rows": 2, "foreground_required": foregroundRequired, "rows": NavigationPerformance.rows]
                let data = try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
                try data.write(to: directory.appendingPathComponent(foregroundRequired ? "navigation.json" : "navigation-background.json"), options: .atomic)
                status = "完成：60 条热切换记录已保存"
            } catch { status = "保存测量失败：\(error)" }
            running = false
        }
    }
}

@main
struct NavigationPerformanceQAApp: App {
    let container: ModelContainer
    @State private var qa = NavigationQA()
    @State private var coordinator = ReviewCoordinator()
    init() {
        precondition(AppRuntime.current.isPreview && !AppRuntime.current.allowsSending)
        let directory = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PerformanceDirectory") as! String)
        let stress = Bundle.main.object(forInfoDictionaryKey: "PerformanceDataset") as! String == "stress"
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            container = try M1DebugFixture.makeValidationContainer(directory)
            let c = container.mainContext
            if try c.fetchCount(FetchDescriptor<AppSettings>()) == 0 {
                c.insert(AppSettings())
                var sessions: [AgentSession] = []
                for index in 0..<(stress ? 300 : 3) {
                    let s = AgentSession(title: "隔离会话 \(index + 1)"); c.insert(s); sessions.append(s)
                }
                for index in 0..<(stress ? 1000 : 8) {
                    c.insert(Knowledge(learningGoal: "解释概念 \(index)", knowledgeType: "concept", theme: "性能验收",
                        contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "隔离样例",
                        evidenceLocator: "fixture", title: "知识 \(index)", explanation: "相同的固定样例，不是用户数据。"))
                }
                if stress {
                    for index in 0..<10000 {
                        c.insert(AgentMessage(sessionID: sessions[index % sessions.count].id, role: index.isMultiple(of: 2) ? "user" : "assistant",
                            content: "固定历史消息 \(index)：保留输入、响应与会话归属。", deliveryStatus: "completed"))
                    }
                    for index in 0..<5000 {
                        let run = AgentRun(id: UUID(), sessionID: sessions[index % sessions.count].id)
                        run.status = "completed"; run.activityKind = "knowledge_answer"
                        run.completedAt = Calendar.current.date(byAdding: .day, value: -(index % 360), to: .now)
                        c.insert(run)
                    }
                }
                try c.save()
            }
        } catch { fatalError("Isolated performance fixture failed: \(error)") }
    }
    var body: some Scene {
        WindowGroup("Review Today · 性能隔离验收", id: "main") {
            ContentView(coordinator: coordinator).modelContainer(container).runwayAppearance()
                .environment(\.brandTrialStill, qa.reduced)
                .background(ActivationPaintProbe().allowsHitTesting(false).accessibilityHidden(true))
                .safeAreaInset(edge: .bottom) {
                    HStack { Text(qa.status); Spacer(); Button("运行 30 轮切页采样") { qa.run() }.disabled(qa.running) }
                        .font(.caption).padding(6)
                }
        }.windowStyle(.hiddenTitleBar).defaultSize(width: 1280, height: 820).windowResizability(.contentMinSize)
        .commands {
            CommandMenu("性能验收") {
                Button("录制四页切换：标准动效") { qa.recordMotion(reduced: false) }.disabled(qa.running)
                Button("录制四页切换：减少动态") { qa.recordMotion(reduced: true) }.disabled(qa.running)
                Button("保存菜单与窗口恢复记录") { qa.exportInteractions() }.disabled(qa.running)
                Button("运行菜单绘制诊断（含前台标记）") { qa.runMenus() }.disabled(qa.running)
                Button("运行后台绘制诊断（不作前台验收）") { qa.run(foregroundRequired: false) }.disabled(qa.running)
                Button("运行 30 轮切页采样") { qa.run() }.keyboardShortcut("r", modifiers: [.command, .option]).disabled(qa.running)
            }
        }
    }
}

/// Records only this isolated QA window. No desktop inventory, audio or model calls.
@MainActor private final class PageMotionCapture: NSObject, SCRecordingOutputDelegate {
    private var finished = false
    private var failure: Error?
    func record(window: NSWindow, directory: URL, reduced: Bool) async throws -> URL {
        let content = try await SCShareableContent.currentProcess
        guard let own = content.windows.first(where: {
            $0.windowID == CGWindowID(window.windowNumber) &&
            $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier
        }) else { throw CocoaError(.fileReadNoPermission) }
        let configuration = SCStreamConfiguration()
        configuration.width = Int(window.frame.width) / 2 * 2
        configuration.height = Int(window.frame.height) / 2 * 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 60)
        configuration.capturesAudio = false; configuration.captureMicrophone = false
        configuration.showsCursor = true; configuration.ignoreShadowsSingleWindow = true
        let stream = SCStream(filter: SCContentFilter(desktopIndependentWindow: own), configuration: configuration, delegate: nil)
        let outputConfiguration = SCRecordingOutputConfiguration()
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("review-today-arrival-\(UUID().uuidString).mp4")
        outputConfiguration.outputURL = temporary
        outputConfiguration.videoCodecType = .h264; outputConfiguration.outputFileType = .mp4
        try stream.addRecordingOutput(SCRecordingOutput(configuration: outputConfiguration, delegate: self))
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            DispatchQueue.global(qos: .userInitiated).async {
                stream.startCapture { error in
                    if let error { continuation.resume(throwing: error) }
                    else { continuation.resume() }
                }
            }
        }
        try await Task.sleep(for: .milliseconds(400))
        func findFade(_ view: NSView) -> PageArrivalFade.Surface? {
            if let view = view as? PageArrivalFade.Surface { return view }
            return view.subviews.lazy.compactMap { findFade($0) }.first
        }
        let fade = window.contentView.flatMap { findFade($0) }
        var fadeSamples: [[String: Any]] = []
        let started = ProcessInfo.processInfo.systemUptime
        for page in ["today", "learning", "library", "inbox", "library", "learning", "today"] {
            NotificationCenter.default.post(name: NavigationPerformance.navigate, object: page)
            for _ in 0..<40 {
                try await Task.sleep(for: .milliseconds(20))
                fadeSamples.append(["page": page, "time": ProcessInfo.processInfo.systemUptime - started,
                    "width": fade?.bounds.width ?? -1, "height": fade?.bounds.height ?? -1,
                    "presentation_opacity": fade?.layer?.presentation()?.opacity ?? 0,
                    "animation_present": fade?.layer?.animation(forKey: PageArrivalFade.Surface.animationKey) != nil,
                    "app_active": NSApp.isActive])
            }
        }
        for page in ["learning", "library", "inbox", "today", "library", "learning"] {
            NotificationCenter.default.post(name: NavigationPerformance.navigate, object: page)
            try await Task.sleep(for: .milliseconds(40))
        }
        try await Task.sleep(for: .milliseconds(800))
        try await stream.stopCapture()
        for _ in 0..<100 {
            if finished || failure != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        if let failure { throw failure }
        guard finished else { throw CocoaError(.fileWriteUnknown) }
        let name = "arrival-\(reduced ? "reduced" : "standard")-\(Int(Date.now.timeIntervalSince1970))"
        let url = directory.appendingPathComponent(name + ".mp4")
        try FileManager.default.moveItem(at: temporary, to: url)
        try JSONSerialization.data(withJSONObject: fadeSamples, options: [.prettyPrinted, .sortedKeys])
            .write(to: directory.appendingPathComponent(name + ".json"))
        try "Current-process QA window, actual presentation timestamps, 60 fps target, reduced=\(reduced), no audio. Scripted real page selection; not OS input latency evidence.\n".write(to: directory.appendingPathComponent(name + ".txt"), atomically: true, encoding: .utf8)
        return url
    }
    nonisolated func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) {
        Task { @MainActor in self.finished = true }
    }
    nonisolated func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: Error) {
        Task { @MainActor in self.failure = error }
    }
}
