import AppKit
import SwiftUI
import SwiftData
import ScreenCaptureKit
import AVFoundation

/// Synthetic server outcomes, production transcript/buttons/Spine and real isolated SwiftData commit.
@main struct TopicCaptureNativeQA: App {
    let container: ModelContainer
    let session: AgentSession
    @State private var qa = TopicQAState()
    init() {
        let dir = "/tmp/review-today-topic-native-" + UUID().uuidString
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", dir, 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "18764", 1)
        unsetenv("REVIEW_TODAY_M1_UI_FIXTURE")
        try! FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        container = try! ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: URL(fileURLWithPath: dir + "/test.store")))
        session = AgentSession(title: "话题收尾隔离验收")
        container.mainContext.insert(session); try! container.mainContext.save()
        print("QA isolated store: \(dir)"); fflush(stdout)
    }
    var body: some Scene {
        WindowGroup { TopicQARoot(session: session, qa: qa).modelContainer(container).runwayAppearance() }
            .defaultSize(width: 1040, height: 820)
    }
}

@MainActor @Observable final class TopicQAState {
    var fail = false
    var reduced = false
    var dark = false
    var inbox = false
    var legacy = false
    var unpassed = false
    var offer: TopicCaptureOffer?
    var selectedKnowledge: UUID?
    var showLibrary = false
    var capture = TopicQACapture()
    var monitor = AgentServiceMonitor()
    var coordinator = ReviewCoordinator()
    var sequence = 0
    enum Disk: Error { case simulatedFailure }
    func store(_ session: AgentSession, _ context: ModelContext) {
        session.captureOffersJSON = String(data: try! JSONEncoder().encode(offer.map { [$0] } ?? []), encoding: .utf8)!
        session.captureOffersRevision += 1; try! context.save()
    }
    func reset(_ session: AgentSession, _ context: ModelContext) {
        sequence += 1; showLibrary = false; inbox = false
        for m in try! context.fetch(FetchDescriptor<AgentMessage>()) where m.sessionID == session.id { context.delete(m) }
        let question = AgentMessage(sessionID: session.id, role: "user", content: "RAG 与微调有什么区别？", deliveryStatus: "accepted")
        let answer = AgentMessage(sessionID: session.id, role: "coach", content: "RAG 在回答前检索资料；微调通过训练调整模型参数。前者提供依据，后者调整行为。\n\n> [!NOTE]\n> 网页核验暂未完成，先讲基础内容；涉及变化或争议的部分仍需核实。", deliveryStatus: "accepted")
        let response = AgentMessage(sessionID: session.id, role: "user", content: legacy ? "明白了，接下来讲 Agent。" : "RAG 先检索再生成，微调会调整模型参数。", deliveryStatus: "accepted")
        context.insert(question); context.insert(answer); context.insert(response)
        question.createdAt = Date.now.addingTimeInterval(-4); answer.createdAt = Date.now.addingTimeInterval(-3); response.createdAt = Date.now.addingTimeInterval(-2)
        if legacy {
            offer = .init(id: UUID(), version: 1, title: "RAG 与微调的区别", anchorMessageID: response.id, status: "offered", nextRequest: "接下来讲 Agent。", continuationConsumed: false)
        } else {
            let feedback = AgentMessage(sessionID: session.id, role: "coach", content: unpassed ? "这次还需要补充：RAG 的资料检索不会直接改变模型参数。可以继续想一想或追问。" : "答对了。", deliveryStatus: "accepted")
            context.insert(feedback); feedback.createdAt = Date.now.addingTimeInterval(-1)
            offer = unpassed ? nil : .init(id: UUID(), version: 1, title: "RAG 与微调的区别", anchorMessageID: feedback.id, status: "offered", nextRequest: "", continuationConsumed: true, trigger: "verified_check", scopeSummary: "RAG 先检索资料再生成回答；微调通过训练调整模型参数。")
        }
        store(session, context)
        print("QA reset \(sequence); synthetic model state; isolated store"); fflush(stdout)
    }
    func refreshScope(_ session: AgentSession, _ context: ModelContext) {
        guard offer?.isCheckInvitation == true, ["offered", "deferred"].contains(offer?.status ?? "") else { return }
        let oldID = offer!.id, oldAnchor = offer!.anchorMessageID
        offer?.version += 1
        offer?.scopeSummary = "RAG 先检索资料再生成回答；微调通过训练调整模型参数。检索资料不足时应说明限制。"
        precondition(offer?.id == oldID && offer?.anchorMessageID == oldAnchor)
        store(session, context)
        print("QA same invitation range refreshed: version=\(offer!.version), anchor retained; no generation"); fflush(stdout)
    }
    func next(_ session: AgentSession, _ context: ModelContext) {
        guard offer?.hasNext == true else { return }
        offer?.continuationConsumed = true
        context.insert(AgentMessage(sessionID: session.id, role: "coach", content: "下面开始 Agent 的基本组成：模型负责判断，循环根据执行结果推进下一步。\n\n（隔离样例续讲，仅验证界面交接。）", deliveryStatus: "accepted"))
        print("QA continued once"); fflush(stdout)
    }
    func sent(_ message: AgentMessage, session: AgentSession, context: ModelContext) {
        message.deliveryStatus = "accepted"
        guard let raw = message.operationJSON?.data(using: .utf8), let op = try? JSONSerialization.jsonObject(with: raw) as? [String: Any], let kind = op["kind"] as? String else {
            print("QA followup accepted without saving: \(message.content)"); fflush(stdout)
            return
        }
        guard op["target_id"] as? String == offer?.id.uuidString.lowercased(), op["version"] as? Int == offer?.version else {
            message.deliveryStatus = "retryable_failed"; message.lastDeliveryError = "范围已更新，请使用当前邀请。"; try! context.save()
            print("QA stale displayed-version action rejected"); fflush(stdout); return
        }
        print("QA bound action: \(kind), version=\(offer!.version), reviewRequested=\(message.reviewRequested)"); fflush(stdout)
        if kind == "capture_later" || kind == "capture_skip" {
            offer?.status = kind == "capture_later" ? "deferred" : "skipped"; next(session, context); store(session, context); return
        }
        guard kind == "capture_save" else { return }
        let task = (try? context.fetch(FetchDescriptor<LearningTask>()))?.first(where: { $0.id == offer?.saveTaskID }) ?? LearningTask(sessionID: session.id, inputMessageID: message.id)
        task.inputMessageID = message.id
        task.mode = "memory_organization"; task.status = "committing"; task.conversationManaged = true
        context.insert(task)
        offer?.status = "saving"; offer?.actionInputID = message.id; offer?.saveTaskID = task.id; offer?.error = nil
        store(session, context)
        let savedSequence = sequence
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(5))
            guard savedSequence == sequence else { return }
            do {
                let ids = [UUID(), UUID()]
                _ = try HarnessProcessor.persistMemory(KnowledgeIngestionFixture.payload(ids), sourceText: "检索找到相关资料，生成依据资料组织回答。", task: task, context: context, save: fail ? { throw Disk.simulatedFailure } : nil)
                offer?.status = "saved"; offer?.knowledgeIDs = ids
                next(session, context)
                print("QA real isolated commit: \(ids.count) cards")
            } catch {
                task.status = "retryable_failed"; offer?.status = "failed"; offer?.error = "隔离测试：模拟本机写入失败，请重试。"
                print("QA failed; no success receipt")
            }
            store(session, context); fflush(stdout)
        }
    }
}

