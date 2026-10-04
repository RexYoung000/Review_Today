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
    var trigger: String?
    var scopeSummary: String?
    var previewPoints: [String]?
    var previewSummary: String?
    enum CodingKeys: String, CodingKey {
        case id, version, title, status, error
        case anchorMessageID = "anchor_message_id", nextRequest = "next_request"
        case continuationConsumed = "continuation_consumed", saveTaskID = "save_task_id"
        case actionInputID = "action_input_id", knowledgeIDs = "knowledge_ids"
        case trigger, scopeSummary = "scope_summary"
        case previewPoints = "preview_points", previewSummary = "preview_summary"
    }
    static func read(_ raw: String) -> [Self] {
        (try? JSONDecoder().decode([Self].self, from: Data(raw.utf8))) ?? []
    }
    var hasNext: Bool { !nextRequest.isEmpty && !continuationConsumed }
    var needsAttention: Bool { ["deferred", "failed"].contains(status) }
    var isCheckInvitation: Bool { trigger == "verified_check" }
    var visibleScope: String? {
        let value = scopeSummary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty || value == title.trimmingCharacters(in: .whitespacesAndNewlines) ? nil : value
    }
    var visiblePreviewPoints: [String] {
        var seen = Set<String>()
        return (previewPoints ?? []).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0).inserted }
    }
    var visiblePreviewSummary: String? {
        let value = previewSummary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? nil : value
    }
    func boundOperation(_ kind: String) -> [String: Any] {
        ["kind": kind, "target_id": id.uuidString.lowercased(), "version": version, "selection": [String]()]
    }

    /// Keep a queued action visible across transcript remounts, without creating another input.
    func pendingOperation(for message: AgentMessage?, runStatus: String? = nil) -> String? {
        guard let message, message.deliveryStatus != "held",
              let action = ConversationProcessor.object(message.operationJSON),
              action["target_id"] as? String == id.uuidString.lowercased(),
              action["version"] as? Int == version,
              let kind = action["kind"] as? String,
              ["capture_save", "capture_later"].contains(kind),
              ["offered", "failed", "deferred", "dismissed"].contains(status) else { return nil }
        if message.deliveryStatus != "local", let runStatus,
           ["interrupted", "cancelled", "completed", "retryable_failed", "terminal_failed"].contains(runStatus) { return nil }
        if kind == "capture_later", status == "deferred" { return nil }
        if kind == "capture_save", message.id == actionInputID { return nil }
        return kind
    }
}

/// Only live, successful local receipts can introduce a completion cue. History stays still.
/// Shared across transcript remounts so an ACK retry cannot replay the same save.
@MainActor @Observable
final class KnowledgeInvitationAttention {
    static let shared = KnowledgeInvitationAttention()
    private var consumed = Set<UUID>()
    private var unread = Set<UUID>()
    private var expected: [UUID: Int] = [:]

    func register(_ offer: TopicCaptureOffer) {
        guard offer.isCheckInvitation, offer.saveTaskID.map({ !consumed.contains($0) }) ?? true else { return }
        expected[offer.id] = offer.version
    }
    func cancel(_ offerID: UUID) { expected.removeValue(forKey: offerID) }

    func receive(_ receipt: KnowledgeIngestionReceipt, offer: TopicCaptureOffer, eligible: Bool, reduced: Bool) -> Bool {
        guard offer.isCheckInvitation, !receipt.knowledgeIDs.isEmpty,
              receipt.taskID == offer.saveTaskID || receipt.inputID == offer.actionInputID,
              consumed.insert(receipt.taskID).inserted else { return false }
        guard expected[offer.id] == offer.version else { return false }
        expected.removeValue(forKey: offer.id)
        unread.formUnion(receipt.knowledgeIDs)
        return eligible && !reduced
    }
    func isUnread(_ id: UUID) -> Bool { unread.contains(id) }
    func viewed(_ id: UUID) { unread.remove(id) }
}

