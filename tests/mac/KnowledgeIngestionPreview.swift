import Combine
import AppKit
import SwiftData
import SwiftUI
import ScreenCaptureKit
import AVFoundation

@main struct KnowledgeIngestionPreview: App {
    let container: ModelContainer
    let session: AgentSession
    @State private var qa = IngestionQA()
    init() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("ingestion-native-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        container = try! ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: dir.appendingPathComponent("test.store")))
        session = AgentSession(title: "知识入库隔离验收")
        container.mainContext.insert(session)
        let message = AgentMessage(sessionID: session.id, role: "coach", content: "检索找到相关资料，生成依据资料组织回答。\n\n这一版已经整理好，可以加入知识库。", deliveryStatus: "accepted")
        container.mainContext.insert(message)
        session.pendingOperationJSON = "{\"kind\":\"save\",\"target_id\":\"\(UUID())\",\"version\":1}"
        try! container.mainContext.save()
    }
    var body: some Scene {
        WindowGroup {
            IngestionQAView(session: session, qa: qa).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 760)
        .commands {
            CommandMenu("入库验收") {
                Button("准备下一次") { qa.reset(session, context: container.mainContext) }.keyboardShortcut("n", modifiers: [.command, .option])
                Toggle("模拟磁盘失败", isOn: $qa.failSave).keyboardShortcut("f", modifiers: [.command, .option])
                Toggle("减少动态", isOn: $qa.reduced).keyboardShortcut("l", modifiers: [.command, .option])
                Toggle("深色", isOn: Binding(get: { qa.dark }, set: { qa.dark = $0; AppearanceController.shared.setDark($0, screenPoint: nil, reduceMotion: true) })).keyboardShortcut("d", modifiers: [.command, .option])
                Button("开始或停止原速录制") { qa.capture.toggleRecording() }.keyboardShortcut("r", modifiers: [.command, .option])
                Button("保存截图") { qa.capture.snapshot() }.keyboardShortcut("s", modifiers: [.command, .option])
                Button("最小窗口") { NSApp.keyWindow?.setContentSize(NSSize(width: 760, height: 620)) }.keyboardShortcut("m", modifiers: [.command, .option])
                Button("标准窗口") { NSApp.keyWindow?.setContentSize(NSSize(width: 1040, height: 760)) }.keyboardShortcut("w", modifiers: [.command, .option])
            }
        }
    }
}

@MainActor @Observable final class IngestionQA {
    var state = KnowledgeIngestion()
    var failSave = false
    var reduced = false
    var dark = false
    var selectedKnowledge: UUID?
    var showLibrary = false
    var capture = IngestionCapture()
    var monitor = AgentServiceMonitor()
    enum Disk: Error { case failed }
    func reset(_ session: AgentSession, context: ModelContext) {
        state.leaveContext(); showLibrary = false
        session.pendingOperationJSON = "{\"kind\":\"save\",\"target_id\":\"\(UUID())\",\"version\":1}"
        try! context.save()
    }
    func send(_ message: AgentMessage, explicit: Bool, context: ModelContext) {
        state.register(input: message.id, session: message.sessionID, explicitSave: explicit, eligible: true,
                       compact: UserDefaults.standard.bool(forKey: KnowledgeIngestion.preferenceKey))
        // Only the remote response/delay is substituted; product send, controller,
        // atomic disk write, notification, sheet and knowledge opening are real.
        message.deliveryStatus = "accepted"
        let task = LearningTask(sessionID: message.sessionID, inputMessageID: message.id)
        task.mode = "memory_organization"; task.status = "committing"; task.conversationManaged = true
        context.insert(task); try! context.save()
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(6))
            do {
                let payload = try KnowledgeIngestionFixture.payload([UUID(), UUID()])
                _ = try HarnessProcessor.persistMemory(payload, sourceText: "检索找到相关资料，生成依据资料组织回答。", task: task, context: context,
                                                       save: failSave ? { throw Disk.failed } : nil)
            } catch { task.status = "retryable_failed"; task.errorCode = "LOCAL_SAVE_FAILED"; try? context.save() }
        }
    }
}