struct TopicQARoot: View {
    let session: AgentSession
    @Bindable var qa: TopicQAState
    @State private var selection: UUID?
    @State private var destination: UUID?
    @Environment(\.modelContext) private var context
    var body: some View {
        VStack(spacing: 0) {
            Text("隔离验证 · 合成服务状态 · 使用正式对话界面和本机保存 · 不访问日常数据").font(.caption).foregroundStyle(.secondary).padding(6)
            HStack {
                Button("重置") { qa.reset(session, context); destination = nil }
                Button("更新范围") { qa.refreshScope(session, context) }.disabled(qa.offer?.isCheckInvitation != true || !["offered", "deferred"].contains(qa.offer?.status ?? ""))
                Toggle("保存失败", isOn: $qa.fail)
                Toggle("减少动态", isOn: $qa.reduced)
                Toggle("深色", isOn: $qa.dark)
                Button(qa.inbox ? "回到对话" : "待处理") { qa.inbox.toggle() }
                Button("窄窗") { (NSApp.keyWindow ?? NSApp.windows.first(where: \.isVisible))?.setContentSize(NSSize(width: 760, height: 680)) }
                Button("标准") { (NSApp.keyWindow ?? NSApp.windows.first(where: \.isVisible))?.setContentSize(NSSize(width: 1040, height: 820)) }
                Button("截图") { qa.capture.snapshot() }
                Button(qa.capture.recording ? "停止录制" : "录制") { qa.capture.toggle() }
            }.controlSize(.small).padding(8)
            HStack {
                Toggle("旧收尾兼容", isOn: $qa.legacy)
                Toggle("检查未通过", isOn: $qa.unpassed).disabled(qa.legacy)
                Text("新邀请只锚定答题反馈；范围更新不生成、不推进、不改变编辑器焦点。")
                    .font(.caption).foregroundStyle(.secondary)
            }.controlSize(.small).padding(.horizontal, 8).padding(.bottom, 6)
            if qa.inbox {
                InboxView(onOpenSession: { selection = $0; qa.inbox = false }, onOpenCapture: { selection = $0; destination = $1; qa.inbox = false })
            } else if qa.showLibrary {
                LibraryView(selectedID: $qa.selectedKnowledge, coordinator: qa.coordinator)
            } else {
                LearningWorkspace(monitor: qa.monitor, selectedSessionID: $selection, captureDestination: destination,
                    onOpenKnowledge: { qa.selectedKnowledge = $0; qa.showLibrary = true },
                    onMessageSaved: { message, _ in qa.sent(message, session: session, context: context) })
            }
        }.frame(minWidth: 720, minHeight: 620)
            .preferredColorScheme(qa.dark ? .dark : .light).environment(\.brandTrialStill, qa.reduced)
            .onChange(of: qa.dark) { _, value in AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true) }
            .onChange(of: qa.legacy) { _, _ in qa.reset(session, context); destination = nil }
            .onChange(of: qa.unpassed) { _, _ in qa.reset(session, context); destination = nil }
            .onAppear {
                qa.dark = AppearanceController.shared.isDark; selection = session.id
                qa.monitor.useFixturePresentation(); if qa.offer == nil { qa.reset(session, context) }
                Task { @MainActor in
                    await Task.yield()
                    NSApp.setActivationPolicy(.regular)
                    NSApp.windows.first(where: \.isVisible)?.makeKeyAndOrderFront(nil)
                    NSApp.activate(ignoringOtherApps: true)
                }
            }
    }
}

