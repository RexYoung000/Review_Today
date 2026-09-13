import SwiftData
import SwiftUI
import UserNotifications

struct AppSidebar: View {
    @Binding var selection: SidebarItem?
    @Binding var selectedSessionID: UUID?
    @Binding var scrollAnchor: UUID?
    var onCollapse: () -> Void
    var onStartLearning: () -> Void
    var onSearch: () -> Void
    var inboxCount: Int
    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduceMotion
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \SessionFolder.createdAt) private var folders: [SessionFolder]
    @State private var sessionHoverScrollOffset: CGFloat = 0
    @State private var sessionHoverScrolling = false
    @State private var hoveredSessionID: UUID?
    @State private var openMenuSessionID: UUID?
    @State private var focusedMenuSessionID: UUID?
    @FocusState private var focusedSessionID: UUID?
    @FocusState private var searchFocused: Bool
    @State private var editingSessionID: UUID?
    @State private var movingSession: AgentSession?
    @State private var renamingFolder: SessionFolder?
    @State private var folderName = ""
    @State private var undoSessionID: UUID?
    @State private var deletionImpact: SessionDeletionImpact?
    @State private var batchError: String?
    @AppStorage("reviewToday.collapsedSessionFolders") private var collapsedRaw = ""
    private var activeSessions: [AgentSession] { sessions.filter { $0.status == "active" } }
    private var collapsed: Set<String> { Set(collapsedRaw.split(separator: ",").map(String.init)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SidebarWindowControls().frame(height: 32).padding(.horizontal, 18).padding(.top, 8)
            brand
            SidebarPrimaryNavigation(selection: $selection, selectedSessionID: $selectedSessionID, inboxCount: inboxCount)
                .padding(.horizontal, 10)
            Divider().padding(.vertical, 12)
            sessionNavigation
            if let batchError { Text(batchError).font(.caption).foregroundStyle(.red).padding(10) }
            if let undoSessionID, let session = sessions.first(where: { $0.id == undoSessionID && $0.status == "archived" }) {
                HStack {
                    Text("已归档").font(.caption); Spacer()
                    Button("撤销") {
                        restore(session)
                        if session.status == "active" { self.undoSessionID = nil }
                    }.buttonStyle(.borderless)
                }.padding(10)
            }
            HStack {
                SettingsLink {
                    HStack(spacing: 8) { Image(systemName: "gearshape").frame(width: 27); Text("设置") }
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
                        .contentShape(Rectangle()).foregroundStyle(Color.secondary)
                }.buttonStyle(InteractionButtonStyle(padding: 0))
                AnimatedThemeToggler()
            }.padding(.horizontal, 16).padding(.bottom, 16)
        }
        .background(runway.field.opacity(0.45))
        .sheet(item: $movingSession) { session in
            SessionFolderPicker(session: session) { folder in
                if let folder { setExpanded(folder, true) }
                scrollAnchor = session.id
            }
        }
        .sheet(isPresented: Binding(get: { editingSessionID != nil }, set: { if !$0 { editingSessionID = nil } })) {
            if let session = sessions.first(where: { $0.id == editingSessionID }) { SessionTagEditor(session: session) }
        }
        .sheet(item: $deletionImpact) { impact in
            SessionDeletionSheet(impact: impact) { ids in if selectedSessionID.map(ids.contains) == true { selectedSessionID = nil } }
        }
        .alert("重命名文件夹", isPresented: Binding(get: { renamingFolder != nil }, set: { if !$0 { renamingFolder = nil } })) {
            TextField("文件夹名称", text: $folderName)
            Button("取消", role: .cancel) { renamingFolder = nil }
            Button("保存") {
                if let folder = renamingFolder {
                    do { try SessionOrganization.rename(folder, to: folderName, context: modelContext) }
                    catch { batchError = error.localizedDescription }
                }
                renamingFolder = nil
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .sessionSearchClosed)) { _ in
            Task { @MainActor in await Task.yield(); searchFocused = true }
        }
        .onChange(of: selectedSessionID) { _, id in
            if let folder = sessions.first(where: { $0.id == id })?.folderID { setExpanded(folder, true) }
            scrollAnchor = id
        }
    }

    private var sessionNavigation: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 0) {
                Text("会话").font(.subheadline.weight(.medium)).padding(4)
                Spacer(minLength: 0)
                if !activeSessions.isEmpty {
                    Button(action: onSearch) { Image(systemName: "magnifyingglass").font(.system(size: 14)).frame(width: 28, height: 28) }
                        .buttonStyle(InteractionButtonStyle(focused: searchFocused, padding: 2))
                        .focusable().focusEffectDisabled().focused($searchFocused).help("搜索会话").accessibilityLabel("搜索会话")
                }
                ChromeIconButton(title: "新建会话", symbol: "plus", action: createSession)
            }.padding(.horizontal, 10)
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(activeSessions.filter { session in !folders.contains(where: { $0.id == session.folderID }) }) { session in sessionRow(session).fluidHoverTarget(session.id.uuidString, group: "unfiled") }
                    ForEach(folders) { folder in
                        folderHeader(folder)
                        if !collapsed.contains(folder.id.uuidString) {
                            ForEach(activeSessions.filter { $0.folderID == folder.id }) { session in sessionRow(session).fluidHoverTarget(session.id.uuidString, group: folder.id.uuidString).padding(.leading, 12) }
                        }
                    }
                }.scrollTargetLayout()
                    .fluidHoverSurface(reset: sessionHoverScrollOffset,
                        blocked: sessionHoverScrolling || openMenuSessionID != nil)
                    .padding(.horizontal, 8)
            }
            .onScrollGeometryChange(for: CGFloat.self) { $0.contentOffset.y } action: { _, value in
                sessionHoverScrollOffset = value; hoveredSessionID = nil
            }
            .onScrollPhaseChange { _, phase in sessionHoverScrolling = phase != .idle }
            .scrollPosition(id: $scrollAnchor, anchor: .top)
            .overlay {
                if activeSessions.isEmpty && folders.isEmpty { SessionWelcome(action: createSession) }
            }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: activeSessions.map(\.id))
        }.frame(maxHeight: .infinity)
    }

    private func folderHeader(_ folder: SessionFolder) -> some View {
        HStack(spacing: 4) {
            Button { setExpanded(folder.id, collapsed.contains(folder.id.uuidString)) } label: {
                HStack(spacing: 7) {
                    Image(systemName: collapsed.contains(folder.id.uuidString) ? "chevron.right" : "chevron.down").font(.caption2)
                    Image(systemName: "folder")
                    Text(folder.name).lineLimit(1)
                    Text("\(activeSessions.filter { $0.folderID == folder.id }.count)").foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                }.font(.callout).padding(.vertical, 8).contentShape(Rectangle())
            }.buttonStyle(InteractionButtonStyle(padding: 3)).help(folder.name)
            Menu {
                Button("重命名") { folderName = folder.name; renamingFolder = folder }
                Button("删除文件夹") {
                    do { try SessionOrganization.remove(folder, context: modelContext) }
                    catch { batchError = error.localizedDescription }
                }.help("会话保留并移回未分类")
            } label: { Image(systemName: "ellipsis").frame(width: 24, height: 26) }
                .menuStyle(.borderlessButton).fixedSize().accessibilityLabel("文件夹操作：\(folder.name)")
        }.padding(.top, 6)
    }
    private func setExpanded(_ id: UUID, _ expanded: Bool) {
        var values = collapsed
        if expanded { values.remove(id.uuidString) } else { values.insert(id.uuidString) }
        collapsedRaw = values.sorted().joined(separator: ",")
    }
    private func createSession() { batchError = nil; onStartLearning() }
    private func archive(_ session: AgentSession) {
        if LearningSessionActions.archive(session, context: modelContext) { undoSessionID = session.id }
        else { batchError = "归档未保存，请重试。" }
    }
    private func restore(_ session: AgentSession) {
        if LearningSessionActions.restore(session, context: modelContext) { selectedSessionID = session.id; selection = .learning }
        else { batchError = "恢复未保存，请重试。" }
    }
    private func prepareDeletion(_ ids: Set<UUID>) {
        do { deletionImpact = try SessionDeletion.impact(ids, context: modelContext) }
        catch { batchError = error.localizedDescription }
    }
    private var brand: some View {
        HStack(spacing: 8) {
            BrandMark(size: 27)
            Text("Review Today").font(.system(size: 15, weight: .semibold)).foregroundStyle(runway.ink).lineLimit(1)
            Spacer(minLength: 0)
            ChromeIconButton(title: "收起侧栏", symbol: "sidebar.left", action: onCollapse)
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 16)
    }

    private func sessionRow(_ session: AgentSession) -> some View {
        let selected = selectedSessionID == session.id && selection == .learning
        return Button { selectedSessionID = session.id; selection = .learning } label: {
                HStack(spacing: 7) {
                    SessionActivityStatus(sessionID: session.id, archived: session.status != "active")
                    Text(session.title).font(.callout.weight(selected ? .semibold : .regular))
                        .foregroundStyle(runway.ink).lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !session.memoryUseAllowed { MemoryExcludedMark() }
                    if let tag = session.displayTopicTags.first {
                        Text(tag).font(.caption2).foregroundStyle(runway.information)
                            .lineLimit(1).padding(.horizontal, 6).padding(.vertical, 3)
                            .background(runway.decorativeAccent.opacity(0.1), in: Capsule())
                            .frame(width: min(58, (tag as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 10)]).width + 12))
                            .help(session.displayTopicTags.joined(separator: " · "))
                    }
                }
                .padding(.horizontal, 8).padding(.vertical, 9)
                .padding(.trailing, 41)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(InteractionButtonStyle(selected: selected, hoverFeedback: false, focused: focusedSessionID == session.id, padding: 0, outline: .rounded(10)))
            .focusable().focusEffectDisabled()
            .focused($focusedSessionID, equals: session.id)
            .onKeyPress(keys: [.return, .space], phases: .down) { _ in
                guard focusedSessionID == session.id else { return .ignored }
                selectedSessionID = session.id; selection = .learning
                return .handled
            }
            .help(session.title)
            .accessibilityAddTraits(selected ? [.isSelected] : [])
            .overlay(alignment: .trailing) {
            SingleLevelMenu(title: "会话操作：\(session.title)", symbol: "ellipsis", items: [
                .init(id: "archive", title: session.status == "active" ? "归档" : "恢复", symbol: session.status == "active" ? "archivebox" : "arrow.uturn.backward"),
                .init(id: "tags", title: "编辑标签", symbol: "tag"),
                .init(id: "move", title: "移动到…", symbol: "folder"),
                .init(id: "memory", title: session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", symbol: "brain")
            ] + [.init(id: "delete", title: "删除会话", symbol: "trash", destructive: true)], onPresentationChange: { openMenuSessionID = $0 ? session.id : nil },
               onFocusChange: { focusedMenuSessionID = $0 ? session.id : nil }) { action in
                switch action {
                case "archive": if session.status == "active" { archive(session) } else { restore(session) }
                case "delete": prepareDeletion([session.id])
                case "tags": editingSessionID = session.id
                case "move": movingSession = session
                case "memory":
                    if !LearningMemory.setAllowed(!session.memoryUseAllowed, session: session, context: modelContext) { batchError = "记忆设置未保存，请重试。" }
                default: break
                }
            }
            .frame(width: 30).padding(.trailing, 7)
            .opacity(hoveredSessionID == session.id || focusedSessionID == session.id ||
                     openMenuSessionID == session.id || focusedMenuSessionID == session.id ? 1 : 0)
        }
        .onHover { hoveredSessionID = $0 ? session.id : nil }

        .contextMenu {
            if session.status == "active" { Button("归档", systemImage: "archivebox") { archive(session) } }
            else { Button("恢复", systemImage: "arrow.uturn.backward") { restore(session) } }
            Button("删除会话", systemImage: "trash", role: .destructive) { prepareDeletion([session.id]) }
            Button("移动到…", systemImage: "folder") { movingSession = session }
            Button("编辑标签", systemImage: "tag") { editingSessionID = session.id }
            Button(session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", systemImage: "brain") {
                if !LearningMemory.setAllowed(!session.memoryUseAllowed, session: session, context: modelContext) { batchError = "记忆设置未保存，请重试。" }
            }
        }
    }

}

