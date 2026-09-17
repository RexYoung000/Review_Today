import Foundation
import SwiftUI

@main
struct AnswerDocumentContractTests {
    static func main() {
        let linked = AnswerLinkStyle.attributed("正文与[来源](https://example.com)及 `代码`")
        precondition(linked.runs.filter { $0.link != nil }.allSatisfy { $0.foregroundColor == Color.blue && $0.underlineStyle == .single })
        precondition(linked.runs.filter { $0.link == nil }.allSatisfy { $0.foregroundColor == nil })
        let reference = AnswerLinkStyle.reference("[官方 **说明**](https://example.com)")!
        precondition(reference.url.absoluteString == "https://example.com")
        precondition(String(reference.label.characters) == "官方 说明" && reference.label.runs.allSatisfy { $0.link == nil })
        precondition(AnswerLinkStyle.reference("正文与[来源](https://example.com)") == nil)
        let originalSentence = "不会没用，但**「有用」的地方会换位置**。这轮先只讲清楚换到哪儿去。"
        let emphasized = AnswerInlineMarkdown.parse(originalSentence)
        precondition(String(emphasized.characters) == "不会没用，但「有用」的地方会换位置。这轮先只讲清楚换到哪儿去。")
        precondition(emphasized.runs.contains {
            $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true &&
            String(emphasized[$0.range].characters) == "「有用」的地方会换位置"
        })
        for source in ["但**“有用”**的位置", "但**「甲」**与**「乙」**", "中文**（关键）**继续"] {
            let parsed = AnswerInlineMarkdown.parse(source)
            precondition(!String(parsed.characters).contains("**"), source)
            precondition(parsed.runs.contains { $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true })
        }
        // Native parsing remains authoritative for escaped/code/link/nested syntax.
        for source in [#"但\*\*「有用」\*\*"#, "`但**「有用」**`", "``但**「有用」**`代码``",
                       "**普通加粗**和 *斜体*", "***嵌套***", "**粗体中 *斜体* 结尾**",
                       "[链接](https://example.com/a**「b」**)", "[但**「有用」**](https://example.com)",
                       "<https://example.com/a**b**>", "未完成`但**「有用」**", "但**「有用」",
                       "但**「有用」的地方*", "空 ** 空 **", "原有\u{200A}空白"] {
            let native = try! AttributedString(markdown: source, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
            precondition(AnswerInlineMarkdown.parse(source) == native, source)
        }
        let combined = AnswerInlineMarkdown.parse("`**代码**`与但**「有用」**，[来源](https://example.com)")
        precondition(String(combined.characters) == "**代码**与但「有用」，来源")
        precondition(combined.runs.contains { $0.link?.absoluteString == "https://example.com" })
        precondition(combined.runs.contains { $0.inlinePresentationIntent?.contains(.code) == true })
        // Every partial stream preserves the native literal until the pair closes.
        let streamBold = "但**「有用」的地方**"
        for end in streamBold.indices {
            let prefix = String(streamBold[..<end])
            let native = try! AttributedString(markdown: prefix, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
            precondition(AnswerInlineMarkdown.parse(prefix) == native)
        }
        print("A009: CJK strong emphasis, exact text, code, escapes, links and streaming prefixes passed")
        let legacyNotice = "网页核验暂未完成，先讲基础内容；涉及变化或争议的部分仍需核实。"
        precondition(AnswerDocument.parse("正文\n\n" + legacyNotice).last?.kind == .notice(legacyNotice))
        precondition(AnswerDocument.parse("> [!NOTE]\n> 核验尚未完成").first?.kind == .notice("核验尚未完成"))
        precondition(AnswerDocument.parse("```text\n" + legacyNotice + "\n```").first?.kind == .code("text", legacyNotice))
        let mixed = """
        核心 **观点**。
        ## 原因
        - 第一项
          继续解释
          - 第二层
        > 一个例子
        > 换行保留
        ---
        | 问题 | 说明 |
        | --- | --- |
        | 知识更新 | 查询新资料 |
        """
        let blocks = AnswerDocument.parse(mixed)
        precondition(blocks.count == 6)
        precondition(blocks[1].kind == .heading(2, "原因"))
        precondition(blocks[2].kind == .list([
            .init(marker: "-", text: "第一项\n继续解释", indent: 0),
            .init(marker: "-", text: "第二层", indent: 1)]))
        precondition(blocks[3].kind == .quote("一个例子\n换行保留"))
        precondition(blocks[5].kind == .table(["问题", "说明"], [["知识更新", "查询新资料"]]))
        precondition(AnswerDocument.parse("1. 先检索\n2. 再回答")[0].kind == .list([
            .init(marker: "1.", text: "先检索", indent: 0), .init(marker: "2.", text: "再回答", indent: 0)]))
        precondition(AnswerDocument.parse("1、 先检索\n• 一个并列点")[0].kind == .list([
            .init(marker: "1、", text: "先检索", indent: 0), .init(marker: "•", text: "一个并列点", indent: 0)]))

        let pipe = "| a\\|b | \u{60}x|y\u{60} | \u{60}\u{60}x\u{60}|y\u{60}\u{60} |"
        precondition(AnswerDocument.cells(pipe) == ["a|b", "\u{60}x|y\u{60}", "\u{60}\u{60}x\u{60}|y\u{60}\u{60}"])
        let partialTable = "| A | B |\n| --- | --- |\n| 完整 | 数据 |\n| 中文😀"
        let partial = AnswerDocument.parse(partialTable)
        precondition(partial.last?.kind == .paragraph("| 中文😀"), "Partial rows must never disappear")
        let finished = AnswerDocument.parse(partialTable + " | 完成 |")
        precondition(finished.count == 1)
        precondition(finished[0].id == partial[0].id)

        let valid = "flowchart LR\nA[\"检索\"] --> B[\"组合\"] --> C[\"回答\"]"
        precondition(AnswerDocument.linearFlow(valid) == ["检索", "组合", "回答"])
        precondition(AnswerDocument.linearFlow("flowchart TD; B[第二]; A[第一]; A --> B") == ["第一", "第二"])
        precondition(AnswerDocument.linearFlow("flowchart TB\nA[\"第一;步\"] --> B[完成]") == ["第一;步", "完成"])
        let invalid = [
            "flowchart LR\nA[开始] --> B[结束]\nA --> C[分支]",
            "flowchart LR\nA[开始] --> B[结束]\nB --> A",
            "flowchart LR\nA[开始] --> B[结束]\nC[孤立]",
            "flowchart LR\nA[开始] --> B",
            "flowchart LR\nA[开始] --> B[结束]\nclick A \"file:///private\"",
            "flowchart LR\nA[开始] --> B[结束]\nstyle A fill:red",
            "flowchart LR\nA[开始] --> B[结束]\nA[不同内容]",
            "flowchart LR\nA[\"<script>text</script>\"] --> B[结束]",
            "flowchart LR\nA[开始] -->|条件| B[结束]",
        ]
        for source in invalid {
            precondition(AnswerDocument.linearFlow(source) == nil, source)
            let rendered = AnswerDocument.parse("~~~mermaid\n" + source + "\n~~~")
            precondition(rendered[0].kind == .code("mermaid", source), "Fallback must keep all source")
        }
        let open = AnswerDocument.parse("先讲知识。\n\n~~~mermaid\nflowchart LR\nA[\"检索\"] --> B[\"组")
        precondition(open[1].kind == .flow(["检索", "组"], complete: false))
        let close = AnswerDocument.parse("先讲知识。\n\n~~~mermaid\n" + valid + "\n~~~")
        precondition(close[1].kind == .flow(["检索", "组合", "回答"], complete: true))
        precondition(open[0] == close[0] && open[1].id == close[1].id)

        let literal = "~~~python\n# 保留代码\nx = '**中文**'\n~~~"
        precondition(AnswerDocument.parse(literal)[0].kind == .code("python", "# 保留代码\nx = '**中文**'"))
        precondition(AnswerDocument.parse("普通\n换行")[0].kind == .paragraph("普通\n换行"))
        precondition(AnswerDocument.parse("**中文😀未闭合")[0].kind == .paragraph("**中文😀未闭合"))
        precondition(AnswerDocument.containsQuestion("为什么？", in: "### 想一想\n\n**为什么？**"))
        precondition(!AnswerDocument.containsQuestion("为什么？", in: "另一个问题？"))
        precondition(!AnswerDocument.containsQuestion(" ", in: "知识正文"))

        // Exercise every streaming prefix, including fence/Unicode/table boundaries.
        let stream = mixed + "\n\n~~~mermaid\n" + valid + "\n~~~\n\n结束。"
        for end in stream.indices {
            let parsed = AnswerDocument.parse(String(stream[..<end]))
            precondition(Set(parsed.map(\.id)).count == parsed.count)
        }
        let long = Array(repeating: mixed, count: 100).joined(separator: "\n\n")
        let start = Date()
        precondition(AnswerDocument.parse(long).count == 600)
        print("AnswerDocument: blocks, incremental rows/flows, malformed fallbacks, Unicode and question dedup passed; long parse \(Int(Date().timeIntervalSince(start) * 1000)) ms")
        if CommandLine.arguments.count > 1 {
            let raw = try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8)
            for line in raw.components(separatedBy: "\n") {
                guard let data = line.data(using: .utf8),
                      let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let response = value["response"] as? String, !response.isEmpty else { continue }
                let blocks = AnswerDocument.parse(response)
                let tables = blocks.filter { if case .table = $0.kind { true } else { false } }.count
                let flows = blocks.filter { if case .flow(_, complete: true) = $0.kind { true } else { false } }.count
                let fallbacks = blocks.filter { if case .code("mermaid", _) = $0.kind { true } else { false } }.count
                print("Real sample \(value["case"] ?? "unknown"): \(blocks.count) blocks, \(tables) tables, \(flows) flows, \(fallbacks) graph fallbacks")
            }
        }
    }
}
