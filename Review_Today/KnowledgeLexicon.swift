import Foundation

enum KnowledgeLexicon {
    private static let commandPrefixes = ["说明", "描述", "概括", "解释", "写出", "列出", "总结", "简述", "讲讲", "谈谈", "记住"]
    private static let genericTitles: Set<String> = [
        "RAG", "记住", "技术", "知识", "内容", "笔记", "其他", "未分类", "通用", "说明", "主题", "知识点"
    ]
    private static let genericThemes: Set<String> = [
        "技术", "知识", "其他", "未分类", "内容", "笔记", "通用", "主题", "知识点"
    ]
    private static let incompleteEnds = CharacterSet(charactersIn: "在的与和或及把对从于其并")

    static func displayTheme(for item: Knowledge) -> String {
        let raw = item.theme.trimmingCharacters(in: .whitespacesAndNewlines)
        if !raw.isEmpty, !genericThemes.contains(raw) { return raw }
        let blob = item.title + item.learningGoal + item.theme
        if blob.contains("RAG") || blob.contains("检索增强") {
            return "检索增强生成"
        }
        if blob.contains("向量嵌入") || blob.contains("向量数据库") {
            return "向量嵌入与检索"
        }
        let title = strongTitle(for: item)
        if !isWeak(title) { return title }
        return String(localized: "未命名主题")
    }

    static func keyword(for item: Knowledge, among siblings: [Knowledge] = [], clipped: Bool = false) -> String {
        let base = strongTitle(for: item)
        let clashes = siblings.filter { $0.id != item.id && strongTitle(for: $0) == base }
        if !clashes.isEmpty, let extra = disambiguator(for: item, base: base) {
            let combined = "\(base) · \(extra)"
            return clipped ? clip(combined) : combined
        }
        return clipped ? clip(base) : base
    }

    /// Resolve duplicate titles once for the list rather than scanning every
    /// sibling inside every sort comparison and every rendered chip.
    static func resolvedTitles(for items: [Knowledge]) -> [UUID: String] {
        let bases = Dictionary(uniqueKeysWithValues: items.map { ($0.id, strongTitle(for: $0)) })
        let counts = Dictionary(grouping: bases.values, by: { $0 }).mapValues(\.count)
        return Dictionary(uniqueKeysWithValues: items.map { item in
            let base = bases[item.id] ?? ""
            if (counts[base] ?? 0) > 1, let extra = disambiguator(for: item, base: base) {
                return (item.id, "\(base) · \(extra)")
            }
            return (item.id, base)
        })
    }
    static func chipTitle(for item: Knowledge, among siblings: [Knowledge], theme: String) -> String {
        chipTitle(resolved: keyword(for: item, among: siblings), theme: theme)
    }
    static func chipTitle(resolved title: String, theme: String) -> String {
        let text = stripCommandLead(stripRepeatedTheme(title, theme: theme))
        return isWeak(text) ? title : text
    }

    static func explanationPieces(for item: Knowledge) -> [ExplanationPiece] {
        let written = item.explanation.trimmingCharacters(in: .whitespacesAndNewlines)
        if !written.isEmpty { return parse(written) }
        let excerpt = item.evidenceExcerpt.trimmingCharacters(in: .whitespacesAndNewlines)
        if !excerpt.isEmpty { return parse(excerpt) }
        return parse(item.learningGoal)
    }

