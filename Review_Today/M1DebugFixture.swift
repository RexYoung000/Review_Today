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
        return ["1", "invalid", "review"].contains(mode)
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
        context.insert(AppSettings())
        try context.save()
    }
}
#endif
