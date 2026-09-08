import SwiftData
import SwiftUI

struct LibraryView: View {
    @Binding var selectedID: UUID?
    var coordinator: ReviewCoordinator
    var onStartLearning: () -> Void = {}

    @Query(sort: \Knowledge.theme) private var allItems: [Knowledge]
    @Environment(\.runway) private var runway
    @State private var filter = "active"
    @State private var theme = "all"
    @State private var showDeck = false
    @State private var browsingIndex = 0
    @Environment(\.modelContext) private var modelContext
    @State private var selection = KnowledgeSelection()
    @State private var deletionImpact: KnowledgeDeletionImpact?
    @State private var operationError: String?
    @State private var undoTrash: [UUID: String] = [:]
    private var selectableIDs: Set<UUID> {
        Set(visibleItems.filter { KnowledgeLexicon.displayTheme(for: $0) == selection.group }.map(\.id))
    }

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
        let titles = KnowledgeLexicon.resolvedTitles(for: visible)
        var buckets: [String: [Knowledge]] = [:]
        for item in visible {
            buckets[KnowledgeLexicon.displayTheme(for: item), default: []].append(item)
        }
        return buckets.keys.sorted().map { key in
            let group = buckets[key]!.sorted {
                (titles[$0.id] ?? "") < (titles[$1.id] ?? "")
            }
            return (key, group)
        }
    }

    var body: some View {
        let deckTitles = KnowledgeLexicon.resolvedTitles(for: visibleItems)
        return VStack(alignment: .leading, spacing: 0) {
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
        .accessibilityHidden(showDeck)
        .disabled(showDeck)
        .overlay {
            if showDeck, !visibleItems.isEmpty {
                KnowledgeDeckOverlay(
                    items: visibleItems,
                    titles: deckTitles,
                    index: $browsingIndex,
                    coordinator: coordinator,
                    onClose: closeDeck,
                    onAction: { action, id in perform(action, ids: [id]) }
                )
            }
        }
        .sheet(item: $deletionImpact) { impact in
            KnowledgeDeletionSheet(impact: impact) { undoTrash = [:] }
        }
        .overlay(alignment: .bottom) {
            if operationError != nil || !undoTrash.isEmpty {
                HStack(spacing: 12) {
                    if let operationError { Text(operationError).foregroundStyle(.red) }
                    else { Text("已移到回收站 \(undoTrash.count) 条") }
                    if !undoTrash.isEmpty {
                        Button("撤销") {
                            do { try KnowledgeManagement.undoTrash(undoTrash, context: modelContext); undoTrash = [:]; operationError = nil }
                            catch { operationError = error.localizedDescription }
                        }
                    }
                    Button("关闭") { undoTrash = [:]; operationError = nil }
                }.font(.caption).padding(12).background(runway.card, in: RoundedRectangle(cornerRadius: 12)).padding(12)
            }
        }
        .onChange(of: filter) { _, _ in selection.finish(); operationError = nil }
        .onChange(of: theme) { _, _ in selection.finish(); operationError = nil }
        .onChange(of: selectableIDs) { _, ids in selection.reconcile(ids) }
        .onChange(of: visibleItems.map(\.id)) { _, ids in if ids.isEmpty { showDeck = false } }
        .onChange(of: themes) { _, names in
            if theme != "all" && !names.contains(theme) { theme = "all" }
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
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: Runway.gap) {
                statusFilters.fixedSize()
                if !themes.isEmpty { themeFilters.frame(minWidth: 240) }
                Spacer(minLength: 0)
                resultCount
            }
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) { statusFilters; Spacer(minLength: 8); resultCount }
                if !themes.isEmpty { themeFilters }
            }
        }
        .padding(.horizontal, Runway.section)
        .padding(.top, Runway.gap)
        .padding(.bottom, Runway.space)
    }

    private var resultCount: some View {
        Text("总数 \(visibleItems.count)").font(.subheadline).foregroundStyle(.secondary)
            .monospacedDigit().fixedSize().accessibilityLabel("当前筛选总数 \(visibleItems.count)")
    }

    private var statusFilters: some View {
        filterTrack {
            FilterPill(title: String(localized: "在用"), selected: filter == "active") { filter = "active" }
            FilterPill(title: String(localized: "已暂停"), selected: filter == "paused") { filter = "paused" }
            FilterPill(title: String(localized: "回收站"), selected: filter == "soft_deleted") { filter = "soft_deleted" }
        }
    }

    private var themeFilters: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            filterTrack {
                FilterPill(title: String(localized: "全部"), selected: theme == "all") { theme = "all" }
                ForEach(themes, id: \.self) { name in
                    FilterPill(title: name, selected: theme == name) { theme = name }
                }
            }
        }.fixedSize(horizontal: false, vertical: true)
    }

    private func filterTrack<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        HStack(spacing: 4) {
            content()
        }
        .padding(4)
        .background(runway.field, in: Capsule())
    }

    private func sectionBlock(_ group: (theme: String, items: [Knowledge]), columns: [GridItem]) -> some View {
        let selecting = selection.group == group.theme
        let titles = KnowledgeLexicon.resolvedTitles(for: group.items)
        return VStack(alignment: .leading, spacing: Runway.gap) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: Runway.space) {
                    groupTitle(group.theme, count: group.items.count); Spacer(minLength: 8)
                    groupTools(group.theme, selecting: selecting)
                }
                VStack(alignment: .leading, spacing: 8) {
                    groupTitle(group.theme, count: group.items.count)
                    groupTools(group.theme, selecting: selecting)
                }
            }
            LazyVGrid(columns: columns, alignment: .leading, spacing: Runway.gap) {
                ForEach(group.items, id: \.id) { item in
                    SummaryChip(
                        title: KnowledgeLexicon.chipTitle(resolved: titles[item.id] ?? item.title, theme: group.theme),
                        fullTitle: titles[item.id] ?? item.title,
                        selecting: selecting, selected: selection.ids.contains(item.id), lifecycle: item.lifecycle,
                        onAction: { perform($0, ids: [item.id]) }
                    ) {
                        if selecting { selection.toggle(item.id, visible: selectableIDs) }
                        else { selection.finish(); openDeck(item) }
                    }
                    .contextMenu { if !selecting { chipMenu(item) } }
                }
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    private func groupTitle(_ name: String, count: Int) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Runway.space) {
            Text(name).font(.title3.weight(.semibold)).foregroundStyle(runway.ink)
            Text("\(count)").font(.subheadline).foregroundStyle(.secondary)
        }
    }
    @ViewBuilder private func groupTools(_ name: String, selecting: Bool) -> some View {
        if selecting {
            HStack(spacing: 6) {
                SelectionCountLabel(count: selection.ids.count)
                SessionListToolbarButton(title: selection.ids == selectableIDs ? "取消全选" : "全选", symbol: selection.ids == selectableIDs ? "checkmark.square.fill" : "checkmark.square", selected: selection.ids == selectableIDs) { selection.all(selectableIDs) }
                ForEach(KnowledgeAction.available(filter)) { action in
                    SessionListToolbarButton(title: action.title, symbol: action.symbol, destructive: action.destructive) { perform(action, ids: selection.ids.intersection(selectableIDs)) }
                        .disabled(selection.ids.isEmpty)
                }
                SessionListToolbarButton(title: "完成", symbol: "checkmark") { selection.finish() }
            }.fixedSize(horizontal: true, vertical: false)
        } else {
            SessionListToolbarButton(title: "多选", symbol: "checklist", accessibilityTitle: "多选\(name)知识", secondary: true) {
                selection.begin(name); operationError = nil
            }
        }
    }
    private func perform(_ action: KnowledgeAction, ids: Set<UUID>) {
        do {
            if action == .delete { deletionImpact = try KnowledgeManagement.impact(ids, context: modelContext) }
            else {
                let original = try KnowledgeManagement.apply(action, ids: ids, context: modelContext)
                undoTrash = action == .trash ? original : [:]
            }
            operationError = nil
        } catch { operationError = error.localizedDescription }
    }

    private static func chipColumns(for width: CGFloat) -> [GridItem] {
        let spacing = Runway.gap
        let minWidth: CGFloat = 252
        let count = max(1, min(3, Int((width + spacing) / (minWidth + spacing))))
        return Array(repeating: GridItem(.flexible(), spacing: spacing, alignment: .top), count: count)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            MascotMotion(phase: .idle, ambient: true).frame(width: 150, height: 170)
            Text(emptyCopy).multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            if filter == "active" && items.isEmpty {
                RunwayPrimaryButton(title: "开始学习", action: onStartLearning)
            } else if !items.isEmpty && theme != "all" {
                Button("显示全部主题") { theme = "all" }.buttonStyle(.borderless)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var emptyCopy: String {
        if !items.isEmpty && theme != "all" { return "没有符合当前筛选的知识，请调整筛选。" }
        return switch filter {
        case "paused": String(localized: "没有已暂停的知识。")
        case "soft_deleted": String(localized: "回收站为空。")
        default: String(localized: "还没有知识点。前往 Agent 开始学习，确认后保存到知识库。")
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
        KnowledgeActionButtons(lifecycle: item.lifecycle) { perform($0, ids: [item.id]) }
    }
}

private struct SummaryChip: View {
    var title: String
    var fullTitle: String
    var selecting = false
    var selected = false
    var lifecycle = "active"
    var onAction: (KnowledgeAction) -> Void = { _ in }
    var action: () -> Void
    @State private var hovering = false
    @FocusState private var focused: Bool
    @FocusState private var menuFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Text(title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .multilineTextAlignment(.leading)
                    .lineLimit(2).truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: selecting ? (selected ? "checkmark.circle.fill" : "circle") : "chevron.right")
                    .font(.body.weight(.medium)).foregroundStyle(selected ? runway.ink : runway.copy)
                    .opacity(!selecting && (hovering || focused) ? 0 : 1).accessibilityHidden(true)
            }
            .padding(.horizontal, Runway.gap)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, minHeight: 72, maxHeight: 72, alignment: .leading)
            .background(runway.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous)
                    .strokeBorder(hovering ? runway.decorativeAccent.opacity(0.45) : runway.hairline, lineWidth: 1)
            )
            .shadow(color: runway.liftShadow.opacity(0.45), radius: 8, y: 2)
        }
        .buttonStyle(InteractionButtonStyle(selected: selected, focused: focused, padding: 0, outline: .rounded(Runway.chipRadius)))
        .help(fullTitle).accessibilityLabel(fullTitle)
        .overlay(alignment: .trailing) {
            if !selecting {
                Menu { KnowledgeActionButtons(lifecycle: lifecycle, perform: onAction) } label: {
                    Image(systemName: "ellipsis").frame(width: 28, height: 32)
                }.menuStyle(.borderlessButton).fixedSize().padding(.trailing, Runway.gap - 5)
                    .focused($menuFocused)
                    .opacity(hovering || focused || menuFocused ? 1 : 0)
                    .accessibilityLabel("知识操作：\(fullTitle)")
            }
        }
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .focusable().focusEffectDisabled().focused($focused)
        .onHover { hovering = $0 }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: hovering)
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