    static func mainQuestion(for item: Knowledge) -> Question? {
        item.questions.first {
            $0.variantIndex == 0
                && !$0.promptText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    static func scoring(for item: Knowledge) -> AgentAPI.ScoringSpec? {
        guard let json = mainQuestion(for: item)?.scoringSpecJSON,
              let data = json.data(using: .utf8)
        else { return nil }
        return try? JSONDecoder().decode(AgentAPI.ScoringSpec.self, from: data)
    }

    static func previewUnavailableReason(for item: Knowledge) -> String? {
        guard item.lifecycle != "soft_deleted" else {
            return String(localized: "恢复使用后可以试一题。")
        }
        guard mainQuestion(for: item) != nil else {
            return String(localized: "缺少主问题，暂时不能试一题。")
        }
        guard let spec = scoring(for: item) else {
            return String(localized: "评分规格无法读取，暂时不能试一题。")
        }
        guard !spec.learningGoal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              spec.mustCover.contains(where: { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
        else {
            return String(localized: "评分关键点不完整，暂时不能试一题。")
        }
        guard !item.evidenceExcerpt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !spec.evidence.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            return String(localized: "缺少来源证据，暂时不能试一题。")
        }
        return nil
    }

    static func needsLegacyTitleFallback(title: String, goal: String) -> Bool {
        let source = stripCommandLead(goal).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, source.count > title.count, source.hasPrefix(title) else { return false }
        // Evidence-backed legacy cuts: an unfinished quantity or a cut word.
        // A complete short title such as “RAG” or “矩阵的阶” remains unchanged.
        let unfinishedQuantity = title.range(of: "[一二三四五六七八九十0-9]+个$", options: .regularExpression) != nil
        let cutStage = title.hasSuffix("阶") && source.dropFirst(title.count).hasPrefix("段")
        return unfinishedQuantity || cutStage
    }

    private static func strongTitle(for item: Knowledge) -> String {
        let title = item.title.trimmingCharacters(in: .whitespacesAndNewlines)
        let goal = item.learningGoal.trimmingCharacters(in: .whitespacesAndNewlines)
        if !isWeak(title) && !needsLegacyTitleFallback(title: title, goal: goal) { return title }
        // Legacy imported cards have no title. Use the full existing goal rather
        // than heuristically cutting a noun phrase, an English term or a word.
        if !goal.isEmpty { return stripCommandLead(goal) }
        let theme = item.theme.trimmingCharacters(in: .whitespacesAndNewlines)
        return theme.isEmpty ? String(localized: "知识点") : theme
    }

    private static func stripRepeatedTheme(_ text: String, theme: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let aliases = [theme, "检索增强生成 (RAG)", "检索增强生成", "RAG"]
            .filter { !$0.isEmpty }
            .sorted { $0.count > $1.count }
        for alias in aliases {
            guard value != alias, value.hasPrefix(alias) else { continue }
            var rest = String(value.dropFirst(alias.count))
                .trimmingCharacters(in: CharacterSet(charactersIn: " ·・-—：:（）()"))
            if rest.hasPrefix("的") { rest = String(rest.dropFirst()).trimmingCharacters(in: .whitespaces) }
            if rest.count >= 2 { value = rest }
        }
        return value
    }

    private static func stripCommandLead(_ text: String) -> String {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for prefix in commandPrefixes + ["什么是"] where value.hasPrefix(prefix) {
            let rest = String(value.dropFirst(prefix.count))
                .trimmingCharacters(in: CharacterSet(charactersIn: "：: 的"))
            if rest.count >= 2 { return rest }
        }
        return value
    }

    private static func nounPhrase(from goal: String) -> String {
        var text = goal.trimmingCharacters(in: .whitespacesAndNewlines)
        for prefix in commandPrefixes where text.hasPrefix(prefix) {
            text = String(text.dropFirst(prefix.count))
                .trimmingCharacters(in: CharacterSet(charactersIn: "：: 的"))
            break
        }
        if let range = text.range(of: "在"), text[range.upperBound...].contains("中") {
            let head = String(text[..<range.lowerBound]).trimmingCharacters(in: .whitespaces)
            if head.count >= 2 { return finishPhrase(head) }
        }
        let breaks = CharacterSet(charactersIn: "：:，,。. —-")
        if let idx = text.unicodeScalars.firstIndex(where: { breaks.contains($0) }) {
            let prefix = String(text[..<idx]).trimmingCharacters(in: .whitespaces)
            if prefix.count >= 2, !prefix.hasSuffix("在") { return finishPhrase(prefix) }
        }
        return finishPhrase(text)
    }

    private static func finishPhrase(_ text: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = value.last, String(last).unicodeScalars.allSatisfy({ incompleteEnds.contains($0) }), value.count > 2 {
            value.removeLast()
            value = value.trimmingCharacters(in: .whitespaces)
        }
        return value
    }

    private static func isWeak(_ text: String) -> Bool {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.count < 2 { return true }
        if genericTitles.contains(value) { return true }
        if let last = value.last, String(last).unicodeScalars.allSatisfy({ incompleteEnds.contains($0) }) {
            return true
        }
        return false
    }

    private static func stripLeadingAcronym(_ text: String, theme: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for token in [theme, "RAG", "检索增强生成"].filter({ !$0.isEmpty }) where value.hasPrefix(token) {
            value = String(value.dropFirst(token.count))
                .trimmingCharacters(in: CharacterSet(charactersIn: " 的：:，,"))
        }
        return finishPhrase(value)
    }

    private static func disambiguator(for item: Knowledge, base: String) -> String? {
        var rest = item.learningGoal
        if let range = rest.range(of: base) {
            rest = String(rest[range.upperBound...])
        }
        rest = rest.trimmingCharacters(in: CharacterSet(charactersIn: " 的：:，,。"))
        rest = stripLeadingAcronym(rest, theme: item.theme)
        rest = finishPhrase(rest)
        if rest.count >= 2, rest != base, !isWeak(rest) { return rest }
        return nil
    }

    private static func clip(_ text: String) -> String {
        if text.count > 22 { return String(text.prefix(22)) + "…" }
        return text
    }

    static func parse(_ text: String) -> [ExplanationPiece] {
        text.replacingOccurrences(of: "\r\n", with: "\n")
            .components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .map(parseLine)
    }

    private static func parseLine(_ line: String) -> ExplanationPiece {
        // A dot immediately followed by a digit may be a decimal or a version.
        // Only explicit list markers become rows; prose keeps its text intact.
        if let match = firstMatch(#"^(\d+)\s*(?:[、．\)]\s*|\.\s+)(.+)$"#, in: line),
           match.count >= 3, let number = Int(match[1]) {
            return .numbered(number, match[2])
        }
        if let match = firstMatch(#"^(?:[-*]\s+|[•·]\s*)(.+)$"#, in: line), match.count >= 2 {
            return .bullet(match[1])
        }
        return .paragraph(line)
    }

    private static func firstMatch(_ pattern: String, in text: String) -> [String]? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, range: range) else { return nil }
        return (0..<match.numberOfRanges).compactMap { index in
            guard let swiftRange = Range(match.range(at: index), in: text) else { return nil }
            return String(text[swiftRange])
        }
    }
}

struct ExplanationPiece: Hashable {
    enum Kind: Hashable {
        case numbered(Int)
        case bullet
        case paragraph
    }

    var kind: Kind
    var text: String

    static func numbered(_ number: Int, _ text: String) -> ExplanationPiece {
        ExplanationPiece(kind: .numbered(number), text: text)
    }

    static func bullet(_ text: String) -> ExplanationPiece {
        ExplanationPiece(kind: .bullet, text: text)
    }

    static func paragraph(_ text: String) -> ExplanationPiece {
        ExplanationPiece(kind: .paragraph, text: text)
    }
}
