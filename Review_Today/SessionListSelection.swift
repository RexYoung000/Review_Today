import Foundation

/// Local list controls; opening a conversation and editing its draft remain independent.
struct SessionListSelection {
    private(set) var showArchived = false
    private(set) var searchText = ""
    private(set) var searchVisible = false
    private(set) var multiSelect = false
    private(set) var selectedIDs = Set<UUID>()
    private var rangeAnchor: UUID?

    var scopeTitle: String { showArchived ? "已归档" : "进行中" }
    var searchPrompt: String { showArchived ? "搜索已归档会话" : "搜索进行中会话" }

    func matches(status: String, title: String, tags: [String]) -> Bool {
        guard status == (showArchived ? "archived" : "active") else { return false }
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty || title.localizedCaseInsensitiveContains(query)
            || tags.contains { $0.localizedCaseInsensitiveContains(query) }
    }

    func visibleSelectedIDs(in visibleIDs: [UUID]) -> Set<UUID> {
        selectedIDs.intersection(visibleIDs)
    }

    func allVisibleSelected(in visibleIDs: [UUID]) -> Bool {
        !visibleIDs.isEmpty && visibleSelectedIDs(in: visibleIDs) == Set(visibleIDs)
    }

    mutating func reset(archived: Bool) {
        showArchived = archived
        searchText = ""
        searchVisible = false
        endSelection()
    }

    mutating func toggleSearch() {
        searchVisible.toggle()
        if !searchVisible { setSearchText("") }
    }

    mutating func setSearchText(_ text: String) {
        guard searchText != text else { return }
        searchText = text
        clearSelection()
    }

    mutating func beginSelection() {
        multiSelect = true
        clearSelection()
    }

    mutating func endSelection() {
        multiSelect = false
        clearSelection()
    }

    mutating func toggle(_ id: UUID, visibleIDs: [UUID], extendingRange: Bool) {
        guard visibleIDs.contains(id) else { return }
        reconcile(visibleIDs: visibleIDs)
        multiSelect = true
        if extendingRange, let anchor = rangeAnchor,
           let first = visibleIDs.firstIndex(of: anchor), let last = visibleIDs.firstIndex(of: id) {
            selectedIDs.formUnion(visibleIDs[min(first, last)...max(first, last)])
        } else if !selectedIDs.insert(id).inserted {
            selectedIDs.remove(id)
        }
        rangeAnchor = id
    }

    mutating func toggleAll(visibleIDs: [UUID]) {
        multiSelect = true
        selectedIDs = allVisibleSelected(in: visibleIDs) ? [] : Set(visibleIDs)
        rangeAnchor = nil
    }

    mutating func reconcile(visibleIDs: [UUID]) {
        selectedIDs.formIntersection(visibleIDs)
        if let rangeAnchor, !visibleIDs.contains(rangeAnchor) { self.rangeAnchor = nil }
    }

    mutating func finishBatch(failedIDs: Set<UUID>, visibleIDs: [UUID]) {
        selectedIDs = failedIDs.intersection(visibleIDs)
        rangeAnchor = nil
        multiSelect = !selectedIDs.isEmpty
    }

    private mutating func clearSelection() {
        selectedIDs.removeAll()
        rangeAnchor = nil
    }
}
