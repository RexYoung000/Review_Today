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
        print("PASS: typed local recall, no drafts/consent, archive vs exclusion, policy/content versions, late-run fence, no formal review writes")
    }
}
