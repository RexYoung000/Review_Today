import Foundation
import SwiftData

@main
struct LearningMemoryContractTests {
    @MainActor static func main() throws {
        let schema = Schema([AgentSession.self, AgentMessage.self, AgentRun.self, AgentRunControl.self,
                             Knowledge.self, Source.self, Question.self, CaptureTask.self, ReviewAttempt.self])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let origin = AgentSession(title: "旧索引课程"), target = AgentSession(title: "RAG")
        let evidenceID = UUID().uuidString.lowercased()
        context.insert(origin); context.insert(target)
        let emptyLibrary = try LearningMemory.candidates(for: "检索", excluding: target.id, context: context)
        precondition(emptyLibrary.isEmpty, "a new library has no prerequisite memory")
        let questionCard = Knowledge(learningGoal: "说明什么是检索增强生成", knowledgeType: "concept", theme: "RAG", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "什么是检索", evidenceLocator: "1")
        context.insert(questionCard); try context.save()
        let questionNoise = try LearningMemory.candidates(for: "什么叫 harness", excluding: target.id, context: context)
        precondition(questionNoise.isEmpty, "question words alone must not recall unrelated topics")
        context.delete(questionCard); try context.save()
        origin.composerDraft = "秘密未发送草稿"
        origin.pendingOperationJSON = "{\"kind\":\"save\"}"
        LearningMemory.store(["id": evidenceID, "session_id": origin.id.uuidString, "concept": "索引",
                              "concepts": ["检索"], "kind": "explained", "excerpt": "通过索引检索资料",
                              "message_id": evidenceID, "dependencies": []], session: origin)
        try context.save()
        var refs = try LearningMemory.candidates(for: "RAG 检索", excluding: target.id, context: context)
        precondition(refs.count == 1 && refs[0]["kind"] as? String == "explained")
        let irrelevant = try LearningMemory.candidates(for: "photosynthesis", excluding: target.id, context: context)
        precondition(irrelevant.isEmpty, "irrelevant existing records are not forced into teaching")
        precondition(!ConversationProcessor.json(refs).contains("秘密") && !ConversationProcessor.json(refs).contains("save"))
        origin.status = "archived"
        try context.save()
        refs = try LearningMemory.candidates(for: "检索", excluding: target.id, context: context)
        precondition(refs.count == 1, "archive does not mean forget")
        let run = AgentRun(id: UUID(), sessionID: target.id)
        run.status = "running"
        run.memoryReferencesJSON = ConversationProcessor.json(refs)
        context.insert(run)
        precondition(LearningMemory.setAllowed(false, session: origin, context: context))
        let excluded = try LearningMemory.candidates(for: "检索", excluding: target.id, context: context)
        precondition(excluded.isEmpty && run.status == "stopping")
        target.pendingOperationJSON = "{\"kind\":\"save\",\"target_id\":\"fresh\"}"
        try LearningMemory.fenceInvalidReferences(context: context)
        precondition(target.pendingOperationJSON?.contains("fresh") == true, "old exclusion replay does not revoke unrelated later consent")
        run.revision += 1 // the delayed stop receipt is not a new dependency
        try LearningMemory.fenceInvalidReferences(context: context)
        precondition(target.pendingOperationJSON?.contains("fresh") == true)
        precondition(!LearningMemory.valid(refs, sessions: [origin, target], knowledge: []))
        precondition(LearningMemory.setAllowed(true, session: origin, context: context))
        precondition(!LearningMemory.valid(refs, sessions: [origin, target], knowledge: []), "old policy references stay revoked")
        refs = try LearningMemory.candidates(for: "检索", excluding: target.id, context: context)
        precondition(refs.count == 1)
        origin.memoryContentRevision += 1
        precondition(!LearningMemory.valid(refs, sessions: [origin, target], knowledge: []))
        let corrected = try LearningMemory.candidates(for: "检索", excluding: target.id, context: context)
        precondition(corrected.isEmpty)
        let reviews = try context.fetch(FetchDescriptor<ReviewAttempt>())
        precondition(reviews.isEmpty)
        let card = Knowledge(learningGoal: "向量检索", knowledgeType: "concept", theme: "RAG", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "相似度检索", evidenceLocator: "1")
        context.insert(card)
        let preview = ReviewAttempt(sessionId: UUID(), knowledgeId: card.id, knowledgeVersion: 1, questionId: UUID(), mode: "preview")
        preview.acked = true; preview.completedAt = .now; preview.effectiveGrade = "good"
        context.insert(preview)
        try context.save()
        refs = try LearningMemory.candidates(for: "RAG", excluding: target.id, context: context)
        precondition(refs.count == 1 && refs[0]["kind"] as? String == "knowledge_card" && refs[0]["review"] == nil,
                     "cards work without session history; preview never becomes formal evidence")
        preview.mode = "formal"; preview.effectiveGrade = "invalid"
        try context.save()
        let invalidReview = try LearningMemory.candidates(for: "RAG", excluding: target.id, context: context)
        precondition(invalidReview[0]["review"] == nil)
        preview.effectiveGrade = "good"
        try context.save()
        let validReview = try LearningMemory.candidates(for: "RAG", excluding: target.id, context: context)
        precondition(validReview[0]["review"] != nil)

        // Different cards can share a displayed title or learning goal. Their
        // explicit links must still reach the downstream selector independently.
        do {
            let cardsContainer = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
            let cardsContext = cardsContainer.mainContext
            let destination = AgentSession(title: "比较检索卡片")
            cardsContext.insert(destination)
            func makeCard(_ explanation: String, at second: TimeInterval) -> Knowledge {
                Knowledge(learningGoal: "比较检索策略", knowledgeType: "concept", theme: "检索",
                          contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh",
                          evidenceExcerpt: explanation, evidenceLocator: "synthetic", title: "检索策略",
                          explanation: explanation, createdAt: Date(timeIntervalSince1970: second))
            }
            let first = makeCard("依据字词进行匹配。", at: 10000)
            let second = makeCard("依据语义相近程度进行匹配。", at: 10001)
            cardsContext.insert(first); cardsContext.insert(second); try cardsContext.save()
            let firstID = first.id.uuidString.lowercased(), secondID = second.id.uuidString.lowercased()
            let bothLinks = "reviewtoday://knowledge/\(firstID) reviewtoday://knowledge/\(secondID)"
            let sameTitle = try LearningMemory.candidates(for: bothLinks, excluding: destination.id, context: cardsContext)
            precondition(sameTitle.count == 2 && sameTitle.compactMap { $0["knowledge_id"] as? String } == [secondID, firstID],
                         "both explicitly selected same-title cards survive, preserving ranking")
            let repeated = try LearningMemory.candidates(for: "reviewtoday://knowledge/\(firstID) reviewtoday://knowledge/\(firstID)", excluding: destination.id, context: cardsContext)
            precondition(repeated.count == 1 && repeated[0]["knowledge_id"] as? String == firstID,
                         "repeated links to one card still yield one candidate")
            first.title = ""; second.title = ""; try cardsContext.save()
            let sameGoal = try LearningMemory.candidates(for: bothLinks, excluding: destination.id, context: cardsContext)
            precondition(sameGoal.count == 2 && Set(sameGoal.compactMap { $0["knowledge_id"] as? String }) == Set([firstID, secondID]),
                         "untitled cards with the same learning goal retain their own identities")
            first.title = "索引选型"; first.version += 1; try cardsContext.save()
            precondition(!LearningMemory.valid(sameTitle, sessions: [destination], knowledge: [first, second]))
            let refreshed = try LearningMemory.candidates(for: bothLinks, excluding: destination.id, context: cardsContext)
            precondition(refreshed.count == 2 && refreshed.first(where: { $0["knowledge_id"] as? String == firstID })?["content_version"] as? Int == 2,
                         "renaming and updating a card keeps its identity while fencing the old version")
            first.lifecycle = "deleted"; try cardsContext.save()
            precondition(!LearningMemory.valid(refreshed, sessions: [destination], knowledge: [first, second]))
            let surviving = try LearningMemory.candidates(for: bothLinks, excluding: destination.id, context: cardsContext)
            precondition(surviving.count == 1 && surviving[0]["knowledge_id"] as? String == secondID,
                         "deleting one selected card does not remove the other")
        }
        do {
            let historyContainer = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
            let historyContext = historyContainer.mainContext
            let first = AgentSession(title: "前一课"), second = AgentSession(title: "另一课"), destination = AgentSession(title: "本轮")
            for session in [first, second, destination] { historyContext.insert(session) }
            let older = UUID().uuidString.lowercased(), newer = UUID().uuidString.lowercased(), separate = UUID().uuidString.lowercased()
            for (session, identity, timestamp) in [(first, older, "2026-10-12T00:00:00Z"), (first, newer, "2026-10-13T00:00:00Z"), (second, separate, "2026-10-13T01:00:00Z")] {
                LearningMemory.store(["id": identity, "session_id": session.id.uuidString,
                                      "concept": "数据库索引", "concepts": ["索引"], "kind": "explained",
                                      "excerpt": "索引加快查找。", "dependencies": [], "occurred_at": timestamp], session: session)
            }
            try historyContext.save()
            let grouped = try LearningMemory.candidates(for: "数据库索引", excluding: destination.id, context: historyContext)
            precondition(grouped.count == 2 && Set(grouped.compactMap { $0["id"] as? String }) == Set([newer, separate]),
                         "learning records still merge by session and concept; other sessions stay separate")
        }
        do {
            let boundedContainer = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
            let boundedContext = boundedContainer.mainContext
            let destination = AgentSession(title: "候选上限")
            boundedContext.insert(destination)
            var identities: [String] = []
            for index in 0..<13 {
                let candidate = Knowledge(learningGoal: "检索策略", knowledgeType: "concept", theme: "检索",
                                          contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh",
                                          evidenceExcerpt: "比较资料检索。", evidenceLocator: "synthetic", title: "检索策略",
                                          createdAt: Date(timeIntervalSince1970: TimeInterval(10000 + index)))
                boundedContext.insert(candidate); identities.append(candidate.id.uuidString.lowercased())
            }
            try boundedContext.save()
            let links = identities.map { "reviewtoday://knowledge/" + $0 }.joined(separator: " ")
            let bounded = try LearningMemory.candidates(for: links, excluding: destination.id, context: boundedContext)
            precondition(bounded.count == 12 && bounded.compactMap { $0["knowledge_id"] as? String } == Array(identities.suffix(12).reversed()),
                         "same-title cards still obey the twelve-candidate limit and timestamp order")
        }
        for previousStatus in ["running", "stopping", "interrupted"] {
            let invalidationContainer = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
            let invalidationContext = invalidationContainer.mainContext
            let origin = AgentSession(title: "索引旧课"), destination = AgentSession(title: "RAG 追问")
            let otherSession = AgentSession(title: "无关联会话")
            invalidationContext.insert(origin); invalidationContext.insert(destination); invalidationContext.insert(otherSession)
            let evidenceID = UUID().uuidString.lowercased()
            LearningMemory.store(["id": evidenceID, "session_id": origin.id.uuidString,
                                  "concept": "数据库索引", "kind": "explained", "excerpt": "索引帮助查找。",
                                  "dependencies": []], session: origin)
            let reference = LearningMemory.array(origin.learningEvidenceJSON).first!
            let dependent = AgentRun(id: UUID(), sessionID: destination.id)
            dependent.status = previousStatus; dependent.memoryReferencesJSON = ConversationProcessor.json([reference])
            let independent = AgentRun(id: UUID(), sessionID: otherSession.id); independent.status = "running"
            invalidationContext.insert(dependent); invalidationContext.insert(independent)
            let recovering = AgentMessage(sessionID: destination.id, role: "assistant", content: "已展示的初稿")
            recovering.runID = dependent.id; recovering.responseState = "recovering"
            let completed = AgentMessage(sessionID: destination.id, role: "assistant", content: "完整历史保留")
            completed.runID = dependent.id; completed.responseState = "complete"
            let unrelated = AgentMessage(sessionID: otherSession.id, role: "assistant", content: "无关联恢复回复")
            unrelated.runID = independent.id; unrelated.responseState = "recovering"
            for message in [recovering, completed, unrelated] { invalidationContext.insert(message) }
            try invalidationContext.save()
            precondition(LearningMemory.setAllowed(false, session: origin, context: invalidationContext))
            precondition(recovering.responseState == "interrupted" && recovering.content == "已展示的初稿",
                         "invalidated recovery is immediately interrupted without waiting for a service receipt")
            precondition(completed.responseState == "complete" && completed.content == "完整历史保留")
            precondition(independent.status == "running" && unrelated.responseState == "recovering",
                         "completed history and unrelated recovering replies are preserved")
            precondition(dependent.status == (previousStatus == "interrupted" ? "interrupted" : "stopping"),
                         "invalid reply settlement preserves the Run's existing stop/revision state")
            destination.pendingOperationJSON = "{\"kind\":\"save\",\"target_id\":\"fresh\"}"
            try LearningMemory.fenceInvalidReferences(context: invalidationContext)
            let stopControls = try invalidationContext.fetch(FetchDescriptor<AgentRunControl>())
            precondition(stopControls.count == (previousStatus == "running" ? 1 : 0),
                         "already stopping/interrupted Runs do not acquire another stop request")
            precondition(destination.pendingOperationJSON?.contains("fresh") == true,
                         "repeated old invalidation does not clear a later decision or queue duplicate stops")
        }
        print("PASS: MEM-02 running/stopping/interrupted recovering replies settled immediately, body/history/unrelated replies preserved, repeat fence bounded")
        print("PASS: MEM-01 seven behavior groups: same title, repeated link, same goal, current version, deletion, learning record grouping, candidate limit")
        print("PASS: typed local recall, no drafts/consent, archive vs exclusion, policy/content versions, late-run fence, no formal review writes")
    }
}