private struct KnowledgeDisclosureStyle: DisclosureGroupStyle {
    let hint: LocalizedStringKey
    func makeBody(configuration: Configuration) -> some View {
        Header(configuration: configuration, hint: hint)
    }
    private struct Header: View {
        let configuration: DisclosureGroupStyleConfiguration
        let hint: LocalizedStringKey
        @Environment(\.runway) private var runway
        @Environment(\.brandReduceMotion) private var reduced
        @FocusState private var focused: Bool
        var body: some View {
            VStack(alignment: .leading, spacing: 4) {
                Button(action: toggle) {
                    HStack(spacing: 8) {
                        configuration.label
                        Spacer(minLength: 8)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 10, weight: .semibold))
                            .rotationEffect(.degrees(configuration.isExpanded ? 90 : 0))
                            .accessibilityHidden(true)
                    }
                    .frame(maxWidth: .infinity, minHeight: 24, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(InteractionButtonStyle(selected: configuration.isExpanded, focused: focused, padding: 8))
                .background(runway.ink.opacity(0.04), in: RoundedRectangle(cornerRadius: 9))
                .focusable().focusEffectDisabled().focused($focused)
                .onKeyPress(.space) { toggle(); return .handled }
                .onKeyPress(.return) { toggle(); return .handled }
                .accessibilityValue(Text(configuration.isExpanded ? "已展开" : "已收起"))
                .accessibilityHint(Text(hint))
                if configuration.isExpanded { configuration.content }
            }
        }
        private func toggle() {
            withAnimation(reduced ? nil : .easeOut(duration: 0.16)) { configuration.isExpanded.toggle() }
        }
    }
}

