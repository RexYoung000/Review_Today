import AppKit
import SwiftUI
import SwiftData
import ScreenCaptureKit
import AVFoundation

/// Synthetic server outcomes, production transcript/buttons and real isolated SwiftData commit.
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
        container.mainContext.autosaveEnabled = false
        session = AgentSession(title: "话题收尾隔离验收")
        container.mainContext.insert(session); try! container.mainContext.save()
        print("QA isolated store: \(dir)"); fflush(stdout)
        if CommandLine.arguments.contains("--fixture-check") {
            let check = TopicQAState()
            check.checkFixture(session, container.mainContext)
            exit(0)
        }
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
    var holdProcessing = false
    var processingPhase = "idle"
    var actionCount = 0
    var receiptCount = 0
    var failureCount = 0
    var openKnowledgeCount = 0
    var offer: TopicCaptureOffer?
    var selectedKnowledge: UUID?
    var showLibrary = false
    var capture = TopicQACapture()
    var monitor = AgentServiceMonitor()
    var coordinator = ReviewCoordinator()
    var sequence = 0
    private var receiptObserver: NSObjectProtocol?
    private var automaticAdvance: Task<Void, Never>?
    private var cardIDsByOffer: [UUID: [UUID]] = [:]
    private var pendingSave: PendingSave?
    private struct PendingSave {
        let offerID: UUID
        let version: Int
        let task: LearningTask
        let ids: [UUID]
        let beforeIDs: Set<UUID>
        let receiptCount: Int
        let sequence: Int
        let previewPoints: [String]
        let previewSummary: String?
        let sourceText: String
    }
    enum Disk: Error { case simulatedFailure }
    func observeReceipts(_ session: AgentSession, _ context: ModelContext) {
        guard receiptObserver == nil else { return }
        receiptObserver = NotificationCenter.default.addObserver(forName: .knowledgeIngestionSaved, object: nil, queue: .main) { [weak self] note in
            MainActor.assumeIsolated {
                guard let self, let owner = note.object as? ModelContext, owner === context,
                      let receipt = note.userInfo?["receipt"] as? KnowledgeIngestionReceipt,
                      receipt.sessionID == session.id else { return }
                precondition(receipt.taskID == self.pendingSave?.task.id && receipt.inputID == self.pendingSave?.task.inputMessageID)
                let diskIDs = self.knowledgeIDs(ModelContext(context.container))
                precondition(!receipt.knowledgeIDs.isEmpty && Set(receipt.knowledgeIDs).isSubset(of: diskIDs), "a receipt must refer to cards already visible on disk")
                precondition(self.pendingSave?.task.memoryCommitted == true)
                self.receiptCount += 1
                self.record("durable_receipt", ["cards": receipt.knowledgeIDs.count, "receipts": self.receiptCount])
            }
        }
    }
    private func knowledgeIDs(_ context: ModelContext) -> Set<UUID> {
        Set((try! context.fetch(FetchDescriptor<Knowledge>())).map(\.id))
    }
    private func record(_ event: String, _ fields: [String: Any] = [:]) {
        var value = fields
        value["event"] = event; value["sequence"] = sequence
        value["phase"] = processingPhase; value["synthetic_backend"] = true
        value["daily_data_used"] = false
        print("QA " + String(data: try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]), encoding: .utf8)!)
        fflush(stdout)
    }
    func store(_ session: AgentSession, _ context: ModelContext) {
        session.captureOffersJSON = String(data: try! JSONEncoder().encode(offer.map { [$0] } ?? []), encoding: .utf8)!
        session.captureOffersRevision += 1; try! context.save()
    }
    func reset(_ session: AgentSession, _ context: ModelContext) {
        automaticAdvance?.cancel(); automaticAdvance = nil; pendingSave = nil
        sequence += 1; showLibrary = false; inbox = false; selectedKnowledge = nil
        processingPhase = "idle"; actionCount = 0; receiptCount = 0; failureCount = 0; openKnowledgeCount = 0
        let beforeIDs = knowledgeIDs(context)
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
            offer = unpassed ? nil : .init(id: UUID(), version: 1, title: "RAG 与微调的区别", anchorMessageID: feedback.id, status: "offered", nextRequest: "", continuationConsumed: true, trigger: "verified_check", scopeSummary: "RAG 先检索资料再生成回答；微调通过训练调整模型参数。",
                previewPoints: ["RAG 在回答前检索相关资料，为生成提供依据。", "微调通过训练调整模型参数，改变模型的行为。"],
                previewSummary: "RAG 借助外部资料回答，微调通过训练改变模型行为。")
        }
        store(session, context)
        precondition(knowledgeIDs(context) == beforeIDs, "showing an invitation must not create cards")
        record("reset", ["invitation": offer != nil, "cards_created": 0])
    }
    func refreshScope(_ session: AgentSession, _ context: ModelContext) {
        guard offer?.isCheckInvitation == true, ["offered", "deferred"].contains(offer?.status ?? "") else { return }
        let oldID = offer!.id, oldAnchor = offer!.anchorMessageID
        let beforeIDs = knowledgeIDs(context)
        offer?.version += 1
        offer?.scopeSummary = "RAG 先检索资料再生成回答；微调通过训练调整模型参数。检索资料不足时应说明限制。"
        offer?.previewPoints = ["RAG 在回答前检索相关资料，为生成提供依据。", "微调通过训练调整模型参数，改变模型的行为。", "检索资料不足时，应说明限制，不能把缺少依据的内容当作确定结论。"]
        offer?.previewSummary = "根据资料补充或行为调整的需求选择；资料不足时明确回答边界。"
        precondition(offer?.id == oldID && offer?.anchorMessageID == oldAnchor)
        store(session, context)
        precondition(knowledgeIDs(context) == beforeIDs && pendingSave == nil)
        record("scope_refreshed", ["version": offer!.version, "anchor_retained": true, "cards_created": 0])
    }
    func next(_ session: AgentSession, _ context: ModelContext) {
        guard offer?.hasNext == true else { return }
        offer?.continuationConsumed = true
        context.insert(AgentMessage(sessionID: session.id, role: "coach", content: "下面开始 Agent 的基本组成：模型负责判断，循环根据执行结果推进下一步。\n\n（隔离样例续讲，仅验证界面交接。）", deliveryStatus: "accepted"))
        record("explicit_continuation")
    }
    func sent(_ message: AgentMessage, session: AgentSession, context: ModelContext) {
        message.deliveryStatus = "accepted"
        guard let raw = message.operationJSON?.data(using: .utf8), let op = try? JSONSerialization.jsonObject(with: raw) as? [String: Any], let kind = op["kind"] as? String else {
            record("followup", ["capture_authorized": false])
            return
        }
        guard op["target_id"] as? String == offer?.id.uuidString.lowercased(), op["version"] as? Int == offer?.version else {
            message.deliveryStatus = "retryable_failed"; message.lastDeliveryError = "范围已更新，请使用当前邀请。"; try! context.save()
            record("stale_version_rejected"); return
        }
        actionCount += 1
        record("bound_action", ["kind": kind, "version": offer!.version, "review_requested": message.reviewRequested])
        if kind == "capture_later" || kind == "capture_skip" {
            let beforeIDs = knowledgeIDs(context), priorReceipts = receiptCount
            offer?.status = kind == "capture_later" ? "deferred" : "skipped"
            processingPhase = offer!.status; next(session, context); store(session, context)
            precondition(knowledgeIDs(context) == beforeIDs && receiptCount == priorReceipts)
            record("capture_deferred_or_skipped", ["status": offer!.status, "cards_created": 0, "success_receipt": false])
            return
        }
        guard kind == "capture_save" else { return }
        guard pendingSave == nil, ["offered", "deferred", "failed"].contains(offer?.status ?? "") else {
            record("duplicate_save_ignored", ["cards_created": 0]); return
        }
        let existing = (try? context.fetch(FetchDescriptor<LearningTask>()))?.first(where: { $0.id == offer?.saveTaskID })
        let task = existing ?? LearningTask(sessionID: session.id, inputMessageID: message.id)
        task.inputMessageID = message.id
        task.mode = "memory_organization"; task.status = "running"; task.stage = "memory_generation"; task.errorCode = nil; task.conversationManaged = true
        if existing == nil { context.insert(task) }
        offer?.status = "saving"; offer?.actionInputID = message.id; offer?.saveTaskID = task.id; offer?.error = nil
        let ids = cardIDsByOffer[offer!.id] ?? [UUID(), UUID()]
        cardIDsByOffer[offer!.id] = ids
        let points = offer!.visiblePreviewPoints
        let summary = offer!.visiblePreviewSummary
        let sourceText = (points + (summary.map { [$0] } ?? [])).joined(separator: "\n")
        pendingSave = PendingSave(offerID: offer!.id, version: offer!.version, task: task, ids: ids,
            beforeIDs: knowledgeIDs(context), receiptCount: receiptCount, sequence: sequence,
            previewPoints: points, previewSummary: summary,
            sourceText: sourceText.isEmpty ? "检索找到相关资料，生成依据资料组织回答。" : sourceText)
        processingPhase = "memory_generation"
        store(session, context)
        record("generation_started", ["cards_created": 0, "generation_is_simulated": true])
        scheduleAdvance(session, context)
    }
    func scheduleAdvance(_ session: AgentSession, _ context: ModelContext) {
        automaticAdvance?.cancel(); automaticAdvance = nil
        guard !holdProcessing, let work = pendingSave else { return }
        automaticAdvance = Task { @MainActor in
            do { try await Task.sleep(for: .seconds(3)) } catch { return }
            guard !holdProcessing, sequence == work.sequence else { return }
            advance(session, context)
        }
    }
    private func syntheticPayload(_ work: PendingSave) throws -> AgentAPI.ExtractPayload {
        var payload = try KnowledgeIngestionFixture.payload(work.ids)
        guard !work.previewPoints.isEmpty else { return payload }
        // A deterministic post-click generation stand-in; not proof of model quality.
        for index in payload.knowledge.indices {
            let points = index == 0 ? [work.previewPoints[0]] + Array(work.previewPoints.dropFirst(2))
                : Array(work.previewPoints.dropFirst().prefix(1))
            payload.knowledge[index].title = index == 0 ? "RAG 的检索依据与回答边界" : "微调如何调整模型行为"
            payload.knowledge[index].theme = "RAG 与微调"
            payload.knowledge[index].learningGoal = index == 0 ? "说明 RAG 检索资料的作用与资料不足的限制" : "说明微调对模型参数与行为的影响"
            payload.knowledge[index].explanation = points.joined(separator: "\n") + "\n\n" + (work.previewSummary ?? "")
            payload.knowledge[index].evidenceExcerpt = points.joined(separator: "\n")
        }
        return payload
    }
    func advance(_ session: AgentSession, _ context: ModelContext) {
        automaticAdvance?.cancel(); automaticAdvance = nil
        guard let work = pendingSave, sequence == work.sequence,
              offer?.id == work.offerID, offer?.version == work.version else { return }
        if processingPhase == "memory_generation" {
            precondition(knowledgeIDs(context) == work.beforeIDs && receiptCount == work.receiptCount)
            work.task.stage = "committing"; work.task.status = "committing"
            processingPhase = "committing"; store(session, context)
            record("local_save_started", ["cards_created": 0, "success_receipt": false])
            scheduleAdvance(session, context); return
        }
        guard processingPhase == "committing" else { return }
        do {
            let ids = try HarnessProcessor.persistMemory(syntheticPayload(work), sourceText: work.sourceText, task: work.task, context: context, save: fail ? { throw Disk.simulatedFailure } : nil)
            precondition(ids == work.ids && receiptCount == work.receiptCount + 1)
            let disk = ModelContext(context.container)
            precondition(knowledgeIDs(disk).subtracting(work.beforeIDs) == Set(work.ids), "one action writes only its expected cards")
            let savedCards = (try! disk.fetch(FetchDescriptor<Knowledge>())).filter { work.ids.contains($0.id) }
            precondition(savedCards.allSatisfy { $0.source?.rawText == work.sourceText }, "save uses the source frozen by this version's click")
            let input = (try! context.fetch(FetchDescriptor<AgentMessage>())).first { $0.id == work.task.inputMessageID }
            precondition(savedCards.allSatisfy { $0.participatesInReview == (input?.reviewRequested == true) })
            work.task.status = "completed"; work.task.stage = "completed"
            offer?.status = "saved"; offer?.knowledgeIDs = ids; processingPhase = "saved"
            next(session, context)
            record("commit_completed", ["cards": ids.count, "receipt_verified": true, "generation_is_simulated": true])
        } catch {
            precondition(receiptCount == work.receiptCount && !work.task.memoryCommitted)
            precondition(knowledgeIDs(ModelContext(context.container)) == work.beforeIDs, "failed local save must not leave cards on disk")
            work.task.status = "retryable_failed"; work.task.errorCode = "隔离测试：模拟本机写入失败，请重试。"
            offer?.status = "failed"; offer?.error = work.task.errorCode
            processingPhase = "failed"; failureCount += 1
            record("commit_failed", ["cards_created": 0, "success_receipt": false, "retry_available": true])
        }
        pendingSave = nil; store(session, context)
    }
    func openKnowledge(_ id: UUID, session: AgentSession, context: ModelContext) {
        precondition(offer?.status == "saved" && offer?.knowledgeIDs?.contains(id) == true)
        precondition(knowledgeIDs(ModelContext(context.container)).contains(id), "view callback must target a durably saved card")
        selectedKnowledge = id; showLibrary = true; openKnowledgeCount += 1
        record("open_knowledge_callback", ["target_in_saved_receipt": true, "card_on_disk": true, "callbacks": openKnowledgeCount])
    }
    /// Exercises the QA driver itself; the production buttons still need native interaction checks.
    func checkFixture(_ session: AgentSession, _ context: ModelContext) {
        holdProcessing = true; observeReceipts(session, context); reset(session, context)
        let beforeIDs = knowledgeIDs(ModelContext(context.container))
        let initial = offer!
        precondition(initial.visiblePreviewPoints.count == 2 && initial.visiblePreviewSummary != nil)
        refreshScope(session, context)
        let preview = offer!
        precondition(preview.id == initial.id && preview.anchorMessageID == initial.anchorMessageID && preview.version == 2)
        precondition(preview.visiblePreviewPoints.count == 3 && preview.visiblePreviewSummary != initial.visiblePreviewSummary)
        precondition(knowledgeIDs(ModelContext(context.container)) == beforeIDs && receiptCount == 0)
        func action(_ kind: String) {
            let message = AgentMessage(sessionID: session.id, role: "user", content: "隔离状态检查", deliveryStatus: "accepted")
            precondition(!message.reviewRequested, "saving a preview does not opt into review")
            message.operationJSON = String(data: try! JSONSerialization.data(withJSONObject: offer!.boundOperation(kind)), encoding: .utf8)
            context.insert(message); try! context.save()
            sent(message, session: session, context: context)
        }
        action("capture_later")
        precondition(offer?.status == "deferred" && pendingSave == nil && receiptCount == 0)
        precondition(offer?.visiblePreviewPoints == preview.visiblePreviewPoints && offer?.visiblePreviewSummary == preview.visiblePreviewSummary)
        fail = true; action("capture_save")
        precondition(processingPhase == "memory_generation" && pendingSave?.task.stage == "memory_generation")
        advance(session, context)
        precondition(processingPhase == "committing" && offer?.status == "saving" && receiptCount == 0)
        advance(session, context)
        precondition(offer?.status == "failed" && failureCount == 1 && receiptCount == 0)
        precondition(offer?.visiblePreviewPoints == preview.visiblePreviewPoints && offer?.visiblePreviewSummary == preview.visiblePreviewSummary)
        precondition(knowledgeIDs(ModelContext(context.container)) == beforeIDs)
        fail = false; action("capture_save"); advance(session, context); advance(session, context)
        precondition(offer?.status == "saved" && receiptCount == 1 && pendingSave == nil)
        precondition(offer?.visiblePreviewPoints == preview.visiblePreviewPoints && offer?.visiblePreviewSummary == preview.visiblePreviewSummary,
                     "real saved results retain the content preview")
        let savedIDs = knowledgeIDs(ModelContext(context.container))
        precondition(savedIDs.subtracting(beforeIDs).count == 2)
        let resultIDs = offer!.knowledgeIDs!
        precondition(resultIDs.count == 2 && Set(resultIDs).isSubset(of: savedIDs))
        let results = try! ModelContext(context.container).fetch(FetchDescriptor<Knowledge>())
        precondition(results.first { $0.id == resultIDs[0] }?.explanation.contains("检索资料不足") == true,
                     "the simulated generated card contains the newly selected same-point boundary")
        precondition(results.filter { resultIDs.contains($0.id) }.allSatisfy { !$0.participatesInReview })
        for (index, id) in resultIDs.enumerated() {
            showLibrary = false; selectedKnowledge = nil
            openKnowledge(id, session: session, context: context)
            precondition(showLibrary && selectedKnowledge == id && openKnowledgeCount == index + 1,
                         "every actual saved result can target its own knowledge detail")
        }
        action("capture_save")
        precondition(knowledgeIDs(ModelContext(context.container)) == savedIDs && receiptCount == 1)
        reset(session, context); action("capture_save"); reset(session, context); advance(session, context)
        precondition(knowledgeIDs(ModelContext(context.container)) == savedIDs && receiptCount == 0 && pendingSave == nil)
        print("PASS: structured preview/same-point version refresh without writes, isolated QA phases, deferred/failed/saved preview retention, failed rollback, retry receipt/frozen source, both saved-result detail callbacks, review default off, duplicate/reset fencing; production UI interaction not exercised")
        fflush(stdout)
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
                Toggle("暂停处理", isOn: $qa.holdProcessing)
                Button("推进一步") { qa.advance(session, context) }.disabled(!["memory_generation", "committing"].contains(qa.processingPhase))
                if qa.showLibrary { Button("返回对话") { qa.showLibrary = false } }
            }.controlSize(.small).padding(.horizontal, 8).padding(.bottom, 6)
            Text("QA 阶段：\(qa.processingPhase) · 操作 \(qa.actionCount) · 回执 \(qa.receiptCount) · 失败 \(qa.failureCount) · 查看回调 \(qa.openKnowledgeCount)；生成使用合成载荷，保存使用隔离本机数据库。")
                .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 8).padding(.bottom, 6)
            if qa.inbox {
                InboxView(onOpenSession: { selection = $0; qa.inbox = false }, onOpenCapture: { selection = $0; destination = $1; qa.inbox = false })
            } else if qa.showLibrary {
                LibraryView(selectedID: $qa.selectedKnowledge, coordinator: qa.coordinator)
            } else {
                LearningWorkspace(monitor: qa.monitor, selectedSessionID: $selection, captureDestination: destination,
                    onOpenKnowledge: { qa.openKnowledge($0, session: session, context: context) },
                    onMessageSaved: { message, _ in qa.sent(message, session: session, context: context) })
            }
        }.frame(minWidth: 720, minHeight: 620)
            .preferredColorScheme(qa.dark ? .dark : .light).environment(\.brandTrialStill, qa.reduced)
            .onChange(of: qa.dark) { _, value in AppearanceController.shared.setDark(value, screenPoint: nil, reduceMotion: true) }
            .onChange(of: qa.legacy) { _, _ in qa.reset(session, context); destination = nil }
            .onChange(of: qa.unpassed) { _, _ in qa.reset(session, context); destination = nil }
            .onChange(of: qa.holdProcessing) { _, _ in qa.scheduleAdvance(session, context) }
            .onAppear {
                qa.observeReceipts(session, context)
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
