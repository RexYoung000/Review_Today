import Foundation

@main
struct AgentSpeechSegmentsTests {
    static func main() {
        typealias Segments = AgentSpeechSegments
        func speech(_ source: String, final: Bool = true, limit: Int = 180) -> [String] {
            Segments.project(source, final: final, maxCharacters: limit).filter { $0.kind == .speech }.map(\.text)
        }
        func check(_ value: @autoclosure () -> Bool, _ message: String) { precondition(value(), message) }
        func stablePrefixes(_ source: String) {
            var previous: [Segments.Segment] = []
            var prefix = ""
            for character in source {
                prefix.append(character)
                let projected = Segments.project(prefix)
                check(Array(projected.prefix(previous.count)) == previous, "An append changed an emitted segment: \(prefix)")
                check(projected.allSatisfy { $0.sourceEnd <= prefix.utf16.count }, "Source offsets exceed current text")
                previous = projected
            }
            let complete = Segments.project(source, final: true)
            check(Array(complete.prefix(previous.count)) == previous, "Final flush changed already emitted segments")
            check(zip(complete, complete.dropFirst()).allSatisfy { $0.sourceEnd <= $1.sourceEnd }, "Source offsets must be monotonic")
        }

        check(speech("不要改成 30 秒。应保留 3.14 和版本 2.0.1！可以吗？") == ["不要改成 30 秒。", "应保留 3.14 和版本 2.0.1！", "可以吗？"], "Negation, digits and Chinese boundaries must survive")
        check(speech("Dr. Lee uses version 2.0.1. It is not 3.14! Why?") == ["Dr. Lee uses version 2.0.1.", "It is not 3.14!", "Why?"], "English abbreviations and decimals must not create premature sentences")
        check(Segments.project("已完成的一句。\n未完成的一句").map(\.text) == ["已完成的一句。"], "Only confirmed complete lines stream")
        check(Segments.project("末行有句号。").isEmpty, "An unfinished line may still become a table header")
        check(speech("未带句号的完整尾段") == ["未带句号的完整尾段"], "Final must flush a complete remainder")

        let markdown = "# 关键点\n\n- **不要**把 30 改成 300。\n> 请看[官方 **说明**](https://example.com/a_(b)?secret=42)。\n变量 foo_bar 保留，2*3*4 不是 234，-3.5 < 0。\n"
        let projectedMarkdown = speech(markdown).joined()
        check(projectedMarkdown.contains("不要把 30 改成 300。") && projectedMarkdown.contains("官方 说明"), "Markdown projection must keep visible content")
        check(projectedMarkdown.contains("foo_bar") && projectedMarkdown.contains("2*3*4") && projectedMarkdown.contains("-3.5 < 0"), "Literal math, identifiers and negative numbers must remain")
        check(!projectedMarkdown.contains("https") && !projectedMarkdown.contains("secret") && !projectedMarkdown.contains("**"), "URLs and format markers must not be spoken")

        let visual = "开头。\n\n```swift\nprint(\"CODE_SECRET\")\n```\n\n| 不要提前读。 | 30 |\n| --- | --- |\n| TABLE_SECRET | 300 |\n\n~~~mermaid\nflowchart LR\nA[DIAGRAM_SECRET] --> B\n~~~\n\n结尾。\n"
        let visualProjection = Segments.project(visual)
        check(visualProjection.filter { $0.kind == .visualNotice }.count == 3, "Each skipped code/table/diagram block needs an explicit notice")
        check(visualProjection.filter { $0.kind == .speech }.map(\.text) == ["开头。", "结尾。"], "Visual block contents must never enter speech")
        check(visualProjection.filter { $0.kind == .visualNotice }.allSatisfy { $0.text == "图表/代码请看文字。" }, "Skipped blocks must be disclosed")
        check(Segments.project("```swift\n不要读这段。\n").isEmpty, "An open code fence cannot be spoken")
        check(Segments.project("```swift\n不要读这段。", final: true).first?.kind == .visualNotice, "An unfinished final fence must still be disclosed")
        check(Segments.project("[不要提前读。](https://example.com\n").isEmpty, "An open link must hold its label and URL")
        check(Segments.project("[不要提前读。](https://example.com", final: true).map(\.text) == ["链接请看文字。"], "Malformed final link must not expose its destination")
        check(speech("地址 https://example.com/secret?q=30 然后继续。\n").joined() == "地址然后继续。", "A plain URL is omitted without deleting surrounding prose")
        check(Segments.project("地址 https://example.com/secret?q=30 然后继续。\n").contains { $0.kind == .visualNotice && $0.text == "链接请看文字。" }, "URL omission is explicit")
        check(!speech("访问 example.com/private 或 user@example.org，正文不变。\n").joined().contains("example"), "Bare addresses and emails must not be read")
        check(speech("不要执行 `rm -rf SECRET`，请看文字。\n").joined() == "不要执行，请看文字。", "Inline code is explicitly skipped, never executed or read")

        let long = Array(repeating: "不要改成 30 秒，", count: 15).joined() + "必须保留 3.14。"
        let bounded = Segments.project(long, final: true, maxCharacters: 40)
        check(bounded.allSatisfy { $0.text.utf16.count <= 40 }, "Every emitted sentence must obey the UTF-16 bound")
        check(bounded.map(\.text).joined() == long, "Safe splitting must not remove or rewrite any content")
        let numerical = "不要分开这些数值 " + String(repeating: "1", count: 28) + ",000。"
        let numericalSegments = Segments.project(numerical, final: true, maxCharacters: 40)
        check(!numericalSegments.contains { $0.kind == .speech && $0.text.hasSuffix(",") }, "A comma inside a number is not a safe speech boundary")
        let unbroken = String(repeating: "a", count: 220) + "。"
        check(Segments.project(unbroken, final: true).map(\.text) == ["这段内容较长，请看文字。"], "An oversized unbreakable token must not be silently truncated")
        let emoji = "👨‍👩‍👧‍👦 不要改成 30 秒。\r\n最后🙂。"
        let emojiProjection = Segments.project(emoji, final: true)
        check(emojiProjection.last?.sourceEnd == emoji.utf16.count, "sourceEnd uses UTF-16, including emoji and CRLF")

        for sample in [markdown, visual, emoji,
                       "前句。\n\n[标签。](https://example.com/a_(b))与后句。\n",
                       "**不要**改成 30 秒。\n\n这是完整尾段",
                       "不要先读。 | 值\n--- | ---\n表内不要读。 | 30\n\n可以读了。\n",
                       "代码前。\n\n````swift\n```\nCODE_SECRET\n````\n\n代码后。\n",
                       "参考 https://example.com/path?q=3.14 ，不要改数字。\n"] {
            stablePrefixes(sample)
        }
        print("PASS: speech projection, stable streaming prefixes, UTF-16 offsets, Markdown, explicit omissions, negation/numbers and bounded sentences")
    }
}
