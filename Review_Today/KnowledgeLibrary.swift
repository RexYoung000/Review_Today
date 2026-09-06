import SwiftData
import SwiftUI

struct LibraryView: View {
    @Binding var selectedID: UUID?
    var coordinator: ReviewCoordinator

    @Query(sort: \Knowledge.theme) private var allItems: [Knowledge]
    @Environment(\.runway) private var runway
    @State private var filter = "active"
    @State private var theme = "all"
    @State private var showDeck = false
    @State private var browsingIndex = 0

    private var items: [Knowledge] {
        allItems.filter { $0.lifecycle == filter }
    }

    private var themes: [String] {
        Array(Set(items.map { KnowledgeLexicon.displayTheme(for: $0) }.filter { !$0.isEmpty })).sorted()
    }

    private var visibleItems: [Knowledge] {
        items.filter { theme == "all" || KnowledgeLexicon.displayTheme(for: $0) == theme }
    }

    private var groupedItems: [(theme: String, items: [Knowledge])] {
        let visible = visibleItems
        var buckets: [String: [Knowledge]] = [:]
        for item in visible {
            buckets[KnowledgeLexicon.displayTheme(for: item), default: []].append(item)
        }
        return buckets.keys.sorted().map { key in
            let group = buckets[key]!.sorted {
                KnowledgeLexicon.keyword(for: $0, among: visible)
                    < KnowledgeLexicon.keyword(for: $1, among: visible)
            }
            return (key, group)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if visibleItems.isEmpty {
                emptyState
            } else {
                GeometryReader { geo in
                    let columns = Self.chipColumns(for: geo.size.width - Runway.section * 2)
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Runway.section) {
                            ForEach(groupedItems, id: \.theme) { group in
                                sectionBlock(group, columns: columns)
                            }
                        }
                        .padding(.horizontal, Runway.section)
                        .padding(.top, Runway.gap)
                        .padding(.bottom, 40)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
        .background(PaperSurface())
        .navigationTitle(String(localized: "知识库"))
        .overlay {
            if showDeck, !visibleItems.isEmpty {
                KnowledgeDeckOverlay(
                    items: visibleItems,
                    index: $browsingIndex,
                    coordinator: coordinator,
                    onClose: closeDeck
                )
            }
        }
        .onChange(of: selectedID) { _, _ in
            openSelectedKnowledgeIfNeeded()
        }
        .onChange(of: allItems.map(\.id), initial: true) { _, _ in
            openSelectedKnowledgeIfNeeded()
        }
        .onChange(of: browsingIndex) { _, newValue in
            if visibleItems.indices.contains(newValue) {
                selectedID = visibleItems[newValue].id
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            HStack(alignment: .firstTextBaseline) {
                Text(String(localized: "知识库"))
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(runway.ink)
                Spacer(minLength: 12)
                if !visibleItems.isEmpty {
                    Text("\(visibleItems.count)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: Runway.gap) {
                filterTrack {
                    FilterPill(title: String(localized: "在用"), selected: filter == "active") {
                        filter = "active"
                    }
                    FilterPill(title: String(localized: "已暂停"), selected: filter == "paused") {
                        filter = "paused"
                    }
                    FilterPill(title: String(localized: "已删除"), selected: filter == "soft_deleted") {
                        filter = "soft_deleted"
                    }
                }

                if !themes.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        filterTrack {
                            FilterPill(title: String(localized: "全部"), selected: theme == "all") { theme = "all" }
                            ForEach(themes, id: \.self) { name in
                                FilterPill(title: name, selected: theme == name) { theme = name }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(.horizontal, Runway.section)
        .padding(.top, Runway.gap)
        .padding(.bottom, Runway.space)
    }

    private func filterTrack<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        HStack(spacing: 4) {
            content()
        }
        .padding(4)
        .background(runway.field, in: Capsule())
    }

    private func sectionBlock(_ group: (theme: String, items: [Knowledge]), columns: [GridItem]) -> some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            HStack(alignment: .firstTextBaseline, spacing: Runway.space) {
                Text(group.theme)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(runway.ink)
                Text("\(group.items.count)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
            LazyVGrid(columns: columns, alignment: .leading, spacing: Runway.gap) {
                ForEach(group.items, id: \.id) { item in
                    SummaryChip(
                        title: KnowledgeLexicon.chipTitle(for: item, among: group.items, theme: group.theme)
                    ) {
                        openDeck(item)
                    }
                    .contextMenu { chipMenu(item) }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static func chipColumns(for width: CGFloat) -> [GridItem] {
        let spacing = Runway.gap
        let minWidth: CGFloat = 252
        let count = max(1, min(3, Int((width + spacing) / (minWidth + spacing))))
        return Array(repeating: GridItem(.flexible(), spacing: spacing, alignment: .top), count: count)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            CoachMark(pose: .waitYou, size: 64)
            Text(emptyCopy)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var emptyCopy: String {
        switch filter {
        case "paused": String(localized: "没有已暂停的知识。")
        case "soft_deleted": String(localized: "没有已软删除的知识。")
        default: String(localized: "还没有知识点。在今天记录想记住的内容。")
        }
    }

    private func openSelectedKnowledgeIfNeeded() {
        guard !showDeck,
              let selectedID,
              let match = allItems.first(where: { $0.id == selectedID })
        else { return }
        filter = match.lifecycle
        theme = "all"
        openDeck(match)
    }

    private func openDeck(_ item: Knowledge) {
        if let i = visibleItems.firstIndex(where: { $0.id == item.id }) {
            browsingIndex = i
        }
        selectedID = item.id
        showDeck = true
    }

    private func closeDeck() {
        showDeck = false
    }

    @ViewBuilder
    private func chipMenu(_ item: Knowledge) -> some View {
        if item.lifecycle == "active" {
            Button(String(localized: "暂停")) { item.lifecycle = "paused" }
            Button(String(localized: "软删除"), role: .destructive) { item.lifecycle = "soft_deleted" }
        } else {
            Button(String(localized: "恢复")) { item.lifecycle = "active" }
        }
    }
}

private struct SummaryChip: View {
    var title: String
    var action: () -> Void
    @State private var hovering = false
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: action) {
            IconLeadRow(iconWidth: 22, spacing: 12) {
                Image(systemName: "plus")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(runway.plus)
                    .frame(height: 20, alignment: .center)
            } content: {
                Text(title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .multilineTextAlignment(.leading)
                    .lineLimit(2)
            }
            .padding(.horizontal, Runway.gap)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, minHeight: 72, maxHeight: 72, alignment: .leading)
            .background(runway.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous)
                    .strokeBorder(runway.hairline, lineWidth: 1)
            )
            .shadow(color: runway.liftShadow, radius: hovering ? Runway.shadowBlur : 10, y: hovering ? 6 : Runway.shadowY)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(Runway.spring, value: hovering)
    }
}

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

    static func chipTitle(for item: Knowledge, among siblings: [Knowledge], theme: String) -> String {
        var text = keyword(for: item, among: siblings)
        text = stripRepeatedTheme(text, theme: theme)
        text = stripCommandLead(text)
        if isWeak(text) { return keyword(for: item, among: siblings) }
        return text
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

    private static func strongTitle(for item: Knowledge) -> String {
        let fromField = finishPhrase(item.title)
        if !isWeak(fromField) { return fromField }
        let fromGoal = finishPhrase(nounPhrase(from: item.learningGoal))
        if !isWeak(fromGoal) { return fromGoal }
        let stripped = stripLeadingAcronym(fromGoal.isEmpty ? item.learningGoal : fromGoal, theme: item.theme)
        if !isWeak(stripped) { return stripped }
        let fromTheme = finishPhrase(item.theme)
        if !isWeak(fromTheme) { return fromTheme }
        return fromGoal.isEmpty ? String(localized: "知识点") : fromGoal
    }

    private static func stripRepeatedTheme(_ text: String, theme: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let aliases = [theme, "检索增强生成 (RAG)", "检索增强生成", "RAG"]
            .filter { !$0.isEmpty }
            .sorted { $0.count > $1.count }
        for alias in aliases {
            guard value != alias, value.hasPrefix(alias) else { continue }
            let rest = String(value.dropFirst(alias.count))
                .trimmingCharacters(in: CharacterSet(charactersIn: " ·・-—：:（）()"))
            if rest.count >= 2 { value = rest }
        }
        return value
    }

    private static func stripCommandLead(_ text: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
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
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
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
        rest = finishPhrase(String(rest.prefix(14)))
        if rest.count >= 2, rest != base, !isWeak(rest) { return rest }
        return nil
    }

    private static func clip(_ text: String) -> String {
        if text.count > 22 { return String(text.prefix(22)) + "…" }
        return text
    }

    static func parse(_ text: String) -> [ExplanationPiece] {
        let normalized = text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "......", with: "\n")
            .replacingOccurrences(of: "……", with: "\n")
            .replacingOccurrences(of: "…", with: "\n")
        let lines = normalized
            .components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }

        if lines.count > 1 {
            return lines.prefix(8).enumerated().map { parseLine($0.element, fallbackIndex: $0.offset + 1) }
        }

        let steps = splitSteps(normalized)
        if steps.count > 1 {
            return steps.prefix(6).enumerated().map { ExplanationPiece.numbered($0.offset + 1, tidy($0.element)) }
        }

        if let numbered = splitInlineNumbers(normalized), numbered.count >= 2 {
            return numbered
        }

        let sentences = splitSentences(normalized).map(tidy).filter { $0.count > 3 }
        if sentences.count >= 2 {
            return sentences.prefix(6).enumerated().map { ExplanationPiece.numbered($0.offset + 1, $0.element) }
        }
        if let only = sentences.first, !only.isEmpty {
            return [.paragraph(only)]
        }
        return [.paragraph(normalized.trimmingCharacters(in: .whitespacesAndNewlines))]
    }

    private static func parseLine(_ line: String, fallbackIndex: Int) -> ExplanationPiece {
        if let match = firstMatch(#"^(\d+)\s*[\.、．\)]\s*(.+)$"#, in: line), match.count >= 3,
           let number = Int(match[1]) {
            return .numbered(number, tidy(match[2]))
        }
        if let match = firstMatch(#"^第\s*([0-9一二三四五六七八九十]+)\s*[步点条]\s*[：:.]?\s*(.+)$"#, in: line),
           match.count >= 3 {
            return .numbered(fallbackIndex, tidy(match[2]))
        }
        if let match = firstMatch(#"^[-*•·]\s*(.+)$"#, in: line), match.count >= 2 {
            return .bullet(tidy(match[1]))
        }
        return .numbered(fallbackIndex, tidy(line))
    }

    private static func splitInlineNumbers(_ text: String) -> [ExplanationPiece]? {
        guard let regex = try? NSRegularExpression(pattern: #"\d+\s*[\.、．\)]\s*"#) else { return nil }
        let nsText = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
        guard matches.count >= 2 else { return nil }
        var pieces: [ExplanationPiece] = []
        for (index, match) in matches.enumerated() {
            let start = match.range.location + match.range.length
            let end = index + 1 < matches.count ? matches[index + 1].range.location : nsText.length
            let body = nsText.substring(with: NSRange(location: start, length: max(0, end - start)))
            let cleaned = tidy(body)
            if !cleaned.isEmpty { pieces.append(.numbered(index + 1, cleaned)) }
        }
        return pieces.count >= 2 ? pieces : nil
    }

    private static func splitSentences(_ text: String) -> [String] {
        var sentences: [String] = []
        var current = ""
        for character in text {
            current.append(character)
            if "。！？；;".contains(character) {
                let piece = current.trimmingCharacters(in: .whitespaces)
                if !piece.isEmpty { sentences.append(piece) }
                current = ""
            }
        }
        let tail = current.trimmingCharacters(in: .whitespaces)
        if !tail.isEmpty { sentences.append(tail) }
        return sentences
    }

    private static func splitSteps(_ text: String) -> [String] {
        guard let regex = try? NSRegularExpression(pattern: #"第\s*[0-9一二三四五六七八九十]+\s*步"#) else {
            return [text]
        }
        let nsText = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
        guard matches.count >= 2 else { return [text] }
        var parts: [String] = []
        for (index, match) in matches.enumerated() {
            let start = match.range.location
            let end = index + 1 < matches.count ? matches[index + 1].range.location : nsText.length
            let piece = nsText.substring(with: NSRange(location: start, length: end - start))
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !piece.isEmpty { parts.append(piece) }
        }
        return parts
    }

    private static func tidy(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "。；;"))
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

struct ExplanationPiece: Identifiable, Hashable {
    enum Kind: Hashable {
        case numbered(Int)
        case bullet
        case paragraph
    }

    var kind: Kind
    var text: String
    var id: String { "\(kind)-\(text)" }

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

private struct KnowledgeDeckOverlay: View {
    var items: [Knowledge]
    @Binding var index: Int
    var coordinator: ReviewCoordinator
    var onClose: () -> Void

    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway
    @Query private var fsrsRows: [FsrsState]
    @Query private var attempts: [ReviewAttempt]
    @Environment(\.modelContext) private var modelContext
    @State private var confirmPermanent = false

    var body: some View {
        ZStack {
            runway.scrim
                .ignoresSafeArea()
                .onTapGesture(perform: onClose)

            DepthCarousel(items: deckItems, index: $index) { wrapper in
                KnowledgeDepthCard(
                    item: wrapper.item,
                    siblings: items,
                    onPreview: {
                        guard let question = KnowledgeLexicon.mainQuestion(for: wrapper.item),
                              KnowledgeLexicon.previewUnavailableReason(for: wrapper.item) == nil
                        else { return }
                        coordinator.startPreview(
                            knowledgeID: wrapper.item.id,
                            questionID: question.id
                        )
                        openWindow(id: "review")
                        onClose()
                    },
                    onDelete: { confirmPermanent = true }
                )
            }
            .padding(.horizontal, 36)
            .padding(.vertical, 28)

            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(runway.ink)
                    .frame(width: 32, height: 32)
                    .background(runway.card.opacity(0.94), in: Circle())
                    .shadow(color: runway.liftShadow, radius: Runway.shadowBlur, y: Runway.shadowY)
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.cancelAction)
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
        }
        .alert(String(localized: "永久删除这条知识？"), isPresented: $confirmPermanent) {
            Button(String(localized: "取消"), role: .cancel) {}
            Button(String(localized: "永久删除"), role: .destructive) {
                if items.indices.contains(index) {
                    permanentlyDelete(items[index])
                }
            }
        } message: {
            Text(String(localized: "此操作不能恢复。来源若还被其他知识使用会保留。"))
        }
    }

    private var deckItems: [DeckItem] {
        items.map { DeckItem(id: $0.id, item: $0) }
    }

    private func permanentlyDelete(_ item: Knowledge) {
        let id = item.id
        if let state = fsrsRows.first(where: { $0.knowledgeId == id }) {
            modelContext.delete(state)
        }
        for attempt in attempts where attempt.knowledgeId == id {
            modelContext.delete(attempt)
        }
        let source = item.source
        modelContext.delete(item)
        if let source,
           source.knowledgeItems.filter({ $0.id != id }).isEmpty,
           source.tasks.isEmpty {
            modelContext.delete(source)
        }
        try? modelContext.save()
        onClose()
    }
}

private struct DeckItem: Identifiable {
    var id: UUID
    var item: Knowledge
}

private struct KnowledgeDepthCard: View {
    var item: Knowledge
    var siblings: [Knowledge]
    var onPreview: () -> Void
    var onDelete: () -> Void
    @Environment(\.runway) private var runway

    private var mainQuestion: Question? { KnowledgeLexicon.mainQuestion(for: item) }
    private var spec: AgentAPI.ScoringSpec? { KnowledgeLexicon.scoring(for: item) }
    private var previewUnavailableReason: String? { KnowledgeLexicon.previewUnavailableReason(for: item) }
    private var cover: [String] {
        spec?.mustCover.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } ?? []
    }
    private var mixups: [String] {
        spec?.commonMisconceptions.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } ?? []
    }
    private var orderHint: String {
        spec?.orderRules.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
    private var pieces: [ExplanationPiece] { KnowledgeLexicon.explanationPieces(for: item) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: Runway.space) {
                Text(KnowledgeLexicon.displayTheme(for: item))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(KnowledgeLexicon.keyword(for: item, among: siblings))
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(runway.ink)
                    .lineSpacing(2)
                    .lineLimit(2)
            }
            .padding(.horizontal, Runway.gap)
            .padding(.top, Runway.gap)
            .padding(.bottom, 12)

            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: Runway.section) {
                    detailBlock
                    questionBlock
                    memoryBlock
                    sourceBlock
                }
                .padding(.horizontal, Runway.gap)
                .padding(.bottom, Runway.gap)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            .scrollIndicators(.visible)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            VStack(alignment: .leading, spacing: Runway.space) {
                if let previewUnavailableReason {
                    Label(previewUnavailableReason, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(Color.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(alignment: .center, spacing: Runway.space) {
                    Text("下次 \(item.dueAt.formatted(date: .abbreviated, time: .omitted))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Menu {
                        if item.lifecycle == "active" {
                            Button(String(localized: "暂停")) { item.lifecycle = "paused" }
                            Button(String(localized: "软删除"), role: .destructive) { item.lifecycle = "soft_deleted" }
                        } else {
                            Button(String(localized: "恢复")) { item.lifecycle = "active" }
                        }
                        Button(String(localized: "永久删除"), role: .destructive, action: onDelete)
                    } label: {
                        Image(systemName: "ellipsis")
                            .font(.body.weight(.medium))
                            .foregroundStyle(.secondary)
                            .frame(width: 28, height: 28)
                    }
                    .menuStyle(.borderlessButton)
                    RunwayPrimaryButton(
                        title: String(localized: "试一题"),
                        enabled: previewUnavailableReason == nil,
                        action: onPreview
                    )
                }
            }
            .padding(.horizontal, Runway.gap)
            .padding(.top, 12)
            .padding(.bottom, Runway.gap)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(runway.card)
    }

    private var detailBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "详解"))
                .font(.caption)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 12) {
                ForEach(pieces) { piece in
                    explanationRow(piece)
                }
            }
        }
    }

    private var questionBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "主问题"))
                .font(.caption)
                .foregroundStyle(.secondary)
            if let mainQuestion {
                Text(mainQuestion.promptText)
                    .font(.body.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(String(localized: "这张卡还没有可用的主问题。"))
                    .font(.callout)
                    .foregroundStyle(Color.orange)
            }
        }
    }

    private var memoryBlock: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(String(localized: "判断关键点"))
                .font(.caption)
                .foregroundStyle(.secondary)
            if !orderHint.isEmpty {
                Text(orderHint)
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if cover.isEmpty && mixups.isEmpty && orderHint.isEmpty {
                Text(String(localized: "先说出学习目标里的限定，再用自己的话讲核心含义。"))
                    .font(.callout)
                    .foregroundStyle(runway.copy)
            }
            ForEach(Array(cover.prefix(4).enumerated()), id: \.offset) { _, line in
                memoryRow(line, ok: true)
            }
            ForEach(Array(mixups.prefix(3).enumerated()), id: \.offset) { _, line in
                memoryRow(line, ok: false)
            }
        }
    }

    private var sourceBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            HStack(alignment: .firstTextBaseline) {
                Text(String(localized: "来源证据"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: Runway.space)
                if let locator = sourceLocator {
                    Link(String(localized: "打开来源"), destination: locator)
                        .font(.caption)
                } else {
                    Text(String(localized: "来自你提交的原文"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            let evidence = item.evidenceExcerpt.trimmingCharacters(in: .whitespacesAndNewlines)
            if evidence.isEmpty {
                Text(String(localized: "没有可核对的原文证据。"))
                    .font(.callout)
                    .foregroundStyle(Color.orange)
            } else {
                Text("“\(evidence)”")
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .lineSpacing(4)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(Runway.gap)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(runway.field, in: RoundedRectangle(cornerRadius: Runway.innerRadius, style: .continuous))
            }
        }
    }

    private var sourceLocator: URL? {
        let locator = item.evidenceLocator.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: locator),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme)
        else { return nil }
        return url
    }

    @ViewBuilder
    private func explanationRow(_ piece: ExplanationPiece) -> some View {
        switch piece.kind {
        case .numbered(let number):
            IconLeadRow {
                Text("\(number)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(runway.onAction)
                    .frame(width: 22, height: 22)
                    .background(runway.ink, in: Circle())
            } content: {
                Text(piece.text)
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .bullet:
            IconLeadRow {
                Circle()
                    .fill(runway.copy)
                    .frame(width: 6, height: 6)
                    .padding(.top, 7)
            } content: {
                Text(piece.text)
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .paragraph:
            Text(piece.text)
                .font(.callout)
                .foregroundStyle(runway.copy)
                .lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func memoryRow(_ text: String, ok: Bool) -> some View {
        IconLeadRow {
            Image(systemName: ok ? "checkmark" : "xmark")
                .font(.callout.weight(.bold))
                .foregroundStyle(ok ? runway.plus : Color.orange)
                .frame(height: 20, alignment: .center)
        } content: {
            Text(text)
                .font(.callout)
                .foregroundStyle(ok ? runway.copy : .secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityLabel((ok ? String(localized: "要覆盖") : String(localized: "别搞混")) + " " + text)
    }
}
