import SwiftUI
import SwiftData

struct TopicCaptureOffer: Codable, Identifiable, Equatable {
    var id: UUID
    var version: Int
    var title: String
    var anchorMessageID: UUID
    var status: String
    var nextRequest: String
    var continuationConsumed: Bool
    var saveTaskID: UUID?
    var actionInputID: UUID?
    var error: String?
    var knowledgeIDs: [UUID]?
    enum CodingKeys: String, CodingKey {
        case id, version, title, status, error
        case anchorMessageID = "anchor_message_id", nextRequest = "next_request"
        case continuationConsumed = "continuation_consumed", saveTaskID = "save_task_id"
        case actionInputID = "action_input_id", knowledgeIDs = "knowledge_ids"
    }
    static func read(_ raw: String) -> [Self] {
        (try? JSONDecoder().decode([Self].self, from: Data(raw.utf8))) ?? []
    }
    var hasNext: Bool { !nextRequest.isEmpty && !continuationConsumed }
    var needsAttention: Bool { ["deferred", "failed"].contains(status) }
}

/// A transcript item: visual state is local; the versioned Harness offer owns writes.
struct TopicCapturePanel: View {
    let offer: TopicCaptureOffer
    var focused = false
    var enabled = true
    var persistenceError: String? = nil
    var deliveryError: String? = nil
    var onAction: (String) -> Bool
    var onOpenKnowledge: (UUID) -> Void
    @Environment(\.modelContext) private var context
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.runway) private var runway
    @State private var expanded = false
    @State private var initiated = false
    @State private var token = 0
    @State private var receivedIDs: [UUID] = []
    @State private var resourceFailed = false
    @AppStorage(KnowledgeIngestion.preferenceKey) private var seenFull = false
    private var saved: Bool { !receivedIDs.isEmpty || offer.status == "saved" }
    private var knowledgeIDs: [UUID] { receivedIDs.isEmpty ? offer.knowledgeIDs ?? [] : receivedIDs }
    private var outcome: String {
        if saved { return "saved" }
        if persistenceError != nil || deliveryError != nil || ["failed", "invalidated"].contains(offer.status) { return "failed" }
        if ["skipped", "dismissed", "deferred"].contains(offer.status) { return "cancelled" }
        return "processing"
    }
    private var title: String {
        if saved { return "已加入知识库" }
        if persistenceError != nil { return "本机保存尚未完成" }
        if deliveryError != nil { return "操作尚未送达" }
        switch offer.status {
        case "deferred": return "已放入待处理"
        case "saving": return "Mr. B 正在整理知识"
        case "failed": return "这次录入尚未完成"
        case "invalidated": return "内容已更新"
        case "skipped", "dismissed": return "本次已跳过录入"
        default: return "刚才的要点，要留下来吗？"
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text(title).font(.headline)
                    Text(offer.title).font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                if ["deferred", "dismissed"].contains(offer.status) {
                    Button(expanded ? "收起" : "查看") { expanded.toggle() }.controlSize(.small)
                }
            }
            if offer.hasNext && !saved { Text("之后：\(offer.nextRequest)").font(.caption).foregroundStyle(.secondary) }
            if initiated && !resourceFailed {
                MrBMotionView(configuration: .init(kind: "flow_study", token: token,
                    dark: colorScheme == .dark, reduced: reduced, visible: true,
                    compact: seenFull, flowOutcome: outcome, flowSignalToken: saved ? 1 : outcome == "processing" ? 0 : 2),
                    onEvent: { event in
                        if event == "failed" { resourceFailed = true }
                        if event == "finished", saved { if !reduced { seenFull = true }; initiated = false }
                    })
                    .frame(maxWidth: 504).frame(height: 240).accessibilityHidden(true)
            }
            if saved {
                HStack {
                    Text("\(knowledgeIDs.count) 张知识卡片").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if let id = knowledgeIDs.first { Button("查看知识") { onOpenKnowledge(id) } }
                }
            } else if offer.status == "saving" {
                Text(persistenceError == nil ? "正在保存已确认的内容…" : "正在重试本机保存，成功后再继续。").font(.caption).foregroundStyle(.secondary)
            } else if offer.status == "invalidated" {
                Text(offer.error ?? "请在新的话题收尾处确认内容。").font(.caption).foregroundStyle(.secondary)
            } else if offer.status == "offered" || offer.status == "failed" || (expanded && ["deferred", "dismissed"].contains(offer.status)) {
                if let error = deliveryError ?? (offer.status == "failed" ? offer.error : nil) { Text(error).font(.caption).foregroundStyle(.secondary) }
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 12) { actions }
                    VStack(alignment: .leading, spacing: 10) { actions }
                }.controlSize(.small).disabled(!enabled)
            }
            if resourceFailed { Text("动效暂不可用，保存状态不受影响。").font(.caption).foregroundStyle(.secondary) }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field, in: RoundedRectangle(cornerRadius: 14))
        .onAppear { if focused { expanded = true } }
        .onChange(of: focused) { _, value in if value { expanded = true } }
        .onChange(of: offer.status) { _, value in
            if ["deferred", "skipped", "dismissed", "invalidated"].contains(value) { initiated = false }
        }
        .onDisappear { initiated = false }
        .onReceive(NotificationCenter.default.publisher(for: .knowledgeIngestionSaved)) { note in
            guard let source = note.object as? ModelContext, source === context,
                  let receipt = note.userInfo?["receipt"] as? KnowledgeIngestionReceipt,
                  receipt.taskID == offer.saveTaskID || receipt.inputID == offer.actionInputID else { return }
            receivedIDs = receipt.knowledgeIDs
        }
    }
    @ViewBuilder private var actions: some View {
        Button(offer.status == "failed" ? "重试录入" : offer.hasNext ? "录入并继续" : "录入知识") {
            token += 1; resourceFailed = false
            initiated = onAction("capture_save")
        }.buttonStyle(.borderedProminent).tint(runway.ink)
        if offer.status != "deferred" {
            Button("稍后录入") { _ = onAction("capture_later") }
        }
        Button(offer.hasNext ? "跳过，继续" : "跳过") { _ = onAction("capture_skip") }
    }
}
