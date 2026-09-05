import Foundation
import SwiftData

@main
struct ModelMigrationTests {
    @MainActor static func main() throws {
        let schema = Schema([Source.self, Knowledge.self, Question.self, CaptureTask.self, AppSettings.self,
                             FsrsState.self, ReviewSession.self, ReviewAttempt.self, AgentSession.self,
                             AgentMessage.self, LearningTask.self, TaskEventRecord.self, SourceReference.self,
                             KnowledgeReference.self, SessionSummaryRecord.self, AgentRun.self,
                             AgentRunControl.self, SessionEventRecord.self])
        let url = URL(fileURLWithPath: CommandLine.arguments[2])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema, url: url))
        let context = container.mainContext
        if CommandLine.arguments[1] == "seed" {
            let source = Source(rawText: "迁移测试资料：检索再生成")
            let knowledge = Knowledge(learningGoal: "解释 RAG", knowledgeType: "concept", theme: "RAG", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "检索再生成", evidenceLocator: "paragraph:1")
            knowledge.source = source
            let session = AgentSession(title: "迁移前会话")
            session.composerDraft = "未发送草稿"
            let task = LearningTask(sessionID: session.id, inputMessageID: UUID())
            let review = ReviewAttempt(sessionId: UUID(), knowledgeId: knowledge.id, knowledgeVersion: 1, questionId: UUID(), mode: "formal")
            review.acked = true; review.effectiveGrade = "good"; review.completedAt = .now
            context.insert(source); context.insert(knowledge); context.insert(session); context.insert(task); context.insert(review)
            try context.save()
            print("PASS: old-schema fixture saved")
        } else {
            let sessions = try context.fetch(FetchDescriptor<AgentSession>())
            let knowledge = try context.fetch(FetchDescriptor<Knowledge>())
            let reviews = try context.fetch(FetchDescriptor<ReviewAttempt>())
            precondition(sessions.count == 1 && sessions[0].composerDraft == "未发送草稿")
            precondition(knowledge.count == 1 && knowledge[0].source?.rawText == "迁移测试资料：检索再生成")
            precondition(reviews.count == 1 && reviews[0].acked && reviews[0].effectiveGrade == "good")
#if NEW_SCHEMA
            precondition(sessions[0].lifecycleRevision == 0 && sessions[0].lifecycleActionsJSON == "[]")
            let tasks = try context.fetch(FetchDescriptor<LearningTask>())
            precondition(tasks.count == 1 && tasks[0].learningPlanJSON == nil && tasks[0].learningOutcomeJSON == nil)
#endif
            print("PASS: prior disk schema migrated without changing conversation, source, knowledge, review or draft")
        }
    }
}