struct IngestionQAView: View {
    let session: AgentSession
    @Bindable var qa: IngestionQA
    @State private var selection: UUID?
    @State private var coordinator = ReviewCoordinator()
    @Environment(\.modelContext) private var context
    var body: some View {
        VStack(spacing: 0) {
            Text("隔离验收 · 服务回复为样例，卡片实际写入独立数据库 · 无模型请求").font(.caption).foregroundStyle(.secondary).padding(8)
            if qa.showLibrary {
                LibraryView(selectedID: $qa.selectedKnowledge, coordinator: coordinator)
            } else {
                LearningWorkspace(monitor: qa.monitor, selectedSessionID: $selection,
                    onOpenKnowledge: { qa.selectedKnowledge = $0; qa.showLibrary = true },
                    onMessageSaved: { qa.send($0, explicit: $1, context: context) })
            }
        }
        .frame(minWidth: 760, minHeight: 620)
        .preferredColorScheme(qa.dark ? .dark : .light)
        .environment(\.brandTrialStill, qa.reduced)
        .sheet(isPresented: $qa.state.presented) {
            KnowledgeIngestionSheet(ingestion: qa.state) { qa.selectedKnowledge = $0; qa.showLibrary = true }
                .preferredColorScheme(qa.dark ? .dark : .light).environment(\.brandTrialStill, qa.reduced)
        }
        .onReceive(NotificationCenter.default.publisher(for: .knowledgeIngestionSaved)) { note in
            guard let source = note.object as? ModelContext, source === context,
                  let receipt = note.userInfo?["receipt"] as? KnowledgeIngestionReceipt else { return }
            qa.state.receive(receipt, eligible: true, compact: false)
            session.pendingOperationJSON = nil; try? context.save()
        }
        .onAppear { qa.dark = AppearanceController.shared.isDark; selection = session.id; qa.monitor.useFixturePresentation() }
        .onReceive(NotificationCenter.default.publisher(for: ModelContext.didSave).receive(on: RunLoop.main)) { _ in
            qa.state.refresh(context: context, eligible: NSApp.isActive, compact: false)
        }
    }
}

@MainActor @Observable
final class IngestionCapture {
    var reduced = false
    var recording = false
    var message = ""

    private var folder: URL {
        URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent("docs/evidence/2026-09-08-mr-b/ingestion-integration")
    }

    func resize(_ width: CGFloat, _ height: CGFloat) {
        guard let window = NSApp.keyWindow else { return }
        window.setContentSize(NSSize(width: width, height: height)); window.center()
    }

    func snapshot() {
        guard let key = NSApp.keyWindow else { return }
        let window = key.sheetParent ?? key
        Task { @MainActor in
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let content = try await SCShareableContent.currentProcess
                guard let own = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else { return }
                let config = SCStreamConfiguration()
                config.width = Int(window.frame.width) * 2; config.height = Int(window.frame.height) * 2
                config.ignoreShadowsSingleWindow = true
                let shot = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: own), configuration: config)
                let bitmap = NSBitmapImageRep(cgImage: shot)
                try bitmap.representation(using: .png, properties: [:])?.write(to: folder.appendingPathComponent("native-\(Int(Date.now.timeIntervalSince1970)).png"))
            } catch { message = String(describing: error) }
        }
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

    private func record(_ view: NSView,onStarted:()->Void = {},shouldStop:()->Bool = {false}) async throws {
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
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("mr-b-capture-\(UUID().uuidString).mp4")
        outputConfiguration.outputURL = temporary
        outputConfiguration.videoCodecType = .h264; outputConfiguration.outputFileType = .mp4
        let delegate = PreviewRecordingDelegate()
        let output = SCRecordingOutput(configuration: outputConfiguration, delegate: delegate)
        try stream.addRecordingOutput(output)
        // startCapture may synchronously wait on its file-extension request.
        // Keep that system call off the UI thread; record into our temporary
        // directory and only move a successfully finished file into evidence.
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            DispatchQueue.global(qos: .userInitiated).async {
                stream.startCapture { error in
                    if let error { continuation.resume(throwing: error) }
                    else { continuation.resume() }
                }
            }
        }
        try await Task.sleep(for:.milliseconds(350)); onStarted()
        let start = ProcessInfo.processInfo.systemUptime
        while recording && ProcessInfo.processInfo.systemUptime - start < 45 && delegate.error == nil && !shouldStop() {
            try await Task.sleep(for: .milliseconds(50))
        }
        if shouldStop() { try await Task.sleep(for:.milliseconds(600)) }
        try await stream.stopCapture()
        for _ in 0..<100 {
            if delegate.finished || delegate.error != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        if let error = delegate.error { throw error }
        guard delegate.finished else { throw CocoaError(.fileWriteUnknown) }
        try FileManager.default.moveItem(at: temporary, to: url)
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
