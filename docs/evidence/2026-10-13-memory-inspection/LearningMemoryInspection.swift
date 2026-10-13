@testable import ReviewTodayContractSupport
import Foundation
import SwiftData

/// Baseline inspection only: real native retrieval, synthetic in-memory records.
@main
struct LearningMemoryInspection {
    @MainActor static func main() throws {
        let schema = Schema([AgentSession.self, AgentMessage.self, AgentRun.self, AgentRunControl.self,
                             Knowledge.self, Source.self, Question.self, CaptureTask.self, ReviewAttempt.self])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let target = AgentSession(title: "本轮检索学习")
        context.insert(target); try context.save()
        var rows: [[String: Any]] = []
        let empty = try LearningMemory.candidates(for: "数据库索引", excluding: target.id, context: context)
        precondition(empty.isEmpty)
        rows.append(["case": "empty_memory", "candidate_count": empty.count])

        func card(_ title: String, _ explanation: String, _ second: TimeInterval) -> Knowledge {
            Knowledge(learningGoal: "比较检索方法", knowledgeType: "concept", theme: "检索",
                      contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh",
                      evidenceExcerpt: explanation, evidenceLocator: "synthetic", title: title,
                      explanation: explanation, createdAt: Date(timeIntervalSince1970: second))
        }
        let first = card("关键词检索", "依据字词进行匹配。", 10000)
        let second = card("向量检索", "依据语义相近程度进行匹配。", 10001)
        context.insert(first); context.insert(second); try context.save()
        let firstID = first.id.uuidString.lowercased(), secondID = second.id.uuidString.lowercased()
        let query = "比较这两张卡：reviewtoday://knowledge/\(firstID) reviewtoday://knowledge/\(secondID)"
        let expected = Set([firstID, secondID])
        func ids(_ values: [[String: Any]]) -> [String] { values.compactMap { $0["knowledge_id"] as? String } }
        let distinct = try LearningMemory.candidates(for: query, excluding: target.id, context: context)
        precondition(Set(ids(distinct)) == expected)
        rows.append(["case": "different_titles_two_selected_cards", "selected_ids": Array(expected).sorted(),
                     "candidate_ids": ids(distinct), "candidate_count": distinct.count])

        first.title = "检索策略"; second.title = "检索策略"; try context.save()
        let sameTitle = try LearningMemory.candidates(for: query, excluding: target.id, context: context)
        precondition(sameTitle.count == 1 && Set(ids(sameTitle)) != expected, "preserve the current gap as a baseline")
        precondition(sameTitle[0]["knowledge_id"] as? String == secondID)
        rows.append(["case": "same_title_two_selected_cards", "selected_ids": Array(expected).sorted(),
                     "candidate_ids": ids(sameTitle), "missing_ids": Array(expected.subtracting(ids(sameTitle))).sorted(),
                     "expected_candidate_count": 2, "actual_candidate_count": sameTitle.count,
                     "phase": "gap_reproduced", "available_count": 2, "candidate_limit": 12])

        let repeated = "reviewtoday://knowledge/\(firstID) reviewtoday://knowledge/\(firstID)"
        let unique = try LearningMemory.candidates(for: repeated, excluding: target.id, context: context)
        precondition(ids(unique) == [firstID])
        rows.append(["case": "repeat_same_card_identity", "candidate_ids": ids(unique), "candidate_count": unique.count])

        second.title = "向量检索"; try context.save()
        let beforeVersion = try LearningMemory.candidates(for: query, excluding: target.id, context: context)
        precondition(LearningMemory.valid(beforeVersion, sessions: [target], knowledge: [first, second]))
        second.version += 1; try context.save()
        let oldValid = LearningMemory.valid(beforeVersion, sessions: [target], knowledge: [first, second])
        let current = try LearningMemory.candidates(for: query, excluding: target.id, context: context)
        precondition(!oldValid && Set(ids(current)) == expected)
        precondition(current.first(where: { $0["knowledge_id"] as? String == secondID })?["content_version"] as? Int == 2)
        rows.append(["case": "updated_card_version", "old_reference_valid": oldValid,
                     "new_card_version": 2, "candidate_count": current.count])

        second.lifecycle = "deleted"; try context.save()
        let afterDeletion = try LearningMemory.candidates(for: query, excluding: target.id, context: context)
        precondition(ids(afterDeletion) == [firstID])
        precondition(!LearningMemory.valid(current, sessions: [target], knowledge: [first, second]))
        rows.append(["case": "deleted_card", "candidate_ids": ids(afterDeletion), "stale_reference_valid": false])

        // Learning history also works before any formal card is created.
        let noCardContainer = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let noCardContext = noCardContainer.mainContext
        let origin = AgentSession(title: "先前学习"), destination = AgentSession(title: "本轮追问")
        noCardContext.insert(origin); noCardContext.insert(destination)
        let older = UUID().uuidString.lowercased(), newer = UUID().uuidString.lowercased()
        for (identity, date) in [(older, "2026-10-12T00:00:00Z"), (newer, "2026-10-13T00:00:00Z")] {
            LearningMemory.store(["id": identity, "message_id": identity, "session_id": origin.id.uuidString,
                "concept": "数据库索引", "concepts": ["索引"], "excerpt": "索引用于加快查找。",
                "kind": "explained", "dependencies": [], "occurred_at": date], session: origin)
        }
        try noCardContext.save()
        let learned = try LearningMemory.candidates(for: "数据库索引", excluding: destination.id, context: noCardContext)
        precondition(learned.count == 1 && learned[0]["id"] as? String == newer && learned[0]["kind"] as? String == "explained")
        let knowledgeCount = try noCardContext.fetchCount(FetchDescriptor<Knowledge>())
        let reviewCount = try noCardContext.fetchCount(FetchDescriptor<ReviewAttempt>())
        precondition(knowledgeCount == 0 && reviewCount == 0)
        rows.append(["case": "learning_without_card_and_repeated_concept", "kind": "explained",
                     "candidate_count": learned.count, "newest_record_selected": true,
                     "formal_card_count": knowledgeCount, "formal_review_count": reviewCount])
        let report: [String: Any] = ["kind": "read_only_native_baseline", "date": "2026-10-13", "cases": rows,
                                    "real_supplier_requests": 0, "daily_database_written": false]
        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
}
