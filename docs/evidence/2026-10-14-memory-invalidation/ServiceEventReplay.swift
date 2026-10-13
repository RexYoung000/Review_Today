@testable import ReviewTodayContractSupport
import Foundation
import SwiftData

/// Apply the actual public pages emitted by service-probe.py to production Mac logic.
@main
struct ServiceEventReplay {
    @MainActor static func main() async throws {
        let input = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: Any]
        let candidate = input["candidate"] as! [String: Any]
        let sourceID = UUID(uuidString: input["origin_session_id"] as! String)!
        let destinationID = UUID(uuidString: input["destination_session_id"] as! String)!
        let runID = UUID(uuidString: input["run_id"] as! String)!
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        context.autosaveEnabled = false
        let origin = AgentSession(id: sourceID, title: "合成索引旧课")
        let destination = AgentSession(id: destinationID, title: "合成 RAG 追问")
        context.insert(origin); context.insert(destination)
        LearningMemory.store(candidate, session: origin)
        try context.save()
        try ConversationProcessor.persist(input["before"] as! [String: Any], session: destination, context: context)
        let messages = try context.fetch(FetchDescriptor<AgentMessage>())
        let response = messages.first { $0.runID == runID && $0.responseState == "recovering" }!
        let initialText = response.content
        precondition(initialText.contains("合成初稿"), "real schema-repair preview was applied")
        precondition(LearningMemory.setAllowed(false, session: origin, context: context))
        let immediate = response.responseState
        precondition(immediate == "recovering", "capture immediate UI-state gap")
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        precondition(!LearningMemory.valid([candidate], sessions: sessions, knowledge: []))
        let controls = try context.fetch(FetchDescriptor<AgentRunControl>())
        let control = controls.first { $0.runID == runID && $0.action == "stop" }!
        // The response is the actual service public Run from this same synthetic
        // recovery scenario. Only transport is replaced with an in-process reply.
        try await ConversationProcessor.deliverControl(control, context: context, request: { _, _ in
            input["stop_receipt"] as! [String: Any]
        })
        let afterReceipt = response.responseState
        precondition(control.sent && afterReceipt == "recovering")
        try ConversationProcessor.persist(input["after"] as! [String: Any], session: destination, context: context)
        precondition(response.content == initialText && response.responseState == "interrupted")
        let runs = try context.fetch(FetchDescriptor<AgentRun>())
        precondition(runs.first { $0.id == runID }?.status == "interrupted")
        let cards = try context.fetchCount(FetchDescriptor<Knowledge>())
        let reviews = try context.fetchCount(FetchDescriptor<ReviewAttempt>())
        precondition(cards == 0 && reviews == 0)
        print(String(decoding: try JSONSerialization.data(withJSONObject: ["kind": "native_service_event_replay",
            "initial_state": "recovering", "immediate_after_exclusion": immediate,
            "after_valid_stop_receipt": afterReceipt, "after_run_event_page": response.responseState,
            "expected_immediate_state": "interrupted", "immediate_gap_reproduced": true,
            "stale_reference_valid": false, "late_answer_blocked": true,
            "formal_cards": cards, "formal_reviews": reviews, "daily_database_written": false,
            "real_supplier_requests": 0, "http_transport": false], options: [.prettyPrinted, .sortedKeys]), as: UTF8.self))
    }
}
