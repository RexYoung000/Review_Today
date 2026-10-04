import Foundation
import SwiftData

@main struct TopicCaptureContractTests {
    @MainActor static func main() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let session = AgentSession(title: "话题收尾回放"); context.insert(session); try context.save()
        let id = UUID(), anchor = UUID()
        let offer: [String: Any] = ["id": id.uuidString, "version": 1, "title": "RAG 与微调", "anchor_message_id": anchor.uuidString,
            "status": "deferred", "next_request": "接下来讲 Agent", "continuation_consumed": true]
        func page(_ status: String, revision: Int, version: Int = 1) -> [String: Any] {
            var value = offer; value["status"] = status; value["version"] = version
            return ["session_id": session.id.uuidString, "events": [], "runs": [], "paused": false,
                    "capture_offers": [value], "capture_offers_revision": revision, "lifecycle_revision": 0]
        }
        try ConversationProcessor.persist(page("deferred", revision: 2), session: session, context: context)
        let decoded = TopicCaptureOffer.read(session.captureOffersJSON)
        precondition(decoded.count == 1 && decoded[0].id == id && decoded[0].anchorMessageID == anchor)
        precondition(decoded[0].needsAttention && !decoded[0].hasNext)
        precondition(!decoded[0].isCheckInvitation && decoded[0].visibleScope == nil, "old offers remain compatible")
        precondition(decoded[0].previewPoints == nil && decoded[0].previewSummary == nil,
                     "older checkpoints can omit the structured preview")

        let initialPoints = ["检索找到相关资料。", "生成依据资料组织回答。"]
        let initialSummary = "检索提供依据，生成组织回答。"
        let updatedPoints = initialPoints + ["检索资料不足时，应说明限制。"]
        let updatedSummary = "依据资料回答，并明确资料不足的边界。"
        let updatedScope = "检索与生成的职责，以及检索失败时的边界"
        func invitationPage(_ version: Int, scope: String, revision: Int,
                            points: [String]? = nil, summary: String? = nil,
                            status: String = "offered", knowledgeIDs: [UUID]? = nil) -> [String: Any] {
            var value = offer
            value["version"] = version; value["status"] = status
            value["trigger"] = "verified_check"; value["scope_summary"] = scope
            value["next_request"] = ""; value["continuation_consumed"] = true
            if let points { value["preview_points"] = points }
            if let summary { value["preview_summary"] = summary }
            if let knowledgeIDs { value["knowledge_ids"] = knowledgeIDs.map { $0.uuidString } }
            return ["session_id": session.id.uuidString, "events": [], "runs": [], "paused": false,
                    "capture_offers": [value], "capture_offers_revision": revision, "lifecycle_revision": 0]
        }
        try ConversationProcessor.persist(invitationPage(1, scope: "检索与生成的职责", revision: 3,
                                                       points: initialPoints, summary: initialSummary), session: session, context: context)
        let displayed = TopicCaptureOffer.read(session.captureOffersJSON)[0]
        let firstClick = displayed.boundOperation("capture_save")
        precondition(displayed.isCheckInvitation && !displayed.hasNext && displayed.visibleScope == "检索与生成的职责")
        precondition(displayed.visiblePreviewPoints == initialPoints && displayed.visiblePreviewSummary == initialSummary)
        let roundTrip = try JSONEncoder().encode(displayed)
        let encoded = try JSONSerialization.jsonObject(with: roundTrip) as! [String: Any]
        precondition(encoded["preview_points"] as? [String] == initialPoints && encoded["preview_summary"] as? String == initialSummary)
        precondition(encoded["previewPoints"] == nil && encoded["previewSummary"] == nil)
        let decodedRoundTrip = try JSONDecoder().decode(TopicCaptureOffer.self, from: roundTrip)
        precondition(decodedRoundTrip == displayed)
        var absentPreview = displayed
        absentPreview.previewPoints = nil; absentPreview.previewSummary = nil
        precondition(absentPreview.visiblePreviewPoints.isEmpty && absentPreview.visiblePreviewSummary == nil && absentPreview.visibleScope != nil,
                     "a legacy invitation retains its truthful scope fallback")
        var sparsePreview = displayed
        sparsePreview.previewPoints = ["  一个知识点。  ", "", "\n", "一个知识点。"]
        sparsePreview.previewSummary = "  当前内容的一句总结。\n"
        precondition(sparsePreview.visiblePreviewPoints == ["一个知识点。"] && sparsePreview.visiblePreviewSummary == "当前内容的一句总结。",
                     "blank or duplicate preview items do not invent extra knowledge")
        sparsePreview.previewSummary = " \n "
        precondition(sparsePreview.visiblePreviewSummary == nil)
        sparsePreview.previewPoints = ["第一点；包含一句限制。", "第二点。", "第三点。", "第四点。"]
        precondition(sparsePreview.visiblePreviewPoints == sparsePreview.previewPoints!,
                     "the native projection must not silently split sentences or truncate selected evidence")
        var oldSummary = displayed
        oldSummary.scopeSummary = "  \(displayed.title)  "
        precondition(oldSummary.visibleScope == nil, "legacy summaries that repeat the knowledge name stay hidden")
        try ConversationProcessor.persist(invitationPage(2, scope: updatedScope, revision: 4,
                                                       points: updatedPoints, summary: updatedSummary), session: session, context: context)
        let refreshed = TopicCaptureOffer.read(session.captureOffersJSON)[0]
        precondition(refreshed.id == displayed.id && refreshed.anchorMessageID == displayed.anchorMessageID)
        precondition(refreshed.version == 2 && refreshed.visibleScope?.contains("检索失败") == true)
        precondition(refreshed.visiblePreviewPoints == updatedPoints && refreshed.visiblePreviewSummary == updatedSummary,
                     "same-point additions replace the original visible preview at its new version")
        precondition(firstClick["version"] as? Int == 1, "an already submitted click keeps its displayed version")
        precondition(refreshed.boundOperation("capture_save")["version"] as? Int == 2, "a new click binds the currently displayed range")
        precondition(refreshed.boundOperation("capture_later")["target_id"] as? String == id.uuidString.lowercased())

