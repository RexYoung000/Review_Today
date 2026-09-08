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

    static var schema: Schema {
        Schema([
            Source.self,
            Knowledge.self,
            Question.self,
            CaptureTask.self,
            AppSettings.self,
            FsrsState.self,
            ReviewSession.self,
            ReviewAttempt.self,
            AgentSession.self,
                SessionFolder.self,
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
    }

    static func makeValidationContainer(_ directory: URL) throws -> ModelContainer {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return try ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema, url: directory.appendingPathComponent("app.store")))
    }

    static func makeContainer(mode: String? = Self.mode) throws -> ModelContainer {
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        try seed(container.mainContext, mode: mode)
        return container
    }

    private static func seed(_ context: ModelContext, mode: String?) throws {
        if mode == "today", ProcessInfo.processInfo.environment["REVIEW_TODAY_UI_POLISH_FIXTURE"] == "empty" {
            context.insert(AppSettings()); try context.save(); return
        }
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
        if mode == "today", ProcessInfo.processInfo.environment["REVIEW_TODAY_UI_POLISH_FIXTURE"] == "populated" {
            item.forceDue = true; item.skipTwoHourWait = true
            item.createdAt = Date.now.addingTimeInterval(-86400); item.dueAt = Date.now.addingTimeInterval(-3600)
            for (index, goal) in ["记住 RAG 工作流程的三个主要阶段。", "说明 RAG 的检索与生成阶段分别做什么。", "解释 Embedding model v2.1 与 top-k 检索的区别，保留完整的中英文术语和版本。", "描述检索评估方法", "说明已暂停的知识"].enumerated() {
                let sample = Knowledge(learningGoal: goal, knowledgeType: "concept", theme: index == 4 ? "暂停主题" : index == 3 ? "具有较长名称的检索评估与结果质量分析主题" : "检索增强生成（RAG）", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "隔离 UI 样例", evidenceLocator: "")
                sample.lifecycle = index == 4 ? "paused" : "active"
                context.insert(sample)
            }
        }
        context.insert(AppSettings())
        try seedLearningWorkspace(context, mode: mode)
        try context.save()
    }

    private static func seedLearningWorkspace(_ context: ModelContext, mode: String?) throws {
        if mode == "learning" { seedHandbook(context); return }
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

    private static func seedHandbook(_ context: ModelContext) {
        let names = ["空状态：检索增强生成的学习路径、证据边界与面试表达", "讲解中", "练习中", "学习完成"]
        for (index, name) in names.enumerated() {
            let session = AgentSession(title: "[界面样例] RAG · " + name, modePreset: index == 0 ? "auto" : "problem_solving",
                                       createdAt: Date.now.addingTimeInterval(Double(-index * 60)))
            session.setAutomaticTopicTags(index == 0 ? [] : ["RAG", "面试"])
            if index > 0 {
                session.contextCapacityJSON = ConversationProcessor.json([
                    "input_tokens": index == 1 ? 5500 : 18000, "input_budget": 24000,
                    "model_window": 1000000, "output_reserve": 4096, "estimated": true
                ])
            }
            context.insert(session)
            if index == 0 { continue }
            let input = AgentMessage(sessionID: session.id, role: "user", content: "带我理解 RAG，并准备面试中的独立回答。", deliveryStatus: "sent")
            let answer = AgentMessage(sessionID: session.id, role: "assistant", content:
                index == 2 ? "## 试着独立回答\n\n当企业文档持续更新时，你会选择微调还是 RAG？请说明判断依据与局限。\n\n需要帮助可以先要提示；提示不会计为通过。" :
                "## 先抓住核心\n\n**RAG 是先检索，再生成。** 它把相关资料作为上下文交给模型，而不是直接改变模型参数。\n\n## 用一个例子理解\n\n用户问报销政策时，先检索公司制度，再让模型根据制度回答，并给出出处。\n\n### 容易混淆的地方\n\n检索到资料不代表答案一定正确。还要检查召回、权限、引用和回答忠实度。", deliveryStatus: "received")
            let run = AgentRun(id: UUID(), sessionID: session.id)
            run.status = "completed"
            run.userSummary = index == 1 ? "讲解阶段预览（固定样例）" : "本轮已回应"
            run.elapsedMS = 4600
            run.startedAt = nil
            input.runID = run.id; answer.runID = run.id
            let task = LearningTask(sessionID: session.id, inputMessageID: input.id, mode: "problem_solving", status: index == 3 ? "completed" : "awaiting_user")
            task.conversationManaged = true
            task.understanding = index == 3 ? "verified" : "unknown"
            task.userSummary = index == 1 ? "正在讲解基础概念" : "等待你的独立回答"
            task.requiredActionType = index == 2 ? "submit_answer" : nil
            run.taskID = task.id
            let titles = ["基础概念与边界", "检索质量与引用", "独立作答", "迁移追问"]
            let steps: [[String: Any]] = titles.enumerated().map { i, title in
                ["id": "step-\(i)", "title": title, "state": index == 3 ? "verified" : i < index ? "explained" : "pending",
                 "understanding": index == 3 ? "verified" : "unknown", "message_ids": i < index ? [answer.id.uuidString] : []]
            }
            task.learningPlanJSON = ConversationProcessor.json(["id": task.id.uuidString, "goal": "理解并独立解释 RAG", "version": 1,
                                                               "current_step_id": "step-\(index == 3 ? 3 : index == 2 ? 2 : 0)", "steps": steps])
            if index == 3 {
                task.learningOutcomeJSON = ConversationProcessor.json(["message_id": answer.id.uuidString.lowercased(), "verified": ["解释 RAG 与微调的边界", "将检索方案迁移到企业文档场景"], "explained": [], "memory_status": "not_saved"])
                task.userSummary = "本次学习目标已完成"
            }
            context.insert(input); context.insert(answer); context.insert(run); context.insert(task)
        }
    }
}
#endif
