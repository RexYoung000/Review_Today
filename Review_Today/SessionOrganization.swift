import SwiftData
import SwiftUI

@Model
final class SessionFolder {
    @Attribute(.unique) var id: UUID
    var name: String
    var createdAt: Date
    init(name: String) { id = UUID(); self.name = name; createdAt = .now }
}

@MainActor
enum SessionOrganization {
    enum Failure: LocalizedError {
        case emptyName, duplicateName, missingTarget
        var errorDescription: String? {
            switch self {
            case .emptyName: "请输入文件夹名称。"
            case .duplicateName: "已有同名文件夹，请换一个名称。"
            case .missingTarget: "会话或文件夹已变化，请重新选择。"
            }
        }
    }
    static func showsDraft(isCurrent: Bool, text: String) -> Bool {
        isCurrent || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    static func matches(_ session: AgentSession, query: String, archived: Bool = false) -> Bool {
        guard session.status == (archived ? "archived" : "active") else { return false }
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty || session.title.localizedCaseInsensitiveContains(query)
            || session.displayTopicTags.contains { $0.localizedCaseInsensitiveContains(query) }
    }
    static func named(_ raw: String, excluding: UUID? = nil, context: ModelContext) throws -> String {
        let name = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw Failure.emptyName }
        guard try !context.fetch(FetchDescriptor<SessionFolder>()).contains(where: {
            $0.id != excluding && $0.name.compare(name, options: [.caseInsensitive, .diacriticInsensitive]) == .orderedSame
        }) else { throw Failure.duplicateName }
        return name
    }
    @discardableResult
    static func create(_ name: String, moving session: AgentSession? = nil, context: ModelContext, save: (() throws -> Void)? = nil) throws -> SessionFolder {
        let folder = SessionFolder(name: try named(name, context: context))
        if let session, session.isDeleted { throw Failure.missingTarget }
        let oldFolder = session?.folderID
        do {
            context.insert(folder); session?.folderID = folder.id
            if let save { try save() } else { try context.save() }
            return folder
        } catch { context.processPendingChanges(); context.rollback(); session?.folderID = oldFolder; throw error }
    }
    static func move(_ session: AgentSession, to folderID: UUID?, context: ModelContext, save: (() throws -> Void)? = nil) throws {
        guard !session.isDeleted, session.status != "deleted" else { throw Failure.missingTarget }
        if let folderID, try !context.fetch(FetchDescriptor<SessionFolder>()).contains(where: { $0.id == folderID }) { throw Failure.missingTarget }
        let original = session.folderID
        do {
            session.folderID = folderID
            if let save { try save() } else { try context.save() }
        } catch { context.processPendingChanges(); context.rollback(); session.folderID = original; throw error }
    }
    static func rename(_ folder: SessionFolder, to name: String, context: ModelContext) throws {
        let name = try named(name, excluding: folder.id, context: context)
        let original = folder.name
        do { folder.name = name; try context.save() } catch { context.processPendingChanges(); context.rollback(); folder.name = original; throw error }
    }
    static func remove(_ folder: SessionFolder, context: ModelContext, save: (() throws -> Void)? = nil) throws {
        let members = try context.fetch(FetchDescriptor<AgentSession>()).filter { $0.folderID == folder.id }
        let id = folder.id
        do {
            for session in members { session.folderID = nil }
            context.delete(folder)
            if let save { try save() } else { try context.save() }
        } catch { context.processPendingChanges(); context.rollback(); for session in members { session.folderID = id }; throw error }
    }
}

extension Notification.Name {
    static let sessionSearchClosed = Notification.Name("ReviewToday.sessionSearchClosed")
}

/// Reuse the existing conversation window; WindowGroup.openWindow otherwise
/// creates another window on every archive-row click.
@MainActor
enum ConversationWindowRouter {
    static weak var target: ConversationWindowTarget.TargetView?
    static var pendingID: UUID?
    static func show(_ id: UUID) -> Bool {
        guard let target, let window = target.window, window.isVisible || window.isMiniaturized else {
            pendingID = id
            return false
        }
        if window.isMiniaturized { window.deminiaturize(nil) }
        target.onOpen?(id)
        window.makeKeyAndOrderFront(nil)
        return true
    }
}

struct ConversationWindowTarget: NSViewRepresentable {
    let onOpen: (UUID) -> Void
    func makeNSView(context: Context) -> TargetView { let view = TargetView(); view.onOpen = onOpen; return view }
    func updateNSView(_ view: TargetView, context: Context) { view.onOpen = onOpen }
    final class TargetView: NSView {
        var onOpen: ((UUID) -> Void)?
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard window != nil else { return }
            ConversationWindowRouter.target = self
            if let id = ConversationWindowRouter.pendingID {
                ConversationWindowRouter.pendingID = nil
                DispatchQueue.main.async { [weak self] in self?.onOpen?(id) }
            }
        }
    }
}