        func actionMessage(_ kind: String, for value: TopicCaptureOffer) -> AgentMessage {
            let message = AgentMessage(sessionID: session.id, role: "user", content: "知识卡操作")
            message.operationJSON = ConversationProcessor.json(value.boundOperation(kind))
            return message
        }
        let queuedSave = actionMessage("capture_save", for: refreshed)
        let queuedID = queuedSave.id
        precondition(refreshed.pendingOperation(for: nil) == nil)
        precondition(refreshed.pendingOperation(for: queuedSave) == "capture_save", "a local saved input blocks another save before service updates arrive")
        queuedSave.lastDeliveryError = "RT.HARNESS.SERVICE_UNAVAILABLE"
        precondition(refreshed.pendingOperation(for: queuedSave) == "capture_save" && queuedSave.id == queuedID,
                     "delivery failure keeps the same outbox input pending rather than requesting another save")
        queuedSave.deliveryStatus = "accepted"; queuedSave.lastDeliveryError = nil
        precondition(refreshed.pendingOperation(for: queuedSave) == "capture_save", "durable acceptance alone does not confirm that the offer action was consumed")
        for status in ["queued", "accepted", "running", "adjusting"] {
            precondition(refreshed.pendingOperation(for: queuedSave, runStatus: status) == "capture_save",
                         "an accepted active run protects the pending action across transcript remounts")
        }
        for status in ["interrupted", "cancelled", "completed", "retryable_failed", "terminal_failed"] {
            precondition(refreshed.pendingOperation(for: queuedSave, runStatus: status) == nil,
                         "a stopped or completed run that never consumed the operation cannot leave the card busy")
            queuedSave.deliveryStatus = "local"
            queuedSave.lastDeliveryError = "RT.HARNESS.SERVICE_UNAVAILABLE"
            precondition(refreshed.pendingOperation(for: queuedSave, runStatus: status) == "capture_save",
                         "an unsent durable outbox input keeps its same ID even if the previous run is terminal")
            precondition(queuedSave.id == queuedID)
            queuedSave.deliveryStatus = "accepted"; queuedSave.lastDeliveryError = nil
        }
        precondition(refreshed.pendingOperation(for: actionMessage("capture_save", for: displayed)) == nil,
                     "a delayed action for the old visible range cannot block the current version")
        var unrelated = refreshed; unrelated.id = UUID()
        precondition(refreshed.pendingOperation(for: actionMessage("capture_save", for: unrelated)) == nil)
        queuedSave.deliveryStatus = "held"
        precondition(refreshed.pendingOperation(for: queuedSave) == nil, "held lifecycle inputs are not active pending saves")
        queuedSave.deliveryStatus = "accepted"

