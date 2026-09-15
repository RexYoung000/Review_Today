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
        func page(_ status: String, revision: Int) -> [String: Any] {
            var value = offer; value["status"] = status
            return ["session_id": session.id.uuidString, "events": [], "runs": [], "paused": false,
                    "capture_offers": [value], "capture_offers_revision": revision, "lifecycle_revision": 0]
        }
        try ConversationProcessor.persist(page("deferred", revision: 2), session: session, context: context)
        let decoded = TopicCaptureOffer.read(session.captureOffersJSON)
        precondition(decoded.count == 1 && decoded[0].id == id && decoded[0].anchorMessageID == anchor)
        precondition(decoded[0].needsAttention && !decoded[0].hasNext)
        try ConversationProcessor.persist(page("saved", revision: 3), session: session, context: context)
        try ConversationProcessor.persist(page("deferred", revision: 2), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0].status == "saved", "late pages cannot reopen processed offers")
        session.status = "archived"; session.lifecycleRevision = 1
        try ConversationProcessor.persist(page("offered", revision: 4), session: session, context: context)
        precondition(TopicCaptureOffer.read(session.captureOffersJSON)[0].status == "saved", "archived history cannot revive prompts")
        let reader = ModelContext(container)
        let cards = try reader.fetch(FetchDescriptor<Knowledge>())
        precondition(cards.isEmpty, "replication never saves knowledge")
        print("PASS: topic offers persisted, deferred inbox semantics, consumed continuation, stale/archived page fencing, no knowledge writes")
    }
}
