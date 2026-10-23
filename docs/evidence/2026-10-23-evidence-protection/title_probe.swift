@testable import ReviewTodayContractSupport
import Foundation

/// Read-only display probe. Constructs unattached objects; no store, UI or service.
@main
struct TitleProbe {
    @MainActor static func main() throws {
        let goal = "能依据来源材料的观点说明：核对来源与核对适用条件分别要确认什么，以及为何准确、忠实、适用需要分别检查（属来源观点，非已证实事实）。"
        let cases: [(String, String, String)] = [
            ("来源核对与适用条件核对", goal, "complete_word"),
            ("字符串比对", "解释字符串比对的用途。", "complete_word"),
            ("样本配对", "解释样本配对的方法。", "complete_word"),
            ("RAG 与微调的区别", "解释两种方式的区别。", "complete_title"),
            ("RAG 与", "说明 RAG 与微调的区别。", "unfinished_title"),
            ("", "说明 RAG 的检索过程。", "blank_title"),
            ("知识点", "说明 RAG 的检索过程。", "generic_title"),
            ("RAG 工作流程的三个", "记住 RAG 工作流程的三个主要阶段。", "legacy_quantity"),
            ("RAG 的检索与生成阶", "说明 RAG 的检索与生成阶段分别做什么。", "legacy_cut_word"),
            ("矩阵的阶", "矩阵的阶数与维度", "complete_title")
        ]
        var results: [[String: String]] = []
        for (title, goal, kind) in cases {
            let item = Knowledge(learningGoal: goal, knowledgeType: "concept", theme: "RAG",
                                 contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh",
                                 evidenceExcerpt: "", evidenceLocator: "", title: title)
            let keyword = KnowledgeLexicon.keyword(for: item)
            let resolved = KnowledgeLexicon.resolvedTitles(for: [item])[item.id]!
            precondition(keyword == resolved)
            precondition(item.title == title && item.learningGoal == goal)
            results.append(["stored_title": title, "learning_goal": goal, "display_title": resolved, "case": kind])
        }
        let data = try JSONSerialization.data(withJSONObject: results, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        print(String(decoding: data, as: UTF8.self))
    }
}