private struct KnowledgeDeckOverlay: View {
    var items: [Knowledge]
    var titles: [UUID: String]
    @Binding var index: Int
    var coordinator: ReviewCoordinator
    var onClose: () -> Void
    var onAction: (KnowledgeAction, UUID) -> Void

    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway

    var body: some View {
        ZStack {
            runway.scrim
                .ignoresSafeArea()
                .onTapGesture(perform: onClose)

            DepthCarousel(items: deckItems, index: $index, title: {
                titles[$0.id] ?? $0.item.title
            }) { wrapper in
                KnowledgeDepthCard(
                    item: wrapper.item,
                    siblings: items,
                    resolvedTitle: titles[wrapper.id] ?? wrapper.item.title,
                    onClose: onClose,
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
                    onAction: { onAction($0, wrapper.item.id) }
                )
            }

        }
    }

    private var deckItems: [DeckItem] {
        items.map { DeckItem(id: $0.id, item: $0) }
    }


}

private struct DeckItem: Identifiable {
    var id: UUID
    var item: Knowledge
}

private struct KnowledgeDepthCard: View {
    var item: Knowledge
    var siblings: [Knowledge]
    var resolvedTitle: String
    var onClose: () -> Void
    var onPreview: () -> Void
    var onAction: (KnowledgeAction) -> Void
    @Environment(\.modelContext) private var deletionContext
    @Environment(\.runway) private var runway
    @State private var sourceExpanded = false
    @State private var misconceptionsExpanded = false

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
        GeometryReader { _ in
            VStack(alignment: .leading, spacing: 0) {
                titleBlock

                ScrollView(.vertical, showsIndicators: true) {
                    readingContent
                        .padding(.horizontal, Runway.section)
                        .padding(.bottom, Runway.section)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                }
                .scrollIndicators(.visible)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                footer
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(runway.card)
        }
    }