struct SessionFolderPicker: View {
    let session: AgentSession
    var onMoved: (UUID?) -> Void = { _ in }
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @Query(sort: \SessionFolder.createdAt) private var folders: [SessionFolder]
    @State private var newName = ""
    @State private var creating = false
    @State private var error: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("移动会话").font(.headline)
            Text(session.title).foregroundStyle(.secondary).lineLimit(2)
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    destination("未分类", id: nil)
                    ForEach(folders) { folder in destination(folder.name, id: folder.id) }
                }
            }.frame(maxHeight: 260)
            if creating {
                TextField("文件夹名称", text: $newName).textFieldStyle(BrandMaterialTextFieldStyle())
                    .onSubmit(create)
                Button("创建并移动", action: create).disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } else { Button("新建文件夹…", systemImage: "folder.badge.plus") { creating = true } }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            HStack { Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction) }
        }.padding(24).frame(width: 380)
    }
    private func destination(_ title: String, id: UUID?) -> some View {
        Button {
            do { try SessionOrganization.move(session, to: id, context: context); onMoved(id); dismiss() }
            catch { self.error = error.localizedDescription }
        } label: {
            HStack { Label(title, systemImage: "folder"); Spacer(); if session.folderID == id { Image(systemName: "checkmark") } }
                .frame(maxWidth: .infinity).padding(8).contentShape(Rectangle())
        }.buttonStyle(InteractionButtonStyle(padding: 0))
    }
    private func create() {
        do { let folder = try SessionOrganization.create(newName, moving: session, context: context); onMoved(folder.id); dismiss() }
        catch { self.error = error.localizedDescription }
    }
}

struct SessionSearchOverlay: View {
    let onOpen: (AgentSession) -> Void
    let onClose: () -> Void
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query private var folders: [SessionFolder]
    @Environment(\.runway) private var runway
    @State private var query = ""
    @State private var highlighted: UUID?
    @FocusState private var focused: Bool
    private var results: [AgentSession] { sessions.filter { SessionOrganization.matches($0, query: query) } }
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                runway.scrim.ignoresSafeArea().onTapGesture(perform: onClose)
                VStack(spacing: 0) {
                    HStack(spacing: 12) {
                        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                        TextField("搜索未归档会话…", text: $query).textFieldStyle(.plain).font(.title3)
                            .focused($focused).onSubmit(openHighlighted)
                        ChromeIconButton(title: "关闭搜索", symbol: "xmark", action: onClose)
                    }.padding(22)
                    Divider()
                    HStack { Text(query.isEmpty ? "最近会话" : "找到 \(results.count) 个会话"); Spacer() }
                        .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 22).padding(.top, 12)
                    ScrollViewReader { reader in
                        ScrollView {
                            LazyVStack(spacing: 4) {
                                ForEach(results) { session in
                                    Button { onOpen(session) } label: {
                                        VStack(alignment: .leading, spacing: 5) {
                                            Text(session.title).font(.body).lineLimit(2).foregroundStyle(runway.ink)
                                            Text(folders.first(where: { $0.id == session.folderID })?.name ?? "未分类")
                                                .font(.caption).foregroundStyle(.secondary)
                                        }.frame(maxWidth: .infinity, alignment: .leading).padding(12).contentShape(Rectangle())
                                    }.buttonStyle(InteractionButtonStyle(selected: highlighted == session.id, padding: 0))
                                        .id(session.id)
                                }
                                if results.isEmpty { Text("没有匹配的会话").foregroundStyle(.secondary).padding(32) }
                            }.padding(12)
                        }
                        .onChange(of: highlighted) { _, id in if let id { reader.scrollTo(id) } }
                    }
                }
                .frame(width: max(1, min(760, geometry.size.width - 64)), height: max(180, min(560, geometry.size.height - 96)))
                .background(runway.card, in: RoundedRectangle(cornerRadius: 22))
                .clipShape(RoundedRectangle(cornerRadius: 22))
                .shadow(color: runway.liftShadow, radius: 24, y: 12)
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .onAppear { highlighted = results.first?.id }
        .task { await Task.yield(); focused = true }
        .onChange(of: query) { _, _ in highlighted = results.first?.id }
        .onChange(of: results.map(\.id)) { _, ids in if highlighted.map(ids.contains) != true { highlighted = ids.first } }
        .onKeyPress(.downArrow) { step(1); return .handled }
        .onKeyPress(.upArrow) { step(-1); return .handled }
        .onKeyPress(.escape) { onClose(); return .handled }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("搜索未归档会话")
        .accessibilityAddTraits(.isModal)
    }
    private func step(_ direction: Int) {
        guard !results.isEmpty else { return }
        let current = results.firstIndex { $0.id == highlighted } ?? 0
        highlighted = results[min(max(current + direction, 0), results.count - 1)].id
    }
    private func openHighlighted() { if let item = results.first(where: { $0.id == highlighted }) { onOpen(item) } }
}