struct SessionListToolbarButton: View {
    let title: String
    let symbol: String
    var accessibilityTitle: String? = nil
    var selected = false
    var secondary = false
    var destructive = false
    let action: () -> Void
    @FocusState private var focused: Bool
    @State private var hovering = false
    @Environment(\.runway) private var runway
    @Environment(\.controlActiveState) private var controlState

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(destructive ? Color.red : (secondary && !selected && !hovering ? runway.copy : runway.ink))
                .frame(width: 28, height: 28)
        }
        .buttonStyle(InteractionButtonStyle(selected: selected, focused: focused, padding: secondary ? 2 : 3))
        .focusable().focusEffectDisabled().focused($focused)
        .help(Text(LocalizedStringKey(accessibilityTitle ?? title)))
        .accessibilityLabel(Text(LocalizedStringKey(accessibilityTitle ?? title)))
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .onHover { hovering = $0 }
        .onChange(of: controlState) { _, state in if state != .key { hovering = false } }
        .onDisappear { hovering = false }
    }
}

struct SelectionCountLabel: View {
    let count: Int
    var body: some View {
        Label { Text(count.formatted()).monospacedDigit() } icon: { Image(systemName: "checkmark.circle") }
            .font(.caption).foregroundStyle(.secondary)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text("已选 \(count) 项"))
            .help(Text("已选 \(count) 项"))
    }
}