        var failed = refreshed; failed.status = "failed"; failed.actionInputID = queuedID
        precondition(failed.visiblePreviewPoints == updatedPoints && failed.visiblePreviewSummary == updatedSummary,
                     "a failed save retains the content that can be retried")
        precondition(failed.pendingOperation(for: queuedSave) == nil, "a consumed save that failed allows explicit retry")
        let retry = actionMessage("capture_save", for: failed)
        precondition(failed.pendingOperation(for: retry) == "capture_save", "a new retry stays pending until its own action is consumed")
        var deferred = refreshed; deferred.status = "deferred"
        let later = actionMessage("capture_later", for: refreshed)
        precondition(refreshed.pendingOperation(for: later) == "capture_later")
        precondition(deferred.pendingOperation(for: later) == nil, "an acknowledged later action is complete")
        precondition(deferred.pendingOperation(for: actionMessage("capture_save", for: deferred)) == "capture_save",
                     "saving an expanded deferred suggestion is still protected from duplicate clicks")
        for status in ["saving", "saved", "invalidated", "skipped"] {
            var consumed = refreshed; consumed.status = status
            precondition(consumed.pendingOperation(for: queuedSave) == nil, "service-owned or terminal states are not waiting to send")
        }

        try ConversationProcessor.persist(invitationPage(1, scope: "旧范围", revision: 3), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0] == refreshed, "late range updates cannot undo the visible version")
        let resultIDs = [UUID(), UUID()]
        try ConversationProcessor.persist(invitationPage(2, scope: updatedScope, revision: 5,
                                                       points: updatedPoints, summary: updatedSummary,
                                                       status: "saved", knowledgeIDs: resultIDs), session: session, context: context)
        let saved = TopicCaptureOffer.read(session.captureOffersJSON)[0]
        precondition(saved.visiblePreviewPoints == updatedPoints && saved.visiblePreviewSummary == updatedSummary && saved.knowledgeIDs == resultIDs,
                     "confirmed saved projections keep the preview and every actual detail target")
        try ConversationProcessor.persist(page("deferred", revision: 2), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0].status == "saved", "late pages cannot reopen processed offers")
        session.status = "archived"; session.lifecycleRevision = 1
        try ConversationProcessor.persist(page("offered", revision: 6), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0].status == "saved", "archived history cannot revive prompts")
        let reader = ModelContext(container)
        let cards = try reader.fetch(FetchDescriptor<Knowledge>())
        precondition(cards.isEmpty, "replication never saves knowledge")
        checkAttention(sessionID: session.id, offer: refreshed)
        print("PASS: old/new preview compatibility and roundtrip, visible range refresh, saved/failed content preservation, displayed-version actions, pending outbox/acceptance/retry boundaries, receipt-only once attention/detail viewing, stale/archived page fencing, no knowledge writes")
    }

    @MainActor static func checkAttention(sessionID: UUID, offer original: TopicCaptureOffer) {
        var offer = original
        let taskID = UUID(), inputID = UUID(), first = UUID(), second = UUID()
        offer.status = "saving"; offer.saveTaskID = taskID; offer.actionInputID = inputID
        let receipt = KnowledgeIngestionReceipt(taskID: taskID, inputID: inputID, sessionID: sessionID, knowledgeIDs: [first, second])
        let attention = KnowledgeInvitationAttention()
        precondition(!attention.isUnread(first) && !attention.isUnread(second), "an invitation or generation alone cannot produce a saved cue")
        attention.register(offer)
        let wrong = KnowledgeIngestionReceipt(taskID: UUID(), inputID: UUID(), sessionID: sessionID, knowledgeIDs: [first])
        precondition(!attention.receive(wrong, offer: offer, eligible: true, reduced: false) && !attention.isUnread(first))
        let empty = KnowledgeIngestionReceipt(taskID: taskID, inputID: inputID, sessionID: sessionID, knowledgeIDs: [])
        precondition(!attention.receive(empty, offer: offer, eligible: true, reduced: false))
        precondition(attention.receive(receipt, offer: offer, eligible: true, reduced: false))
        precondition(attention.isUnread(first) && attention.isUnread(second), "all actual saved results have their own unread detail state")
        precondition(!attention.receive(receipt, offer: offer, eligible: true, reduced: false), "duplicate local ACKs cannot replay completion")
        attention.viewed(first)
        precondition(!attention.isUnread(first) && attention.isUnread(second), "viewing one detail restores only that result to its ordinary state")
        precondition(!attention.receive(receipt, offer: offer, eligible: true, reduced: false) && !attention.isUnread(first),
                     "a repeated ACK cannot rehang a viewed result")
        attention.viewed(second)
        precondition(!attention.isUnread(second))
        attention.register(offer)
        precondition(!attention.receive(receipt, offer: offer, eligible: true, reduced: false) && !attention.isUnread(first),
                     "remounting the same saved task cannot register another cue")

        var history = offer; history.status = "saved"; history.knowledgeIDs = receipt.knowledgeIDs
        let historicalAttention = KnowledgeInvitationAttention()
        precondition(!historicalAttention.isUnread(first) && !historicalAttention.receive(receipt, offer: history, eligible: true, reduced: false),
                     "opening persisted saved history stays ordinary and does not play completion")
        precondition(!historicalAttention.isUnread(first))
        let localProjectionRace = KnowledgeInvitationAttention()
        localProjectionRace.register(offer)
        precondition(localProjectionRace.receive(receipt, offer: history, eligible: true, reduced: false),
                     "an expected real receipt still completes if its local saved projection was published first")
        for (eligible, reduced) in [(false, false), (true, true)] {
            let still = KnowledgeInvitationAttention()
            still.register(offer)
            precondition(!still.receive(receipt, offer: offer, eligible: eligible, reduced: reduced))
            precondition(still.isUnread(first) && still.isUnread(second), "background/reduced motion keeps a static truthful saved indicator")
            precondition(!still.receive(receipt, offer: offer, eligible: true, reduced: false), "returning to the foreground cannot catch up a suppressed cue")
        }
        var legacy = offer; legacy.trigger = nil
        let legacyAttention = KnowledgeInvitationAttention()
        legacyAttention.register(legacy)
        precondition(!legacyAttention.receive(receipt, offer: legacy, eligible: true, reduced: false) && !legacyAttention.isUnread(first),
                     "legacy explicit continuation keeps its own presentation")
        var failed = offer; failed.status = "failed"
        let retried = KnowledgeInvitationAttention()
        retried.register(offer); retried.cancel(offer.id)
        precondition(!retried.isUnread(first))
        retried.register(failed)
        precondition(retried.receive(receipt, offer: failed, eligible: true, reduced: false),
                     "only the explicitly registered retry can receive a real completion cue")
        let cancelled = KnowledgeInvitationAttention()
        cancelled.register(offer); cancelled.cancel(offer.id)
        precondition(!cancelled.receive(receipt, offer: offer, eligible: true, reduced: false) && !cancelled.isUnread(first),
                     "a late receipt after leaving/cancelling cannot replay a completion cue")
        let byInput = KnowledgeInvitationAttention()
        var awaitingProjection = offer; awaitingProjection.saveTaskID = nil
        byInput.register(awaitingProjection)
        precondition(byInput.receive(receipt, offer: awaitingProjection, eligible: true, reduced: false),
                     "the actual input binds a receipt even before its task ID projection arrives")
        let versionFence = KnowledgeInvitationAttention()
        var updated = offer
        updated.version += 1; updated.saveTaskID = UUID(); updated.actionInputID = UUID()
        let updatedReceipt = KnowledgeIngestionReceipt(taskID: updated.saveTaskID!, inputID: updated.actionInputID!,
                                                       sessionID: sessionID, knowledgeIDs: [UUID()])
        versionFence.register(updated)
        precondition(!versionFence.receive(receipt, offer: offer, eligible: true, reduced: false),
                     "a receipt for the previous visible version cannot consume the current version's expectation")
        precondition(versionFence.receive(updatedReceipt, offer: updated, eligible: true, reduced: false),
                     "the actual new-version receipt remains eligible after an old-version receipt")
    }
}