/// A transcript item: visual state is local; the versioned Harness offer owns writes.
struct TopicCapturePanel: View {
    let offer: TopicCaptureOffer
    var focused = false
    var enabled = true
    var persistenceError: String? = nil
    var deliveryError: String? = nil
    var processingStage: String? = nil
    var pendingOperation: String? = nil
    var operationNotice: String? = nil
    var onAction: (String) -> Bool
    var onOpenKnowledge: (UUID) -> Void
    @Environment(\.modelContext) private var context
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.runway) private var runway
    @Environment(\.controlActiveState) private var controlState
    @Environment(\.scenePhase) private var scenePhase
    @State private var expanded = false
    @State private var enrollReview = false
    @State private var initiated = false
    @State private var token = 0
    @State private var receivedIDs: [UUID] = []
    @State private var resourceFailed = false
    @State private var pendingClick: String?
    @State private var visible = false
    @State private var completionCue = 0
    @State private var attention = KnowledgeInvitationAttention.shared
    @AppStorage(KnowledgeIngestion.preferenceKey) private var seenFull = false
    private var saved: Bool { !receivedIDs.isEmpty || offer.status == "saved" }
    private var compactInvitation: Bool {
        offer.isCheckInvitation && offer.status == "offered" && persistenceError == nil && deliveryError == nil
    }
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
        default: return offer.isCheckInvitation ? offer.title : "刚才的要点，要留下来吗？"
        }
    }
    var body: some View {
        Group {
            if offer.isCheckInvitation { invitationCard }
            else { legacyPanel }
        }
        .onAppear {
            visible = true
            if focused { expanded = true }
            if offer.status == "saving" || pendingOperation == "capture_save" { attention.register(offer) }
        }
        .onChange(of: focused) { _, value in if value { expanded = true } }
        .onChange(of: offer.status) { _, value in
            pendingClick = nil
            if value == "saving" { attention.register(offer) }
            if ["deferred", "skipped", "dismissed", "invalidated", "failed"].contains(value) {
                initiated = false; attention.cancel(offer.id)
            }
        }
        .onChange(of: offer.version) { _, _ in pendingClick = nil; attention.cancel(offer.id) }
        .onChange(of: pendingOperation) { _, value in
            pendingClick = nil
            if value == "capture_save" { attention.register(offer) }
        }
        .onChange(of: deliveryError) { _, _ in pendingClick = nil }
        .onDisappear {
            visible = false; initiated = false; pendingClick = nil; completionCue = 0
            attention.cancel(offer.id)
        }
        .onChange(of: controlState) { _, state in if state != .key { completionCue = 0 } }
        .onChange(of: reduced) { _, value in if value { completionCue = 0 } }
        .onChange(of: scenePhase) { _, value in if value != .active { completionCue = 0 } }
        .onReceive(NotificationCenter.default.publisher(for: .knowledgeIngestionSaved)) { note in
            guard let source = note.object as? ModelContext, source === context,
                  let receipt = note.userInfo?["receipt"] as? KnowledgeIngestionReceipt,
                  receipt.taskID == offer.saveTaskID || receipt.inputID == offer.actionInputID else { return }
            receivedIDs = receipt.knowledgeIDs
            if attention.receive(receipt, offer: offer,
                                 eligible: visible && controlState == .key && scenePhase == .active,
                                 reduced: reduced) { completionCue += 1 }
        }
    }

    private var waitingOperation: String? { pendingOperation ?? pendingClick }
    private var invitationBusy: Bool { !saved && (offer.status == "saving" || waitingOperation != nil) }
    private var invitationStatus: String {
        if saved { return knowledgeIDs.count > 1 ? "已保存 \(knowledgeIDs.count) 张知识卡" : "已保存" }
        if persistenceError != nil { return "保存尚未完成" }
        if deliveryError != nil && waitingOperation != nil { return "等待连接" }
        if let waitingOperation { return waitingOperation == "capture_later" ? "正在放入待处理" : "等待开始整理" }
        switch offer.status {
        case "saving": return processingStage == "committing" ? "正在保存" : "正在整理知识"
        case "deferred": return "已放入待处理"
        case "failed": return "保存未完成"
        case "invalidated": return "内容已更新"
        case "skipped", "dismissed": return "已跳过"
        default: return "未保存"
        }
    }
    private var invitationSymbol: String {
        if saved { return "checkmark.rectangle.stack" }
        if offer.status == "deferred" { return "tray" }
        if persistenceError != nil || offer.status == "failed" { return "exclamationmark.circle" }
        return "square.stack"
    }
    private var invitationCanAct: Bool {
        !saved && !invitationBusy && (["offered", "failed", "deferred"].contains(offer.status)
            || expanded && offer.status == "dismissed")
    }

    private var invitationCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Image(systemName: "note.text").font(.system(size: 15)).foregroundStyle(runway.copy).accessibilityHidden(true)
                Text(offer.title).font(.title3.weight(.semibold))
                    .foregroundStyle(runway.ink).fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
            }
            invitationContent
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { invitationState; Spacer(minLength: 12); invitationControls }
                VStack(alignment: .leading, spacing: 8) {
                    invitationState
                    HStack { Spacer(minLength: 0); invitationControls }
                }
            }
            if invitationCanAct { invitationReview.disabled(!enabled) }
            if saved && knowledgeIDs.count > 1 { savedInvitation }
            if !saved, let note = invitationNote {
                Text(note).font(.caption).foregroundStyle(runway.copy)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(20)
        .frame(maxWidth: 520, alignment: .leading)
        .background(runway.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous).strokeBorder(runway.hairline, lineWidth: 1))
        .shadow(color: runway.liftShadow.opacity(0.25), radius: 6, y: 2)
        .accessibilityIdentifier("knowledge-invitation-\(offer.id.uuidString)")
    }

    @ViewBuilder private var invitationContent: some View {
        let points = offer.visiblePreviewPoints
        if !points.isEmpty, let summary = offer.visiblePreviewSummary {
            VStack(alignment: .leading, spacing: 9) {
                ForEach(Array(points.enumerated()), id: \.offset) { _, point in
                    HStack(alignment: .firstTextBaseline, spacing: 9) {
                        Text("•").foregroundStyle(runway.copy).accessibilityHidden(true)
                        Text(point).foregroundStyle(runway.ink)
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(point)
                    .id(point)
                }
            }.font(.body.weight(.regular)).lineSpacing(5)
            HStack(alignment: .top, spacing: 11) {
                Rectangle().fill(runway.hairline).frame(width: 2)
                VStack(alignment: .leading, spacing: 4) {
                    Text("一句话记住").font(.caption).foregroundStyle(runway.copy)
                    Text(summary).font(.body.weight(.regular)).foregroundStyle(runway.ink)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled).id(summary)
                }
            }.fixedSize(horizontal: false, vertical: true)
        } else if let scope = offer.visibleScope {
            // Older offers retain their exact scope; the display never invents bullet points.
            Text(scope).font(.body.weight(.regular)).lineSpacing(4).foregroundStyle(runway.ink)
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true).id(scope)
        }
    }

    private var invitationState: some View {
        HStack(spacing: 5) {
            if saved { Image(systemName: "checkmark").accessibilityHidden(true) }
            if invitationBusy && !reduced && deliveryError == nil && persistenceError == nil {
                ProgressView().controlSize(.mini).accessibilityHidden(true)
            }
            Text(invitationStatus).fixedSize(horizontal: false, vertical: true)
        }.font(.caption).foregroundStyle(runway.copy).accessibilityElement(children: .combine)
    }

    @ViewBuilder private var invitationControls: some View {
        if saved, knowledgeIDs.count == 1, let id = knowledgeIDs.first {
            knowledgeDetailButton(id, title: "查看详情")
        } else if invitationCanAct {
            HStack(spacing: 8) { invitationActions }.disabled(!enabled)
        } else if offer.status == "dismissed" && !invitationBusy {
            Button("查看") { expanded = true }.buttonStyle(.borderless).controlSize(.small)
        }
    }

    private var invitationNote: String? {
        if persistenceError != nil { return "本机保存暂未完成，内容已保留，恢复后继续。" }
        if deliveryError != nil && waitingOperation != nil { return "操作已保留，连接恢复后继续。" }
        if offer.status == "failed" { return offer.error ?? "内容已保留，可以重试。" }
        if offer.status == "invalidated" { return offer.error ?? "请使用更新后的知识建议。" }
        if waitingOperation == nil && offer.status != "saving" { return operationNotice }
        return nil
    }

    private var invitationReview: some View {
        Toggle("已学过，加入复习", isOn: $enrollReview)
            .toggleStyle(.checkbox).font(.caption).foregroundStyle(runway.copy).controlSize(.small)
    }

    @ViewBuilder private var invitationActions: some View {
        if offer.status != "deferred" {
            Button("稍后") { submitInvitation("capture_later") }
                .buttonStyle(.borderless).foregroundStyle(runway.copy).controlSize(.small)
        }
        Button(offer.status == "failed" ? "重试保存" : offer.status == "deferred" ? "继续保存" : "保存为知识卡") {
            submitInvitation(enrollReview ? "capture_save_review" : "capture_save")
        }.buttonStyle(.borderedProminent).tint(runway.ink).controlSize(.small)
    }

    private func submitInvitation(_ operation: String) {
        guard enabled, !invitationBusy else { return }
        // Set the immediate state before the callback; a synchronous fixture may already publish the next state.
        pendingClick = operation == "capture_save_review" ? "capture_save" : operation
        if pendingClick == "capture_save" { attention.register(offer) }
        if !onAction(operation) { pendingClick = nil; attention.cancel(offer.id) }
    }

    private var savedInvitation: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(knowledgeIDs.enumerated()), id: \.element) { index, id in
                knowledgeDetailButton(id, title: savedKnowledgeTitle(id) ?? "知识卡 \(index + 1)")
            }
        }
    }

    private func knowledgeDetailButton(_ id: UUID, title: String) -> some View {
        Button {
            attention.viewed(id); completionCue = 0
            onOpenKnowledge(id)
        } label: {
            HStack(spacing: 8) {
                Text(title).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                Image(systemName: "arrow.right").font(.caption).accessibilityHidden(true)
            }.font(.callout).foregroundStyle(runway.ink)
        }
        .buttonStyle(InteractionButtonStyle(padding: 7, outline: .rounded(8)))
        .background(attention.isUnread(id) ? runway.field : .clear, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(attention.isUnread(id) ? runway.hairline : .clear, lineWidth: 1).allowsHitTesting(false))
        .modifier(KnowledgeCompletionLight(token: knowledgeIDs.first == id ? completionCue : 0))
        .accessibilityLabel(knowledgeIDs.count == 1 ? "查看知识卡详情" : "查看知识卡详情：\(title)")
    }

    private func savedKnowledgeTitle(_ id: UUID) -> String? {
        let descriptor = FetchDescriptor<Knowledge>(predicate: #Predicate { $0.id == id })
        let value = (try? context.fetch(descriptor).first)?.title.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? nil : value
    }

    private var legacyPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text(title).font(.headline)
                    if !compactInvitation {
                        Text(offer.title).font(.callout).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if ["deferred", "dismissed"].contains(offer.status) {
                    Button(expanded ? "收起" : "查看") { expanded.toggle() }.controlSize(.small)
                }
            }
            if let scope = offer.visibleScope {
                VStack(alignment: .leading, spacing: 4) {
                    if !offer.isCheckInvitation {
                        Text("本次保存范围").font(.caption).foregroundStyle(.secondary)
                    }
                    Text(scope).font(.callout).textSelection(.enabled).id(scope)
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
                Text(persistenceError == nil ? "正在保存已确认的内容…" : "正在重试本机保存，成功后更新结果。").font(.caption).foregroundStyle(.secondary)
            } else if offer.status == "invalidated" {
                Text(offer.error ?? "请在新的话题收尾处确认内容。").font(.caption).foregroundStyle(.secondary)
            } else if offer.status == "offered" || offer.status == "failed" || (expanded && ["deferred", "dismissed"].contains(offer.status)) {
                if let error = deliveryError ?? (offer.status == "failed" ? offer.error : nil) { Text(error).font(.caption).foregroundStyle(.secondary) }
                if offer.isCheckInvitation {
                    Toggle("已学过，加入复习", isOn: $enrollReview)
                        .toggleStyle(.checkbox).font(.caption).foregroundStyle(.secondary)
                        .controlSize(.small).disabled(!enabled)
                } else {
                    Toggle("已学过，加入复习", isOn: $enrollReview).toggleStyle(.checkbox).disabled(!enabled)
                }
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 12) { actions }
                    VStack(alignment: .leading, spacing: 10) { actions }
                }.controlSize(.small).disabled(!enabled)
            }
            if resourceFailed { Text("动效暂不可用，保存状态不受影响。").font(.caption).foregroundStyle(.secondary) }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field, in: RoundedRectangle(cornerRadius: 14))
    }
    @ViewBuilder private var actions: some View {
        Button(offer.status == "failed" ? "重试录入" : offer.isCheckInvitation ? "新增知识" : offer.hasNext ? "录入并继续" : "录入知识") {
            token += 1; resourceFailed = false
            initiated = onAction(enrollReview ? "capture_save_review" : "capture_save")
        }.buttonStyle(.borderedProminent).tint(runway.ink)
        if offer.status != "deferred" {
            Button(offer.isCheckInvitation ? "稍后" : "稍后录入") { _ = onAction("capture_later") }
        }
        if !offer.isCheckInvitation {
            Button(offer.hasNext ? "跳过，继续" : "跳过") { _ = onAction("capture_skip") }
        }
    }
}

private struct KnowledgeCompletionLight: ViewModifier {
    let token: Int
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.runway) private var runway
    @State private var running = false
    @State private var position: CGFloat = -1

    func body(content: Content) -> some View {
        content.overlay {
            if running && !reduced {
                GeometryReader { geometry in
                    LinearGradient(colors: [.clear, runway.cardHighlight, .clear], startPoint: .leading, endPoint: .trailing)
                        .frame(width: geometry.size.width * 0.6)
                        .rotationEffect(.degrees(12))
                        .offset(x: position * geometry.size.width)
                        .opacity(0.7)
                }.clipShape(RoundedRectangle(cornerRadius: 8))
                    .allowsHitTesting(false).accessibilityHidden(true)
            }
        }
        .task(id: token) {
            running = false; position = -1
            guard token > 0, !reduced else { return }
            running = true
            await Task.yield()
            guard !Task.isCancelled else { running = false; return }
            withAnimation(.easeOut(duration: 1.05)) { position = 1.4 }
            do { try await Task.sleep(for: .milliseconds(1050)) } catch { running = false; return }
            running = false
        }
    }
}