@MainActor @Observable final class TopicQACapture: NSObject, SCRecordingOutputDelegate {
    enum CaptureError: Error { case windowUnavailable }
    var recording = false
    var stream: SCStream?
    var finished = false
    var folder: URL { URL(fileURLWithPath: ProcessInfo.processInfo.environment["REVIEW_TODAY_TOPIC_QA_OUTPUT"] ?? "/tmp/review-today-topic-qa-evidence", isDirectory: true) }
    func source() async throws -> (SCContentFilter, SCStreamConfiguration) {
        guard let w = NSApp.keyWindow ?? NSApp.windows.first(where: \.isVisible) else { throw CaptureError.windowUnavailable }
        let content = try await SCShareableContent.currentProcess
        guard let own = content.windows.first(where: { $0.windowID == CGWindowID(w.windowNumber) }) else { throw CaptureError.windowUnavailable }
        let config = SCStreamConfiguration(); config.width = Int(w.frame.width) / 2 * 2; config.height = Int(w.frame.height) / 2 * 2
        config.ignoreShadowsSingleWindow = true; config.minimumFrameInterval = CMTime(value: 1, timescale: 30)
        config.showsCursor = true; config.capturesAudio = false; config.captureMicrophone = false
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return (SCContentFilter(desktopIndependentWindow: own), config)
    }
    func snapshot() {
        Task { @MainActor in
            do {
                let (filter, config) = try await source()
                let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
                try NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent("native-\(Int(Date.now.timeIntervalSince1970)).png"))
            } catch { print("QA screenshot error: \(error)") }
        }
    }
    func toggle() {
        Task { @MainActor in
            do {
                if let stream { try await stream.stopCapture(); self.stream = nil; recording = false; return }
                let (filter, config) = try await source()
                let stream = SCStream(filter: filter, configuration: config, delegate: nil)
                let output = SCRecordingOutputConfiguration(); output.outputURL = folder.appendingPathComponent("native-\(Int(Date.now.timeIntervalSince1970)).mp4"); output.videoCodecType = .h264
                try stream.addRecordingOutput(SCRecordingOutput(configuration: output, delegate: self))
                self.stream = stream; recording = true; finished = false
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    DispatchQueue.global(qos: .userInitiated).async {
                        stream.startCapture { error in
                            if let error { continuation.resume(throwing: error) } else { continuation.resume() }
                        }
                    }
                }
            } catch { print("QA record error: \(error)"); recording = false; stream = nil }
        }
    }
    nonisolated func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) { Task { @MainActor in self.finished = true } }
    nonisolated func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: Error) { print("QA recording failed: \(error)") }
}
