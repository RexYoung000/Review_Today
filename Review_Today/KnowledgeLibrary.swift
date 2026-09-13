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
