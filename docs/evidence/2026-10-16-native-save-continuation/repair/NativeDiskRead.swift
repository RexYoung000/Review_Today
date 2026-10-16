import Foundation
import SwiftData
@testable import ReviewTodayContractSupport

@main struct NativeDiskRead {
    @MainActor static func main() throws {
        // No application, service, model call, save or fabricated receipt.
        let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let container = try M1DebugFixture.makeValidationContainer(directory)
        let context = ModelContext(container)
        context.autosaveEnabled = false
        let cards = try context.fetch(FetchDescriptor<Knowledge>())
        let tasks = try context.fetch(FetchDescriptor<LearningTask>())
        let sources = try context.fetch(FetchDescriptor<Source>())
        let fsrs = try context.fetch(FetchDescriptor<FsrsState>())
        let evidence: [String: Any] = [
            "layer": "fresh_process_swiftdata_disk_read_after_native_app_quit",
            "knowledge_count": cards.count, "source_count": sources.count, "fsrs_count": fsrs.count,
            "cards": cards.map { ["id": $0.id.uuidString.lowercased(), "title": $0.title,
                "explanation": $0.explanation, "evidence": $0.evidenceExcerpt,
                "review": $0.participatesInReview, "questions": $0.questions.map(\.promptText),
                "origin_task": $0.originTaskID?.uuidString.lowercased() ?? "",
                "origin_session": $0.originSessionID?.uuidString.lowercased() ?? ""] as [String: Any] },
            "tasks": tasks.map { ["id": $0.id.uuidString.lowercased(), "status": $0.status,
                "memory_committed": $0.memoryCommitted] as [String: Any] }
        ]
        let data = try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys, .prettyPrinted])
        try data.write(to: directory.appendingPathComponent("native-disk-read.json"))
        print(String(decoding: data, as: UTF8.self))
    }
}
