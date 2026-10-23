import Foundation
import SwiftData

@main
struct KnowledgeTitleContractTests {
    @MainActor static func main() throws {
        let cases: [(String, String, String)] = [
            ("来源核对与适用条件核对", "能依据来源材料的观点说明：核对来源与核对适用条件分别要确认什么。", "来源核对与适用条件核对"),
            ("核对", "解释核对的用途。", "核对"),
            ("字符串比对", "解释字符串比对的用途。", "字符串比对"),
            ("样本配对", "解释样本配对的方法。", "样本配对"),
            ("绝对与相对", "解释绝对与相对的含义。", "绝对与相对"),
            ("实体的存在", "解释实体的存在及其属性。", "实体的存在"),
            ("线程亲和", "解释线程亲和的含义。", "线程亲和"),
            ("  API 核对  ", "解释 API 核对的用途。", "API 核对"),
            ("RAG 与微调的区别", "说明两种方式的区别。", "RAG 与微调的区别"),
            ("Embedding model v2.1 与 top-k 检索", "解释术语", "Embedding model v2.1 与 top-k 检索"),
            ("矩阵的阶", "矩阵的阶数与维度", "矩阵的阶"),
            ("", "说明 RAG 的检索过程。", "RAG 的检索过程。"),
            (" \n ", "说明 RAG 的检索过程。", "RAG 的检索过程。"),
            ("知识点", "说明 RAG 的检索过程。", "RAG 的检索过程。"),
            ("RAG 工作流程的三个", "记住 RAG 工作流程的三个主要阶段。", "RAG 工作流程的三个主要阶段。"),
            ("RAG 的检索与生成阶", "说明 RAG 的检索与生成阶段分别做什么。", "RAG 的检索与生成阶段分别做什么。"),
            ("RAG 与", "说明 RAG 与微调的区别。", "RAG 与微调的区别。"),
            ("RAG 对", "说明 RAG 对来源质量的依赖。", "RAG 对来源质量的依赖。"),
            ("RAG\t和", "说明 RAG\t和微调的区别。", "RAG\t和微调的区别。"),
            // A similar-looking suffix without matching full source is not cutoff evidence.
            ("RAG 对", "说明来源质量的作用。", "RAG 对"),
            ("RAG 的生成阶", "说明检索与生成流程。", "RAG 的生成阶")
        ]
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        context.autosaveEnabled = false
        var rows: [Knowledge] = []
        var expectedTitles: [UUID: String] = [:]
        for (title, goal, expected) in cases {
            let item = Knowledge(learningGoal: goal, knowledgeType: "concept", theme: "知识",
                                 contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh",
                                 evidenceExcerpt: "原来源文本", evidenceLocator: "原定位", title: title)
            context.insert(item)
            rows.append(item)
            expectedTitles[item.id] = expected
        }
        try context.save()
        let original = rows.map { ($0.id, $0.title, $0.learningGoal, $0.version, $0.participatesInReview) }
        let resolved = KnowledgeLexicon.resolvedTitles(for: rows)
        for (index, item) in rows.enumerated() {
            // Check without siblings here: duplicate resolution may intentionally append context.
            let actual = KnowledgeLexicon.keyword(for: item)
            let expected = expectedTitles[item.id]!
            guard actual == expected else {
                print("FAIL title[\(index)]: \(item.title) -> \(actual); expected \(expected)")
                exit(1)
            }
            precondition(KnowledgeLexicon.resolvedTitles(for: [item])[item.id] == expected)
            precondition(resolved[item.id] == KnowledgeLexicon.keyword(for: item, among: rows))
            if index < 8 || index == 9 || index == 10 {
                precondition(KnowledgeLexicon.displayTheme(for: item) == expected)
                precondition(KnowledgeLexicon.chipTitle(resolved: expected, theme: "知识") == expected)
            }
        }
        for (item, before) in zip(rows, original) {
            precondition(item.id == before.0 && item.title == before.1 && item.learningGoal == before.2)
            precondition(item.version == before.3 && item.participatesInReview == before.4)
        }
        precondition(!context.hasChanges, "title display must not dirty persisted knowledge")
        print("PASS: \(cases.count) title cases; individual/bulk/chip/theme display; stored identity/content/version/review unchanged")
    }
}
