import Foundation

@main
struct SessionListSelectionTests {
    private final class Session {
        let id = UUID()
        let title: String
        var status: String
        var tags: [String] = []
        init(title: String, status: String) { self.title = title; self.status = status }
    }

    @MainActor static func main() throws {
        let alpha = Session(title: "Alpha 学习", status: "active")
        let beta = Session(title: "Beta 学习", status: "active")
        let gamma = Session(title: "Gamma 学习", status: "active")
        let archivedAlpha = Session(title: "Alpha 归档", status: "archived")
        let archivedBeta = Session(title: "Beta 归档", status: "archived")
        beta.tags = ["检索"]
        let sessions = [alpha, beta, gamma, archivedAlpha, archivedBeta]
        var state = SessionListSelection()
        func visible(_ selection: SessionListSelection) -> [UUID] {
            sessions.filter { selection.matches(status: $0.status, title: $0.title, tags: $0.tags) }.map(\.id)
        }

        precondition(visible(state) == [alpha.id, beta.id, gamma.id])
        state.toggleSearch()
        state.setSearchText("  alpha  ")
        precondition(visible(state) == [alpha.id], "search must be case insensitive, trimmed and scoped")
        state.beginSelection()
        state.toggleAll(visibleIDs: visible(state))
        precondition(state.visibleSelectedIDs(in: visible(state)) == [alpha.id])
        state.setSearchText("检索")
        precondition(state.multiSelect && state.selectedIDs.isEmpty && visible(state) == [beta.id], "search changes clear selection while retaining selection mode")
        state.toggle(beta.id, visibleIDs: visible(state), extendingRange: false)
        state.toggleSearch()
        precondition(!state.searchVisible && state.searchText.isEmpty && state.multiSelect && state.selectedIDs.isEmpty)

        state.toggle(alpha.id, visibleIDs: visible(state), extendingRange: false)
        state.toggle(gamma.id, visibleIDs: visible(state), extendingRange: true)
        precondition(state.selectedIDs == [alpha.id, beta.id, gamma.id], "Shift selects the displayed ordered range")
        state.toggle(beta.id, visibleIDs: visible(state), extendingRange: false)
        precondition(state.selectedIDs == [alpha.id, gamma.id], "Command-style toggle removes only its row")
        precondition(state.visibleSelectedIDs(in: [gamma.id]) == [gamma.id], "action scope is safe even before the UI reconciles a data update")
        state.reconcile(visibleIDs: [gamma.id])
        precondition(state.selectedIDs == [gamma.id])
        state.toggleAll(visibleIDs: [beta.id])
        precondition(state.selectedIDs == [beta.id] && state.allVisibleSelected(in: [beta.id]), "all-select compares identities, not equal counts")
        state.toggleAll(visibleIDs: [beta.id])
        precondition(state.selectedIDs.isEmpty && !state.allVisibleSelected(in: []))

        state.toggleSearch(); state.setSearchText("Alpha")
        state.toggle(alpha.id, visibleIDs: visible(state), extendingRange: false)
        state.reset(archived: true)
        precondition(state.showArchived && !state.searchVisible && state.searchText.isEmpty && !state.multiSelect && state.selectedIDs.isEmpty)
        precondition(state.scopeTitle == "已归档" && state.searchPrompt == "搜索已归档会话")
        state.toggleSearch(); state.setSearchText("Alpha")
        state.beginSelection(); state.toggleAll(visibleIDs: visible(state))
        let deleteTargets = state.visibleSelectedIDs(in: visible(state))
        precondition(deleteTargets == [archivedAlpha.id], "delete action receives only the filtered selection shown in the toolbar")
        state.setSearchText("Beta")
        precondition(state.visibleSelectedIDs(in: visible(state)).isEmpty, "search must never retain hidden deletion targets")
        state.toggleAll(visibleIDs: visible(state))
        archivedBeta.status = "active"
        precondition(state.visibleSelectedIDs(in: visible(state)).isEmpty, "an externally restored row is immediately excluded from every action")
        state.reconcile(visibleIDs: visible(state))
        precondition(state.selectedIDs.isEmpty && state.multiSelect)
        archivedBeta.status = "archived"

        state.setSearchText("")
        state.toggleAll(visibleIDs: visible(state))
        state.finishBatch(failedIDs: [archivedBeta.id], visibleIDs: visible(state))
        precondition(state.multiSelect && state.selectedIDs == [archivedBeta.id], "failed items remain selected for retry")
        state.finishBatch(failedIDs: [], visibleIDs: visible(state))
        precondition(!state.multiSelect && state.selectedIDs.isEmpty)
        state.toggleSearch(); state.setSearchText("Alpha"); state.beginSelection()
        state.reset(archived: false)
        precondition(!state.showArchived && !state.searchVisible && state.searchText.isEmpty && !state.multiSelect && state.selectedIDs.isEmpty)

        // A real empty scope differs from a populated scope with no search hits.
        let lastSession = Session(title: "Last active", status: "active")
        var controls = SessionListSelection()
        func actionsVisible() -> Bool {
            controls.showsListActions(hasSessionsInScope: controls.includes(status: lastSession.status))
        }
        precondition(actionsVisible())
        controls.toggleSearch(); controls.setSearchText("no matching title")
        precondition(!controls.matches(status: lastSession.status, title: lastSession.title, tags: []))
        precondition(actionsVisible(), "zero search hits must retain search and clear controls")
        lastSession.status = "archived"
        precondition(actionsVisible(), "an open search must remain dismissible after the last row leaves the scope")
        controls.toggleSearch()
        precondition(!actionsVisible(), "an archived row must not keep tools visible in the empty active scope")
        controls.beginSelection()
        precondition(actionsVisible(), "an in-progress selection must retain Done even when its scope becomes empty")
        controls.endSelection()
        precondition(!actionsVisible())
        controls.reset(archived: true)
        precondition(actionsVisible() && controls.scopeTitle == "已归档")
        lastSession.status = "active"
        precondition(!actionsVisible() && controls.showArchived, "an empty archive keeps its scope label without list actions")
        print("PASS: scoped title/tag search, search/reset boundaries, range and identity selection, current visible action targets, live scope changes, partial retry, empty-scope tools and no-results recovery")
    }
}
