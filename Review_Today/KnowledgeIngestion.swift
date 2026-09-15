import AppKit
import SwiftUI
import SwiftData

struct KnowledgeIngestionReceipt {
    let taskID: UUID
    let inputID: UUID
    let sessionID: UUID
    let knowledgeIDs: [UUID]
}

extension Notification.Name {
    static let knowledgeIngestionSaved = Notification.Name("reviewToday.knowledgeIngestionSaved")
}

/// Ephemeral window-owned eligibility. Nothing replays from persisted history.
@MainActor @Observable
final class KnowledgeIngestion {
    static let preferenceKey = "reviewToday.seenParagraphIngestionV1"
    var presented = false
    private(set) var outcome = "idle"
    private(set) var token = 0
    private(set) var signalToken = 0
    private(set) var compact = false
    private(set) var knowledgeIDs: [UUID] = []
    private(set) var inputID: UUID?
    private(set) var sessionID: UUID?
    var resourceFailed = false
    private var finished = false
    private var inputs: [UUID: UUID] = [:]
    private var consumed = Set<UUID>()
    var tracking: Bool { !inputs.isEmpty }
    var saved: Bool { outcome == "saved" }

    func register(input: UUID, session: UUID, explicitSave: Bool, eligible: Bool, compact: Bool) {
        guard eligible, explicitSave else { return }
        if inputs.count >= 64 { inputs.removeAll() }
        inputs[input] = session
        if explicitSave { begin(input: input, compact: compact, eligible: eligible) }
    }
    private func begin(input: UUID, compact: Bool, eligible: Bool) {
        guard let session = inputs[input], inputID != input else { return }
        // Do not queue an animation behind another operation or a modal.
        guard eligible, !presented else { inputs.removeValue(forKey: input); return }
        inputID = input; sessionID = session; token += 1
        self.compact = compact; outcome = "processing"; knowledgeIDs = []
        presented = true; finished = false; resourceFailed = false
    }
    func receive(_ receipt: KnowledgeIngestionReceipt, eligible: Bool, compact: Bool) {
        guard !receipt.knowledgeIDs.isEmpty, !consumed.contains(receipt.taskID),
              (inputs[receipt.inputID] == receipt.sessionID || (inputID == receipt.inputID && sessionID == receipt.sessionID)) else { return }
        consumed.insert(receipt.taskID)
        if inputID != receipt.inputID { begin(input: receipt.inputID, compact: compact, eligible: eligible) }
        guard inputID == receipt.inputID, ["processing", "failed", "cancelled"].contains(outcome) else { return }
        if outcome != "processing" { token += 1 }
        knowledgeIDs = Array(Set(receipt.knowledgeIDs)).sorted { $0.uuidString < $1.uuidString }
        outcome = "saved"; signalToken += 1
        inputs.removeValue(forKey: receipt.inputID)
    }
    func stop(input: UUID, cancelled: Bool) {
        inputs.removeValue(forKey: input)
        guard inputID == input, outcome == "processing" else { return }
        outcome = cancelled ? "cancelled" : "failed"; signalToken += 1
    }
    func dismiss() { presented = false }
    func leaveContext() { presented = false; inputs.removeAll(); inputID = nil; sessionID = nil }
    func changeSession(to session: UUID?) {
        inputs = inputs.filter { $0.value == session }
        if sessionID != session { presented = false; inputID = nil; sessionID = nil }
    }
    func replay() {
        guard saved else { return }
        compact = false; token += 1; signalToken += 1; finished = false; resourceFailed = false
    }
    func finish(reduced: Bool, foreground: Bool) -> Bool {
        guard !finished else { return false }
        finished = true
        return saved && presented && !compact && !reduced && foreground && !resourceFailed
    }

