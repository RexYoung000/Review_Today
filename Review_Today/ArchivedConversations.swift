import SwiftData
import SwiftUI

struct ArchivedConversations: View {
    @Environment(\.modelContext) private var context
    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query private var folders: [SessionFolder]
    @State private var controls: SessionListSelection = { var state = SessionListSelection(); state.reset(archived: true); return state }()
    @State private var impact: SessionDeletionImpact?
    @State private var moving: AgentSession?
    @State private var error: String?
    private var visible: [AgentSession] { sessions.filter { controls.matches(status: $0.status, title: $0.title, tags: $0.displayTopicTags) } }
    private var ids: [UUID] { visible.map(\.id) }
    private var selected: Set<UUID> { controls.visibleSelectedIDs(in: ids) }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("已归档聊天").font(.title2.weight(.semibold)); Spacer()
                if !controls.multiSelect && sessions.contains(where: { $0.status == "archived" }) {
                    SessionListToolbarButton(title: "多选", secondary: true) { controls.beginSelection() }
                }
            }
            TextField("搜索已归档会话…", text: Binding(get: { controls.searchText }, set: { controls.setSearchText($0) }))
                .textFieldStyle(BrandMaterialTextFieldStyle())
            if controls.multiSelect {
                HStack(spacing: 8) {
                    Text("已选 \(selected.count)").font(.caption).monospacedDigit()
                    SessionListToolbarButton(title: controls.allVisibleSelected(in: ids) ? "取消全选" : "全选") { controls.toggleAll(visibleIDs: ids) }
                    Spacer()
                    SessionListToolbarButton(title: "恢复") { restore(selected) }.disabled(selected.isEmpty)
                    SessionListToolbarButton(title: "永久删除") { prepare(selected) }.foregroundStyle(.red).disabled(selected.isEmpty)
                    SessionListToolbarButton(title: "完成") { controls.endSelection() }
                }
            }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            ScrollView {
                LazyVStack(spacing: 8) {
                    ForEach(visible) { session in
                        HStack(spacing: 12) {
                            Button {
                                if controls.multiSelect { controls.toggle(session.id, visibleIDs: ids, extendingRange: NSEvent.modifierFlags.contains(.shift)) }
                                else {
                                    if !ConversationWindowRouter.show(session.id) { openWindow(id: "main") }
                                }
                            } label: {
                                HStack(spacing: 10) {
                                    if controls.multiSelect { Image(systemName: selected.contains(session.id) ? "checkmark.circle.fill" : "circle") }
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text(session.title).lineLimit(2).foregroundStyle(runway.ink)
                                        Text((folders.first(where: { $0.id == session.folderID })?.name ?? "未分类") + " · " + (session.archivedAt ?? session.updatedAt).formatted(date: .abbreviated, time: .shortened))
                                            .font(.caption).foregroundStyle(.secondary)
                                    }.frame(maxWidth: .infinity, alignment: .leading)
                                }.padding(10).contentShape(Rectangle())
                            }.buttonStyle(InteractionButtonStyle(selected: selected.contains(session.id), padding: 0))
                            if !controls.multiSelect {
                                ChromeIconButton(title: "永久删除：\(session.title)", symbol: "trash") { prepare([session.id]) }
                                Button("恢复") { restore([session.id]) }.buttonStyle(.borderless)
                            }
                        }.padding(6).background(runway.card, in: RoundedRectangle(cornerRadius: 12))
                            .contextMenu { Button("移动到…") { moving = session } }
                    }
                    if visible.isEmpty {
                        Text(controls.searchText.isEmpty ? "没有已归档的聊天" : "没有匹配的会话")
                            .foregroundStyle(.secondary).padding(40)
                    }
                }
            }
        }.padding(24).frame(minWidth: 560, minHeight: 420)
            .navigationTitle("已归档聊天")
            .onChange(of: ids) { _, ids in controls.reconcile(visibleIDs: ids) }
            .sheet(item: $impact) { value in
                SessionDeletionSheet(impact: value) { deleted in controls.reconcile(visibleIDs: ids.filter { !deleted.contains($0) }) }
            }
            .sheet(item: $moving) { session in SessionFolderPicker(session: session) }
            .onKeyPress(.escape) { guard controls.multiSelect else { return .ignored }; controls.endSelection(); return .handled }
    }
    private func prepare(_ targets: Set<UUID>) {
        do { impact = try SessionDeletion.impact(targets.intersection(ids), context: context); error = nil }
        catch { self.error = error.localizedDescription }
    }
    private func restore(_ targets: Set<UUID>) {
        var failed = Set<UUID>()
        for session in visible where targets.contains(session.id) {
            if !LearningSessionActions.restore(session, context: context) { failed.insert(session.id) }
        }
        if controls.multiSelect { controls.finishBatch(failedIDs: failed, visibleIDs: ids) }
        error = failed.isEmpty ? nil : "\(failed.count) 个会话恢复失败，请重试。"
    }
}
