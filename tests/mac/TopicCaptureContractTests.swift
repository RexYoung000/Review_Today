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

        func invitationPage(_ version: Int, scope: String, revision: Int) -> [String: Any] {
            var value = offer
            value["version"] = version; value["status"] = "offered"
            value["trigger"] = "verified_check"; value["scope_summary"] = scope
            value["next_request"] = ""; value["continuation_consumed"] = true
            return ["session_id": session.id.uuidString, "events": [], "runs": [], "paused": false,
                    "capture_offers": [value], "capture_offers_revision": revision, "lifecycle_revision": 0]
        }
        try ConversationProcessor.persist(invitationPage(1, scope: "检索与生成的职责", revision: 3), session: session, context: context)
        let displayed = TopicCaptureOffer.read(session.captureOffersJSON)[0]
        let firstClick = displayed.boundOperation("capture_save")
        precondition(displayed.isCheckInvitation && !displayed.hasNext && displayed.visibleScope == "检索与生成的职责")
        var oldSummary = displayed
        oldSummary.scopeSummary = "  \(displayed.title)  "
        precondition(oldSummary.visibleScope == nil, "legacy summaries that repeat the knowledge name stay hidden")
        try ConversationProcessor.persist(invitationPage(2, scope: "检索与生成的职责，以及检索失败时的边界", revision: 4), session: session, context: context)
        let refreshed = TopicCaptureOffer.read(session.captureOffersJSON)[0]
        precondition(refreshed.id == displayed.id && refreshed.anchorMessageID == displayed.anchorMessageID)
        precondition(refreshed.version == 2 && refreshed.visibleScope?.contains("检索失败") == true)
        precondition(firstClick["version"] as? Int == 1, "an already submitted click keeps its displayed version")
        precondition(refreshed.boundOperation("capture_save")["version"] as? Int == 2, "a new click binds the currently displayed range")
        precondition(refreshed.boundOperation("capture_later")["target_id"] as? String == id.uuidString.lowercased())
        try ConversationProcessor.persist(invitationPage(1, scope: "旧范围", revision: 3), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0] == refreshed, "late range updates cannot undo the visible version")
        try ConversationProcessor.persist(page("saved", revision: 5, version: 2), session: session, context: context)
        try ConversationProcessor.persist(page("deferred", revision: 2), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0].status == "saved", "late pages cannot reopen processed offers")
        session.status = "archived"; session.lifecycleRevision = 1
        try ConversationProcessor.persist(page("offered", revision: 6), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0].status == "saved", "archived history cannot revive prompts")
        let reader = ModelContext(container)
        let cards = try reader.fetch(FetchDescriptor<Knowledge>())
        precondition(cards.isEmpty, "replication never saves knowledge")
        print("PASS: old/new invitations, visible range refresh, displayed-version actions, stale/archived page fencing, no knowledge writes")
    }
}
