import Foundation
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeDiskRead {
    @MainActor static func main() throws {
        let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let container = try M1DebugFixture.makeValidationContainer(directory)
        let context = ModelContext(container)
        context.autosaveEnabled = false
        let cards = try context.fetch(FetchDescriptor<Knowledge>())
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        let messages = try context.fetch(FetchDescriptor<AgentMessage>())
        let runs = try context.fetch(FetchDescriptor<AgentRun>())
        let sources = try context.fetch(FetchDescriptor<Source>())
        let fsrs = try context.fetch(FetchDescriptor<FsrsState>())
        let evidence: [String: Any] = [
            "layer": "fresh_process_swiftdata_read_after_app_quit",
            "knowledge_count": cards.count, "source_count": sources.count, "fsrs_count": fsrs.count,
            "cards": cards.map { ["id": $0.id.uuidString.lowercased(), "title": $0.title,
                "explanation": $0.explanation, "evidence": $0.evidenceExcerpt,
                "review": $0.participatesInReview, "questions": $0.questions.map(\.promptText),
                "origin_task": $0.originTaskID?.uuidString.lowercased() ?? "",
                "origin_session": $0.originSessionID?.uuidString.lowercased() ?? ""] as [String: Any] },
            "sessions": sessions.map { ["id": $0.id.uuidString.lowercased(), "cursor": $0.lastSessionEventSeq] as [String: Any] },
            "runs": runs.map { ["id": $0.id.uuidString.lowercased(), "status": $0.status] },
            "messages": messages.map { ["id": $0.id.uuidString.lowercased(), "role": $0.role, "text": $0.content,
                "delivery": $0.deliveryStatus, "client_id": $0.clientMessageID?.uuidString.lowercased() ?? "",
                "run_id": $0.runID?.uuidString.lowercased() ?? "", "response_state": $0.responseState] }
        ]
        let data = try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys, .prettyPrinted])
        try data.write(to: directory.appendingPathComponent("native-disk-read.json"))
        print("Fresh process read: \(cards.count) cards, \(messages.count) messages, \(runs.count) runs")
    }
}
