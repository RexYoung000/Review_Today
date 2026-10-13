@testable import ReviewTodayContractSupport
import Foundation
import SwiftData

/// Inspection: synthetic records, production mutation and event-apply paths.
@main
struct MemoryInvalidationInspection {
    @MainActor struct Fixture {
        let container: ModelContainer
        let origin: AgentSession
        let destination: AgentSession
        let unrelated: AgentSession
        let run: AgentRun
        let response: AgentMessage
        let history: AgentMessage
        let card: Knowledge
        let review: ReviewAttempt
        let evidenceID: String
        let reference: [String: Any]
        var context: ModelContext { container.mainContext }

        init(state: String, cardReference: Bool = false) throws {
            container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
            let context = container.mainContext
            context.autosaveEnabled = false
            origin = AgentSession(title: "索引旧课")
            destination = AgentSession(title: "RAG 当前课")
            unrelated = AgentSession(title: "无关联会话")
            for value in [origin, destination, unrelated] { context.insert(value) }
            let originMessage = AgentMessage(sessionID: origin.id, role: "assistant", content: "合成旧讲解", deliveryStatus: "received")
            originMessage.responseState = "complete"; context.insert(originMessage)
            evidenceID = UUID().uuidString.lowercased()
            LearningMemory.store(["id": evidenceID, "session_id": origin.id.uuidString,
                "concept": "数据库索引", "concepts": ["索引"], "kind": "explained",
                "excerpt": "索引用于加快查找。", "dependencies": []], session: origin)
            card = Knowledge(learningGoal: "独立已保存知识", knowledgeType: "concept", theme: "独立内容",
                contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh",
                evidenceExcerpt: "正式卡片保留。", evidenceLocator: "synthetic", title: "已保存卡片")
            card.originSessionID = origin.id; context.insert(card)
            review = ReviewAttempt(sessionId: UUID(), knowledgeId: card.id, knowledgeVersion: card.version,
                                  questionId: UUID(), mode: "formal")
            review.acked = true; review.completedAt = Date(timeIntervalSince1970: 1000); review.effectiveGrade = "good"
            context.insert(review); context.insert(FsrsState(knowledgeId: card.id, dueAt: card.dueAt))
            try context.save()
            if cardReference {
                reference = ["id": card.id.uuidString.lowercased(), "knowledge_id": card.id.uuidString.lowercased(),
                             "kind": "knowledge_card", "content_version": card.version]
            } else {
                let candidates = try LearningMemory.candidates(for: "数据库索引", excluding: destination.id, context: context)
                let identity = evidenceID
                reference = candidates.first { $0["id"] as? String == identity }!
            }
            run = AgentRun(id: UUID(), sessionID: destination.id)
            run.status = "running"; run.revision = 1
            run.memoryReferencesJSON = ConversationProcessor.json([reference]); context.insert(run)
            response = AgentMessage(sessionID: destination.id, role: "assistant", content: "已展示的合成初稿", deliveryStatus: "received")
            response.runID = run.id; response.responseState = state; response.responseRevision = 1; response.responseChunkSeq = 2
            context.insert(response)
            history = AgentMessage(sessionID: destination.id, role: "assistant", content: "历史文字保留", deliveryStatus: "received")
            history.responseState = "complete"; context.insert(history)
            destination.summaryText = "依赖旧学习记录的合成摘要"
            destination.pendingOperationJSON = ConversationProcessor.json(["kind": "save", "target_id": run.id.uuidString.lowercased()])
            unrelated.summaryText = "无关联摘要保持"
            unrelated.pendingOperationJSON = "{\"kind\":\"save\",\"target_id\":\"unrelated\"}"
            try context.save()
        }

        func lateStopPage(revision: Int = 2, seq: Int = 1, state: String = "interrupted") -> [String: Any] {
            let date = "2026-10-14T00:00:00.000Z"
            let event: [String: Any] = ["session_id": destination.id.uuidString, "event_id": UUID().uuidString,
                "run_id": run.id.uuidString, "seq": seq, "revision": revision, "stage": "response." + state, "occurred_at": date,
                "payload": ["response": ["response_id": response.id.uuidString, "text": "迟到内容不得覆盖", "chunk_seq": 3, "status": state],
                            "session_summary": ["version": 2, "summary": "迟到摘要不得复活"]]]
            return ["session_id": destination.id.uuidString, "events": [event], "paused": true,
                    "runs": [["session_id": destination.id.uuidString, "run_id": run.id.uuidString,
                              "revision": revision, "status": revision == 1 ? "running" : "interrupted", "updated_at": date]]]
        }
    }