    func refresh(context: ModelContext, eligible: Bool, compact: Bool) {
        guard tracking else { return }
        guard let tasks = try? context.fetch(FetchDescriptor<LearningTask>()),
              let runs = try? context.fetch(FetchDescriptor<AgentRun>()),
              let messages = try? context.fetch(FetchDescriptor<AgentMessage>()),
              let sessions = try? context.fetch(FetchDescriptor<AgentSession>()) else { return }
        for (input, sid) in inputs {
            guard sessions.contains(where: { $0.id == sid && $0.status == "active" }) else {
                stop(input: input, cancelled: true); continue
            }
            let run = runs.last { run in
                run.sessionID == sid && ((try? JSONDecoder().decode([UUID].self, from: Data(run.inputMessageIDsJSON.utf8))) ?? []).contains(input)
            }
            let task = tasks.first { $0.sessionID == sid && $0.mode == "memory_organization" && ($0.inputMessageID == input || $0.id == run?.taskID) }
            // Only an explicitly registered save can own an ingestion presentation.
            // A persisted success is delivered separately, exactly after ModelContext.save.
            // Acknowledgement/network failures after that boundary never undo the result.
            if task?.memoryCommitted == true { continue }
            let status = task?.status ?? run?.status ?? ""
            if ["cancelled", "interrupted", "stopping", "paused"].contains(status) {
                stop(input: input, cancelled: true)
            } else if ["retryable_failed", "terminal_failed", "needs_attention"].contains(status) || task?.errorCode != nil || run?.errorCode != nil {
                stop(input: input, cancelled: false)
            } else if status == "completed" || messages.first(where: { $0.id == input })?.lastDeliveryError != nil {
                // Refused/stale save consent or an ordinary completed answer is not a save.
                stop(input: input, cancelled: status == "completed")
            }
        }
    }
}

struct KnowledgeIngestionSheet: View {
    @Bindable var ingestion: KnowledgeIngestion
    var onOpenKnowledge: (UUID) -> Void
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.runway) private var runway
    @AppStorage(KnowledgeIngestion.preferenceKey) private var seenFull = false
    private var title: LocalizedStringKey {
        switch ingestion.outcome {
        case "saved": "已加入知识库"
        case "failed": "这次整理尚未完成"
        case "cancelled": "整理已暂停"
        default: "Mr. B 正在整理知识"
        }
    }
    var body: some View {
        let token = ingestion.token
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.title2.bold())
                    Text(ingestion.saved ? "整理好了。这部分，值得记住。" : "整理状态与结果会保留在会话中。")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Button { ingestion.dismiss() } label: { Image(systemName: "xmark").frame(width: 28, height: 28) }
                    .buttonStyle(.plain).help("关闭演出").accessibilityLabel("关闭演出").keyboardShortcut(.cancelAction)
            }
            ZStack {
                MrBMotionView(configuration: .init(kind: "flow_study", token: token,
                    dark: colorScheme == .dark, reduced: reduced, visible: ingestion.presented,
                    compact: ingestion.compact, flowOutcome: ingestion.outcome, flowSignalToken: ingestion.signalToken),
                    onEvent: { event in
                        guard token == ingestion.token else { return }
                        if event == "failed" { ingestion.resourceFailed = true }
                        if event == "ready" { ingestion.resourceFailed = false }
                        if event == "finished", ingestion.finish(reduced: reduced, foreground: NSApp.isActive) { seenFull = true }
                    })
                    .opacity(ingestion.resourceFailed ? 0 : 1).accessibilityHidden(true)
                if ingestion.resourceFailed {
                    VStack(spacing: 12) {
                        Image(systemName: ingestion.saved ? "rectangle.stack" : "doc.text").font(.system(size: 44)).foregroundStyle(.secondary)
                        Text("动效暂不可用，处理状态不受影响。").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }.frame(width: 504, height: 270)
            Spacer(minLength: 0)
            VStack(spacing: 10) {
                if ingestion.saved {
                    HStack {
                        Label("\(ingestion.knowledgeIDs.count) 张知识卡片", systemImage: "rectangle.stack")
                        Spacer()
                        Button { ingestion.replay() } label: { Image(systemName: "arrow.counterclockwise") }
                            .buttonStyle(.borderless).help("完整重播").accessibilityLabel("完整重播")
                    }.font(.caption)
                    HStack {
                        Button("查看知识") {
                            guard let id = ingestion.knowledgeIDs.first else { return }
                            ingestion.dismiss(); onOpenKnowledge(id)
                        }
                        Spacer()
                        Button("完成") { ingestion.dismiss() }.buttonStyle(.borderedProminent).tint(runway.ink).keyboardShortcut(.defaultAction)
                    }
                } else {
                    HStack {
                        Text(ingestion.outcome == "processing" ? "可以关闭此窗口，继续处理其他内容。" : "请返回会话查看原因、补充内容或重试。")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button("返回会话") { ingestion.dismiss() }
                    }
                }
            }.frame(height: 66)
        }
        .padding(28).frame(width: 560, height: 490).background(PaperSurface())
    }
}
