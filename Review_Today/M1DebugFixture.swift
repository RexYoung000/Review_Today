#if DEBUG
import Foundation
import SwiftData

enum M1DebugFixture {
    static let environmentKey = "REVIEW_TODAY_M1_UI_FIXTURE"
    static let knowledgeID = UUID(uuidString: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")!
    static let questionID = UUID(uuidString: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")!

    static var mode: String? {
        ProcessInfo.processInfo.environment[environmentKey]
    }

    static var enabled: Bool {
        guard let mode else { return false }
        return ["1", "invalid", "review", "retry", "learning", "today"].contains(mode)
    }

    static func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            Source.self,
            Knowledge.self,
            Question.self,
            CaptureTask.self,
            AppSettings.self,
            FsrsState.self,
            ReviewSession.self,
            ReviewAttempt.self,
            AgentSession.self,
            AgentMessage.self,
            LearningTask.self,
            TaskEventRecord.self,
            SourceReference.self,
            KnowledgeReference.self,
            SessionSummaryRecord.self,
            AgentRun.self,
            AgentRunControl.self,
            SessionEventRecord.self,
        ])
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        try seed(container.mainContext)
        return container
    }

    private static func seed(_ context: ModelContext) throws {
        let sourceText = "光合作用是植物利用光能，把二氧化碳和水转化为有机物，并释放氧气的过程。"
        let source = Source(
            id: UUID(uuidString: "22222222-2222-4222-8222-222222222222")!,
            inputType: "text",
            rawText: sourceText
        )
        let item = Knowledge(
            id: knowledgeID,
            learningGoal: "解释光合作用如何利用原料生成有机物并释放氧气。",
            knowledgeType: "concept",
            theme: "光合作用",
            contentLanguage: "zh",
            questionLanguage: "zh",
            answerLanguage: "zh",
            evidenceExcerpt: sourceText,
            evidenceLocator: "",
            title: "光合作用",
            explanation: "1. 植物利用光能。\n2. 二氧化碳和水转化为有机物。\n3. 这个过程会释放氧气。"
        )
        item.source = source

        let spec = AgentAPI.ScoringSpec(
            learningGoal: "解释光合作用如何利用原料生成有机物并释放氧气。",
            mustCover: ["植物利用光能", "输入包含二氧化碳和水", "生成有机物", "释放氧气"],
            acceptableParaphrases: ["借助光能", "合成有机物", "制造有机物"],
            commonMisconceptions: ["植物从土壤里直接吸收有机物"],
            evidence: sourceText,
            orderRules: "不要求固定顺序，但四个关键点都要覆盖。"
        )
        let specData = try JSONEncoder().encode(spec)
        let question = Question(
            id: questionID,
            variantIndex: 0,
            promptText: "请解释植物进行光合作用的过程。",
            scoringSpecJSON: mode == "invalid" ? "{}" : String(decoding: specData, as: UTF8.self)
        )
        question.knowledge = item

        let task = CaptureTask(
            id: UUID(uuidString: "11111111-1111-4111-8111-111111111111")!,
            status: "completed",
            userStatus: "整理完成"
        )
        task.localCommitDone = true
        task.source = source
        task.receiptJSON = """
        {"understoodAs":"用户想记住光合作用的过程。","theme":"光合作用","knowledgeCount":1,"attribution":"claim"}
        """

        context.insert(source)
        context.insert(item)
        context.insert(question)
        context.insert(task)
        context.insert(FsrsState(knowledgeId: item.id, dueAt: item.dueAt))
        if mode == "retry" {
            let previousSession = ReviewSession(
                mode: "formal",
                snapshotJSON: item.id.uuidString
            )
            let previousAttempt = ReviewAttempt(
                sessionId: previousSession.id,
                knowledgeId: item.id,
                knowledgeVersion: item.version,
                questionId: question.id,
                mode: "formal"
            )
            previousAttempt.answerText = "植物借助光能，用二氧化碳和水合成有机物，同时释放氧气。"
            previousAttempt.agentGrade = "good"
            previousAttempt.pendingGrade = "good"
            previousAttempt.reviewState = "retryable_failed"
            previousAttempt.reviewErrorCode = "RT.REVIEW.ACK_FAILED"
            previousAttempt.reviewUserStatus = "还没有计入复习，可以重试"
            context.insert(previousSession)
            context.insert(previousAttempt)
        }
        context.insert(AppSettings())
        try seedLearningWorkspace(context)
        try context.save()
    }

    private static func seedLearningWorkspace(_ context: ModelContext) throws {
        let now = Date.now
        let samples: [(String, String, [String], String)] = [
            ("RAG 面试准备", "problem_solving", ["RAG", "面试"], "RAG 是什么？它在面试中应该怎么回答？"),
            ("向量数据库基础", "source_learning", ["向量检索", "数据库"], "请按初学者路径讲解向量数据库。"),
            ("检索质量评估", "topic_exploration", ["评估", "检索"], "我想系统了解检索质量怎么评估。"),
        ]
        for (index, sample) in samples.enumerated() {
            let session = AgentSession(title: sample.0, modePreset: sample.1, createdAt: now.addingTimeInterval(Double(-index * 3600)))
            session.updatedAt = now.addingTimeInterval(Double(-index * 900))
            session.setAutomaticTopicTags(sample.2)
            context.insert(session)
            let user = AgentMessage(sessionID: session.id, role: "user", content: sample.3,
                                    createdAt: session.createdAt, deliveryStatus: "sent")
            let answer = AgentMessage(sessionID: session.id, role: "assistant",
                                      content: index == 0 ? "RAG 是先检索与问题相关的外部信息，再把结果作为上下文交给模型生成答案。面试回答还应说明它解决的边界、检索质量和评估方法。" : "已经建立学习路径，下一步会沿当前目标继续。",
                                      createdAt: session.createdAt.addingTimeInterval(12), deliveryStatus: "received")
            let run = AgentRun(id: UUID(), sessionID: session.id)
            user.runID = run.id; answer.runID = run.id
            run.status = index == 2 ? "retryable_failed" : "completed"
            run.userSummary = index == 2 ? "资料检索暂时失败，可重试" : "已完成"
            run.startedAt = nil; run.elapsedMS = 4_800 + index * 900
            run.activityKind = index == 1 ? "lesson_step" : (index == 0 ? "knowledge_answer" : nil)
            run.completedAt = run.activityKind == nil ? nil : answer.createdAt
            context.insert(user); context.insert(answer); context.insert(run)
        }
        if let session = try context.fetch(FetchDescriptor<AgentSession>()).first {
            for offset in [2, 3, 7, 8, 14, 21, 28, 42, 56, 70, 91, 126] {
                let run = AgentRun(id: UUID(), sessionID: session.id)
                run.status = "completed"
                run.activityKind = offset % 2 == 0 ? "knowledge_answer" : "lesson_step"
                run.completedAt = Calendar.current.date(byAdding: .day, value: -offset, to: now)
                context.insert(run)
            }
        }
    }
}
#endif