    private var titleBlock: some View {
        HStack(alignment: .top, spacing: Runway.gap) {
            VStack(alignment: .leading, spacing: Runway.space) {
                Text(KnowledgeLexicon.displayTheme(for: item))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(resolvedTitle)
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(runway.ink)
                    .lineSpacing(2)
                    .lineLimit(2)
                    .help(resolvedTitle)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .knowledgeDeckDragSurface()
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.body.weight(.medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(InteractionButtonStyle(padding: 0, outline: .capsule))
            .help("关闭知识详情").accessibilityLabel("关闭知识详情")
            .keyboardShortcut(.cancelAction)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Runway.section)
        .padding(.top, Runway.section)
        .padding(.bottom, Runway.section)
    }

    private var readingContent: some View {
        VStack(alignment: .leading, spacing: 28) {
            questionBlock
            detailBlock
            memoryBlock
            sourceBlock
        }
    }

    private var footer: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: Runway.space) {
                if let previewUnavailableReason {
                    Label(previewUnavailableReason, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(Color.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(alignment: .center, spacing: Runway.space) {
                    Text(item.lifecycle == "soft_deleted" ? "已移到回收站" : "下次 \(item.dueAt.formatted(date: .abbreviated, time: .omitted))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Menu {
                        KnowledgeActionButtons(lifecycle: item.lifecycle, perform: onAction)
                    } label: {
                        Image(systemName: "ellipsis")
                            .font(.body.weight(.medium))
                            .foregroundStyle(.secondary)
                            .frame(width: 28, height: 28)
                    }
                    .menuStyle(.borderlessButton)
                    if item.lifecycle != "soft_deleted" {
                        RunwayPrimaryButton(
                            title: String(localized: "试一题"),
                            enabled: previewUnavailableReason == nil,
                            action: onPreview
                        )
                    }
                }
            }
            .padding(.horizontal, Runway.section)
            .padding(.top, 12)
            .padding(.bottom, 32)
        }
    }

    private var detailBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "详解"))
                .font(.caption)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(pieces.enumerated()), id: \.offset) { _, piece in
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
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field.opacity(0.70), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var memoryBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
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
            ForEach(Array(cover.enumerated()), id: \.offset) { _, line in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text("•").foregroundStyle(runway.copy).frame(width: 8).accessibilityHidden(true)
                    memoryRow(line)
                }
            }
            if !mixups.isEmpty {
                DisclosureGroup(isExpanded: $misconceptionsExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(Array(mixups.enumerated()), id: \.offset) { index, line in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text("\(index + 1).").monospacedDigit().foregroundStyle(.secondary).frame(minWidth: 18, alignment: .leading)
                                Text(line)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                                .font(.callout)
                                .foregroundStyle(runway.copy)
                                .lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, Runway.space)
                } label: {
                    HStack(spacing: 6) {
                        Text(String(localized: "常见误区"))
                        Text("\(mixups.count)").monospacedDigit()
                    }
                    .font(.caption)
                    .foregroundStyle(runway.copy)
                }
                .disclosureGroupStyle(KnowledgeDisclosureStyle(hint: "展开或收起常见误区"))
                .padding(.top, Runway.space)
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field.opacity(0.70), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var sourceBlock: some View {
        DisclosureGroup(isExpanded: $sourceExpanded) {
            VStack(alignment: .leading, spacing: Runway.gap) {
                HStack {
                    if let locator = sourceLocator {
                        Link(String(localized: "打开来源"), destination: locator)
                            .font(.caption)
                    } else {
                        Text(String(localized: "来自你提交的原文"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
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
            .padding(.top, Runway.space)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: Runway.space) {
                Text(String(localized: "来源证据"))
                if let origin = item.originSessionID, (try? SessionDeletion.contains(origin, context: deletionContext)) == true {
                    Text("原会话已删除").foregroundStyle(.secondary)
                }
            }
            .font(.caption)
            .foregroundStyle(runway.copy)
        }
        .disclosureGroupStyle(KnowledgeDisclosureStyle(hint: "展开或收起来源证据"))
        .tint(runway.ink)
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
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(width: 18, height: 20)
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

    @ViewBuilder
    private func memoryRow(_ text: String) -> some View {
        // Keep the stored wording intact. Only short, explicit labels get their
        // own column; unstructured prose remains a normal wrapping paragraph.
        if let colon = text.firstIndex(of: "："),
           text[..<colon].count <= 16, !text[..<colon].contains("\n") {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: Runway.gap) {
                    Text(String(text[...colon]))
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .frame(width: 126, alignment: .leading)
                    Text(String(text[text.index(after: colon)...]))
                        .font(.callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .frame(minWidth: 180, maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(String(text[...colon]))
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                    Text(String(text[text.index(after: colon)...]))
                        .font(.callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        } else {
            Text(text)
                .font(.callout)
                .foregroundStyle(runway.copy)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