    @MainActor static func main() throws {
        var rows: [[String: Any]] = []
        for state in ["streaming", "recovering"] {
            let f = try Fixture(state: state)
            precondition(LearningMemory.setAllowed(false, session: f.origin, context: f.context))
            let sessions = try f.context.fetch(FetchDescriptor<AgentSession>())
            let cards = try f.context.fetch(FetchDescriptor<Knowledge>())
            precondition(!LearningMemory.valid([f.reference], sessions: sessions, knowledge: cards))
            precondition(f.run.status == "stopping" && f.destination.summaryText.isEmpty && f.destination.pendingOperationJSON == nil)
            let controls = try f.context.fetch(FetchDescriptor<AgentRunControl>())
            precondition(controls.count == 1 && controls[0].action == "stop")
            let expectedCurrent = state == "streaming" ? "interrupted" : "recovering"
            precondition(f.response.responseState == expectedCurrent, "capture the current behavior, including the gap")
            let immediateState = f.response.responseState
            try ConversationProcessor.persist(f.lateStopPage(revision: 1, seq: 1, state: "recovering"), session: f.destination, context: f.context)
            precondition(f.response.content == "已展示的合成初稿" && f.response.responseState == expectedCurrent)
            let beforeServiceConfirmation = f.response.responseState
            try ConversationProcessor.persist(f.lateStopPage(revision: 2, seq: 2), session: f.destination, context: f.context)
            precondition(f.response.content == "已展示的合成初稿" && f.response.responseState == "interrupted",
                         "a newer service Run revision correctly fences recovering messages too")
            precondition(f.destination.summaryText.isEmpty && f.history.content == "历史文字保留")
            precondition(f.unrelated.summaryText == "无关联摘要保持" && f.unrelated.pendingOperationJSON != nil)
            precondition(f.card.lifecycle == "active" && f.review.effectiveGrade == "good")
            rows.append(["case": "exclude_" + state, "old_reference_valid": false,
                         "late_content_blocked": true, "immediate_reply_state": immediateState,
                         "before_service_confirmation": beforeServiceConfirmation,
                         "after_service_confirmation": f.response.responseState,
                         "expected_immediate_reply_state": "interrupted", "gap_reproduced": state == "recovering",
                         "history_and_independent_card_preserved": true, "unrelated_session_preserved": true])
            if state == "recovering" {
                precondition(LearningMemory.setAllowed(true, session: f.origin, context: f.context))
                let allowedSessions = try f.context.fetch(FetchDescriptor<AgentSession>())
                precondition(!LearningMemory.valid([f.reference], sessions: allowedSessions, knowledge: cards))
                let fresh = try LearningMemory.candidates(for: "数据库索引", excluding: f.destination.id, context: f.context)
                precondition(fresh.count == 1 && fresh[0]["policy_version"] as? Int == 2)
                rows.append(["case": "reallow_after_exclusion", "stale_reference_valid": false,
                             "fresh_candidate_policy": 2, "active_reply_not_resumed": f.run.status == "stopping"])
            }
        }
        do {
            let f = try Fixture(state: "recovering")
            let originRun = AgentRun(id: UUID(), sessionID: f.origin.id); originRun.status = "running"; f.context.insert(originRun)
            let correction: [String: Any] = ["session_id": f.origin.id.uuidString, "events": [[
                "session_id": f.origin.id.uuidString, "event_id": UUID().uuidString, "run_id": originRun.id.uuidString,
                "seq": 1, "revision": 1, "stage": "memory_corrected", "payload": ["invalidate_memory": true]]], "runs": []]
            try ConversationProcessor.persist(correction, session: f.origin, context: f.context)
            try ConversationProcessor.persist(correction, session: f.origin, context: f.context)
            precondition(f.origin.memoryContentRevision == 1 && f.run.status == "stopping")
            let stale = try LearningMemory.candidates(for: "数据库索引", excluding: f.destination.id, context: f.context)
            precondition(stale.isEmpty && f.response.responseState == "recovering")
            precondition(f.review.effectiveGrade == "good" && f.card.lifecycle == "active")
            rows.append(["case": "correction_recovering", "content_revision": 1, "duplicate_event_idempotent": true,
                         "old_candidates": 0, "reply_state": f.response.responseState, "expected_reply_state": "interrupted",
                         "gap_reproduced": true, "formal_review_preserved": true])
        }
        do {
            let f = try Fixture(state: "recovering", cardReference: true)
            _ = try KnowledgeManagement.apply(.trash, ids: [f.card.id], context: f.context)
            precondition(f.run.status == "stopping" && f.response.responseState == "recovering")
            precondition(f.card.lifecycle == "soft_deleted" && f.review.effectiveGrade == "good")
            rows.append(["case": "trash_card_recovering", "card_lifecycle": f.card.lifecycle,
                         "run_state": f.run.status, "reply_state": f.response.responseState,
                         "expected_reply_state": "interrupted", "gap_reproduced": true])
        }
        do {
            let f = try Fixture(state: "recovering")
            let impact = try SessionDeletion.impact([f.origin.id], context: f.context)
            let changed = try SessionDeletion.perform(impact, includeCards: false, context: f.context)
            precondition(changed == nil)
            precondition(f.run.status == "stopping" && f.response.responseState == "recovering")
            let deleted = try SessionDeletion.contains(f.origin.id, context: f.context)
            precondition(deleted)
            let cards = try f.context.fetch(FetchDescriptor<Knowledge>())
            precondition(cards.count == 1 && cards[0].id == f.card.id && f.review.effectiveGrade == "good")
            let stale = try LearningMemory.candidates(for: "数据库索引", excluding: f.destination.id, context: f.context)
            precondition(stale.isEmpty && f.destination.checkpointJSON == nil)
            rows.append(["case": "delete_source_session_recovering", "source_deleted": true,
                         "old_candidates": 0, "reply_state": f.response.responseState,
                         "expected_reply_state": "interrupted", "gap_reproduced": true,
                         "independent_card_retained": true])
        }
        print(String(decoding: try JSONSerialization.data(withJSONObject: ["kind": "native_invalidation_inspection",
            "cases": rows, "daily_database_written": false, "supplier_requests": 0], options: [.prettyPrinted, .sortedKeys]), as: UTF8.self))
    }
}