private struct SessionWelcome: View {
    var action: () -> Void
    @FocusState private var focused: Bool
    @Environment(\.runway) private var runway
    @Environment(\.colorScheme) private var colorScheme
    private var bubbleFill: Color { colorScheme == .dark ? runway.field : runway.card }

    var body: some View {
        VStack(spacing: 0) {
            Button(action: action) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("开始").font(BrandTypography.welcome(size: 13)).tracking(1)
                        .foregroundStyle(runway.copy).padding(.leading, 1)
                    Text("学习").font(BrandTypography.welcome(size: 22)).tracking(1)
                        .foregroundStyle(runway.ink)
                }
                .padding(.horizontal, 24).padding(.vertical, 12)
                .background(bubbleFill, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            }
            .buttonStyle(InteractionButtonStyle(focused: focused, padding: 0, outline: .rounded(24)))
            .focusable().focusEffectDisabled().focused($focused)
            .accessibilityLabel("开始学习")
            .help("进入 Agent 继续编辑草稿，不会自动发送")
            .shadow(color: runway.liftShadow.opacity(0.45), radius: 6, x: 0, y: 2)
            .rotationEffect(.degrees(-3)).offset(x: 14)
            VStack(spacing: 3) {
                Circle().fill(bubbleFill).frame(width: 8, height: 8).offset(x: 6)
                Circle().fill(bubbleFill).frame(width: 4, height: 4)
            }
            .padding(.top, 4).accessibilityHidden(true).allowsHitTesting(false)
            MascotMotion(phase: .idle, ambient: true, idleClip: .readingAndLooking)
                .frame(width: 150, height: 170).padding(.top, -48)
                // Keep the animation canvas intact, excluding transparent footroom from centering.
                .padding(.bottom, -38)
        }.frame(maxWidth: .infinity)
    }
}
