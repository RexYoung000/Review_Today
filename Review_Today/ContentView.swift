import SwiftData
import SwiftUI
import UserNotifications

enum SidebarItem: String, Hashable, CaseIterable, Identifiable {
    case today
    case learning
    case library
    case inbox

    var id: String { rawValue }

    var title: String {
        switch self {
        case .today: String(localized: "今天")
        case .learning: "Agent"
        case .library: String(localized: "知识库")
        case .inbox: String(localized: "待处理")
        }
    }

    var systemImage: String {
        switch self {
        case .today: "sun.max"
        case .learning: "terminal"
        case .library: "books.vertical"
        case .inbox: "tray"
        }
    }
}

@MainActor
enum LearningSessionActions {
    @discardableResult
    static func archive(_ session: AgentSession, context: ModelContext) -> Bool {
        let sid = session.id
        let runs = (try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
        for run in runs where ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) {
            if let started = run.startedAt { run.elapsedMS = max(0, Int(Date.now.timeIntervalSince(started) * 1000)) }
            run.startedAt = nil
            run.status = "interrupted"
            run.revision += 1
            run.userSummary = "已停止；会话已归档"
        }
        let messages = (try? context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
        for message in messages {
            if message.responseState == "streaming" { message.responseState = "interrupted" }
            if message.deliveryStatus == "local" { message.deliveryStatus = "held" }
        }
        for control in (try? context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { $0.sessionID == sid && !$0.sent }))) ?? [] {
            control.sent = true // superseded by the atomic Session lifecycle action
            control.lastError = "RT.SESSION.ARCHIVED"
        }
        session.runPaused = true
        session.pendingOperationJSON = nil
        appendLifecycle("archive", session: session)
        session.status = "archived"
        session.archivedAt = .now
        session.updatedAt = .now
        do { try context.save(); ConversationSync.wake(); return true }
        catch { context.rollback(); return false }
    }

    @discardableResult
    static func restore(_ session: AgentSession, context: ModelContext) -> Bool {
        appendLifecycle("restore", session: session)
        session.status = "active"
        session.runPaused = true
        session.archivedAt = nil
        session.updatedAt = .now
        do { try context.save(); ConversationSync.wake(); return true }
        catch { context.rollback(); return false }
    }

    private static func appendLifecycle(_ action: String, session: AgentSession) {
        session.lifecycleRevision += 1
        var actions = (session.lifecycleActionsJSON.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [[String: Any]]) ?? []
        actions.append(["action_id": UUID().uuidString.lowercased(), "action": action, "lifecycle_revision": session.lifecycleRevision])
        session.lifecycleActionsJSON = ConversationProcessor.json(actions)
    }
}

struct SessionTagEditor: View {
    @Bindable var session: AgentSession
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Query private var references: [KnowledgeReference]
    @Query private var knowledge: [Knowledge]
    @State private var tagsText: String

    init(session: AgentSession) {
        self.session = session
        _tagsText = State(initialValue: session.displayTopicTags.joined(separator: "，"))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("编辑会话标签").font(.headline)
            TextField("用逗号分隔，最多 5 个", text: $tagsText)
                .textFieldStyle(BrandMaterialTextFieldStyle())
            if !knowledgeTags.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("关联知识标签 · 只读").font(.caption.weight(.semibold))
                    Text(knowledgeTags.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            HStack {
                Button("恢复自动标签") {
                    session.restoreAutomaticTopicTags()
                    tagsText = session.automaticTopicTags.joined(separator: "，")
                    try? modelContext.save()
                }
                .disabled(session.manualTopicTags == nil)
                Spacer()
                Button("取消") { dismiss() }
                Button("保存") {
                    session.setManualTopicTags(parsedTags)
                    try? modelContext.save()
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 380)
    }

    private var parsedTags: [String] {
        tagsText.components(separatedBy: CharacterSet(charactersIn: "，,\n"))
    }

    private var knowledgeTags: [String] {
        let ids = Set(references.filter { $0.sessionID == session.id }.map(\.knowledgeID))
        return Array(Set(knowledge.filter { ids.contains($0.id) }.map(\.theme).filter { !$0.isEmpty })).sorted()
    }
}

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
    @Query(sort: \AgentRun.updatedAt, order: .reverse) private var runs: [AgentRun]
    @Query(sort: \LearningTask.updatedAt, order: .reverse) private var tasks: [LearningTask]
    @State private var hoveredSessionID: UUID?
    @State private var openMenuSessionID: UUID?
    @State private var focusedMenuSessionID: UUID?
    @FocusState private var focusedNavigation: SidebarItem?
    @State private var navigationFrames: [SidebarItem: CGRect] = [:]
    @State private var hoveredNavigation: SidebarItem?
    @Environment(\.controlActiveState) private var navigationWindowState
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
            primaryNavigation.padding(.horizontal, 10)
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
                    ForEach(activeSessions.filter { session in !folders.contains(where: { $0.id == session.folderID }) }) { session in sessionRow(session) }
                    ForEach(folders) { folder in
                        folderHeader(folder)
                        if !collapsed.contains(folder.id.uuidString) {
                            ForEach(activeSessions.filter { $0.folderID == folder.id }) { session in sessionRow(session).padding(.leading, 12) }
                        }
                    }
                }.scrollTargetLayout().padding(.horizontal, 8)
            }
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
        let state = sessionState(session)
        return Button { selectedSessionID = session.id; selection = .learning } label: {
                HStack(spacing: 7) {
                    Group {
                      if state.symbol == "circle" { Circle().fill(.secondary.opacity(0.4)).frame(width: 5, height: 5) }
                      else { Image(systemName: state.symbol).help(state.label) }
                    }
                        .font(.caption).foregroundStyle(state.problem ? Color.orange : .secondary)
                        .frame(width: 13)
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
            .buttonStyle(InteractionButtonStyle(selected: selected, focused: focusedSessionID == session.id, padding: 0, outline: .rounded(10)))
            .focusable().focusEffectDisabled()
            .focused($focusedSessionID, equals: session.id)
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

    private var primaryNavigation: some View {
        VStack(spacing: 4) {
            ForEach(SidebarItem.allCases) { item in
                sidebarRow(item)
                    .background(GeometryReader { geometry in
                        Color.clear.preference(key: NavigationRowFrames.self,
                            value: [item: geometry.frame(in: .named("primaryNavigation"))])
                    })
            }
        }
        .coordinateSpace(name: "primaryNavigation")
        .onPreferenceChange(NavigationRowFrames.self) { frames in
            if navigationFrames != frames {
                navigationFrames = frames
                hoveredNavigation = nil
            }
        }
        .background(alignment: .topLeading) {
            if let item = hoveredNavigation, let rect = navigationFrames[item] {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(runway.field.opacity(0.5))
                    .frame(width: rect.width, height: rect.height)
                    .offset(x: rect.minX, y: rect.minY)
                    .allowsHitTesting(false).accessibilityHidden(true)
            }
        }
        .contentShape(Rectangle())
        .onContinuousHover(coordinateSpace: .named("primaryNavigation")) { phase in
            switch phase {
            case .active(let point):
                guard navigationWindowState == .key, !navigationFrames.isEmpty else { return }
                let nearest = SidebarItem.allCases.min {
                    abs((navigationFrames[$0]?.midY ?? .infinity) - point.y) <
                    abs((navigationFrames[$1]?.midY ?? .infinity) - point.y)
                }
                guard nearest != hoveredNavigation else { return }
                // Animate only travel inside this group, never the initial entry.
                withAnimation(reduceMotion || hoveredNavigation == nil ? nil : .easeOut(duration: 0.12)) {
                    hoveredNavigation = nearest
                }
            case .ended: hoveredNavigation = nil
            }
        }
        .onChange(of: navigationWindowState) { _, state in
            if state != .key { hoveredNavigation = nil }
        }
        .onDisappear { hoveredNavigation = nil }
    }

    private func sidebarRow(_ item: SidebarItem) -> some View {
        let selected = selection == item && (item != .learning || selectedSessionID == nil)
        return Button { if item == .learning { selectedSessionID = nil }; selection = item } label: {
            HStack(spacing: 8) {
                Image(systemName: item.systemImage).frame(width: 27)
                Text(item.title).fontWeight(selected ? .semibold : .regular)
                Spacer()
                if item == .inbox, inboxCount > 0 {
                    Text("\(inboxCount)").font(.caption.weight(.semibold))
                        .padding(.horizontal, 7).padding(.vertical, 2).background(runway.field, in: Capsule())
                }
            }
            .padding(.horizontal, 6).padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .foregroundStyle(selected ? runway.ink : Color.secondary)
            .background(selected ? runway.field : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(InteractionButtonStyle(hoverFeedback: false, focused: focusedNavigation == item, padding: 0, outline: .rounded(10)))
        .focusable().focusEffectDisabled().focused($focusedNavigation, equals: item)
        .onKeyPress(keys: [.return, .space], phases: .down) { _ in
            guard focusedNavigation == item else { return .ignored }
            if item == .learning { selectedSessionID = nil }
            selection = item
            return .handled
        }
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    private func sessionState(_ session: AgentSession) -> (symbol: String, label: String, problem: Bool) {
        guard session.status == "active" else { return ("archivebox", "已归档", false) }
        guard let run = runs.first(where: { $0.sessionID == session.id }) else { return ("circle", "尚未运行", false) }
        if ["retryable_failed", "terminal_failed"].contains(run.status) { return ("exclamationmark.triangle", "运行失败", true) }
        if ["interrupted", "cancelled"].contains(run.status) { return ("pause.circle", "已停止", false) }
        if ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) { return ("circle.dotted", "\(run.userSummary)", false) }
        if let task = tasks.first(where: { $0.sessionID == session.id }), task.status == "awaiting_user" {
            return ("bubble.left", task.requiredActionType == "submit_answer" ? "等待作答" : "可继续学习", false)
        }
        return ("circle", "", false)
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

private struct SidebarIconRail: View {
    @Binding var selection: SidebarItem?
    @Binding var selectedSessionID: UUID?
    let onExpand: () -> Void
    let onSessions: () -> Void
    let onNewSession: () -> Void
    let inboxCount: Int
    @Environment(\.runway) private var runway

    var body: some View {
        VStack(spacing: 8) {
            SidebarWindowControls().frame(width: 60, height: 32).padding(.top, 8)
            Button(action: onExpand) { BrandMark(size: 27).frame(width: 38, height: 34) }
                .buttonStyle(InteractionButtonStyle(padding: 2))
                .help("展开侧栏").accessibilityLabel("Review Today，展开侧栏")
                .padding(.top, 12).padding(.bottom, 8)
            ForEach(SidebarItem.allCases) { item in
                ChromeIconButton(title: item == .inbox && inboxCount > 0 ? "待处理，\(inboxCount) 项" : item.title,
                                 symbol: item.systemImage,
                                 selected: selection == item && (item != .learning || selectedSessionID == nil)) {
                    if item == .learning { selectedSessionID = nil }
                    selection = item
                }
            }
            Divider().padding(.vertical, 6)
            ChromeIconButton(title: "展开会话列表", symbol: "bubble.left.and.bubble.right",
                             selected: selection == .learning && selectedSessionID != nil, action: onSessions)
            ChromeIconButton(title: "新对话", symbol: "plus", action: onNewSession)
            Spacer(minLength: 12)
            SettingsLink { Image(systemName: "gearshape").font(.system(size: 14)).frame(width: 28, height: 28) }
                .buttonStyle(InteractionButtonStyle(padding: 2)).help("设置").accessibilityLabel("设置")
            AnimatedThemeToggler().padding(.bottom, 16)
        }
        .padding(.horizontal, 10).frame(width: 88)
        .background(PaperSurface())
        .overlay(alignment: .trailing) { Rectangle().fill(runway.hairline).frame(width: 1) }
    }
}

struct ContentView: View {
    @Environment(\.brandMaterialPreview) private var materialPreview
    @Environment(\.modelContext) private var modelContext
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    var coordinator: ReviewCoordinator
    @State private var selection: SidebarItem?
    @State private var learningFocusRequest = 0
    @State private var searchPresented = false
    @State private var creationError: String?
    @State private var draftEntrance = true
    @Environment(\.brandReduceMotion) private var reduceMotion
    @State private var selectedKnowledgeID: UUID?
    @State private var selectedLearningSessionID: UUID?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @AppStorage("reviewToday.sidebarVisible") private var sidebarVisible = true
    @State private var sidebarPolicy = SidebarVisibilityPolicy()
    @State private var sidebarScrollAnchor: UUID?
    @AppStorage("reviewToday.sidebarWidth") private var savedSidebarWidth = 280.0
    @State private var sidebarResizeStart: Double?
    @State private var monitor = AgentServiceMonitor()
    @Query private var inbox: [CaptureTask]
    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var learningTasks: [LearningTask]
    @Query private var learningSessions: [AgentSession]

    init(coordinator: ReviewCoordinator) {
        self.coordinator = coordinator
#if DEBUG
        let fixtureEnabled = M1DebugFixture.enabled
        let fixtureSelection: SidebarItem = M1DebugFixture.mode == "learning" ? .learning : M1DebugFixture.mode == "today" ? .today : .library
        _selection = State(initialValue: fixtureEnabled ? fixtureSelection : .today)
        _selectedKnowledgeID = State(initialValue: fixtureEnabled ? M1DebugFixture.knowledgeID : nil)
#else
        _selection = State(initialValue: .today)
        _selectedKnowledgeID = State(initialValue: nil)
#endif
    }

    var body: some View {
        HStack(spacing: 0) {
            if columnVisibility != .detailOnly {
                AppSidebar(selection: $selection, selectedSessionID: $selectedLearningSessionID,
                           scrollAnchor: $sidebarScrollAnchor, onCollapse: { setSidebar(expanded: false) }, onStartLearning: startLearning, onSearch: { searchPresented = true }, inboxCount: inboxCount)
                    .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
                    .padding(8)
                    .frame(width: min(340, max(250, savedSidebarWidth)))
                Color.clear.frame(width: 6).contentShape(Rectangle())
                    .onHover { hovering in
                        if hovering { NSCursor.resizeLeftRight.push() } else { NSCursor.pop() }
                    }
                    .gesture(DragGesture().onChanged { value in
                        if sidebarResizeStart == nil { sidebarResizeStart = min(340, max(250, savedSidebarWidth)) }
                        savedSidebarWidth = min(340, max(250, (sidebarResizeStart ?? 280) + value.translation.width))
                    }.onEnded { _ in sidebarResizeStart = nil })
                    .accessibilityLabel("侧栏宽度")
                    .accessibilityValue("\(Int(min(340, max(250, savedSidebarWidth))))")
                    .accessibilityAdjustableAction { direction in
                        savedSidebarWidth = min(340, max(250, min(340, max(250, savedSidebarWidth)) + (direction == .increment ? 20 : -20)))
                    }
            } else {
                SidebarIconRail(selection: $selection, selectedSessionID: $selectedLearningSessionID,
                                onExpand: { setSidebar(expanded: true) },
                                onSessions: { setSidebar(expanded: true) }, onNewSession: { setSidebar(expanded: true); startLearning() }, inboxCount: inboxCount)
                    .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous)).padding(8)
            }
            detailContent
                .opacity(selection == .learning && !draftEntrance ? 0 : 1)
                .offset(y: selection == .learning && !draftEntrance ? 8 : 0)
                .padding(.top, 20).frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(PaperSurface())
        .accessibilityHidden(searchPresented)
        .overlay {
            if searchPresented {
                SessionSearchOverlay(onOpen: { session in
                    selectedLearningSessionID = session.id; selection = .learning; searchPresented = false
                }, onClose: {
                    searchPresented = false
                    NotificationCenter.default.post(name: .sessionSearchClosed, object: nil)
                })
            }
        }
        .background(ConversationWindowTarget { id in
            selectedLearningSessionID = id; selection = .learning; searchPresented = false
        })
        .toolbar(.hidden, for: .windowToolbar)
        .ignoresSafeArea(.container, edges: .top)
        .toolbar(removing: .sidebarToggle)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if AppRuntime.current.mode != .normal {
                Text(AppRuntime.current.isPreview ? "界面预览 · 仅内存数据，不连接模型" : "真实模型隔离验收 · 独立数据，不写入日常知识库")
                    .font(.caption2).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity).padding(.vertical, 4)
                    .background(PaperSurface())
            }
        }
        .frame(minWidth: 760, minHeight: 620)
        .onGeometryChange(for: Bool.self) { $0.size.width < 900 } action: { narrow in
            sidebarPolicy.resize(narrow: narrow)
            columnVisibility = sidebarPolicy.expanded ? .all : .detailOnly
        }
        .task {
#if DEBUG
            if AppRuntime.current.isPreview { monitor.useFixturePresentation(); return }
#endif
            await ConversationSync().run(context: modelContext, monitor: monitor)
        }
        .task {
#if DEBUG
            if AppRuntime.current.isPreview { monitor.useFixturePresentation(); return }
#endif
            monitor.start()
            if AppRuntime.current.mode == .normal { ReminderNotifications.request() }
            while !Task.isCancelled {
                await HarnessProcessor.tick(context: modelContext, monitor: monitor)
                await CaptureProcessor.tick(context: modelContext, monitor: monitor)
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .alert("无法新建会话", isPresented: Binding(get: { creationError != nil }, set: { if !$0 { creationError = nil } })) {
            Button("好", role: .cancel) { creationError = nil }
        } message: { Text(creationError ?? "") }
        .onDisappear { monitor.stop() }
        .onAppear {
            do { try AgentComposerStore.preserveLandingDraft(context: modelContext) }
            catch { creationError = "原有草稿暂时无法保存为会话，请重试。" }
            sidebarPolicy.preferredExpanded = sidebarVisible
            columnVisibility = sidebarPolicy.expanded ? .all : .detailOnly
#if DEBUG
            if M1DebugFixture.enabled {
                if M1DebugFixture.mode == "review" {
                    coordinator.startPreview(knowledgeID: M1DebugFixture.knowledgeID, questionID: M1DebugFixture.questionID)
                    openWindow(id: "review")
                } else if M1DebugFixture.mode == "retry" {
                    coordinator.startFormal(knowledgeIDs: [M1DebugFixture.knowledgeID])
                    openWindow(id: "review")
                } else {
                    Task { @MainActor in
                        try? await Task.sleep(for: .milliseconds(600))
                        dismissWindow(id: "review")
                    }
                }
            }
#endif
            UNUserNotificationCenter.current().delegate = NotificationRelay.shared
            NotificationRelay.shared.onStart = { startDueReview() }
            NotificationRelay.shared.onSnooze = { minutes in handleSnooze(minutes) }
            NotificationRelay.shared.onSkip = { skipToday() }
        }
    }

    private func startLearning() {
        NotificationCenter.default.post(name: .prepareNewConversation, object: nil)
        do {
            try AgentComposerStore.preserveLandingDraft(context: modelContext)
            let session = try AgentComposerStore.createSession(context: modelContext)
            selectedLearningSessionID = session.id
            sidebarScrollAnchor = session.id
            selection = .learning
            searchPresented = false
            learningFocusRequest += 1
            if !reduceMotion {
                draftEntrance = false
                Task { @MainActor in
                    await Task.yield()
                    withAnimation(.easeOut(duration: 0.18)) { draftEntrance = true }
                }
            }
        } catch { creationError = "新会话未保存，请重试。已有输入仍保留。" }
    }

    private func setSidebar(expanded: Bool) {
        sidebarPolicy.choose(expanded: expanded)
        sidebarVisible = expanded
        columnVisibility = sidebarPolicy.expanded ? .all : .detailOnly
    }

    private var detailContent: some View {
        Group {
                switch selection ?? .today {
                case .today:
                    TodayView(
                        coordinator: coordinator,
                        onOpenKnowledge: { id in
                            selectedKnowledgeID = id
                            selection = .library
                        },
                        onOpenInbox: { selection = .inbox },
                        onOpenLibrary: { selection = .library },
                        onOpenLearning: { id in
                            selectedLearningSessionID = id
                            selection = .learning
                        }
                    )
                case .learning:
                    LearningWorkspace(
                        monitor: monitor,
                        selectedSessionID: $selectedLearningSessionID,
                        entryFocusRequest: learningFocusRequest,
                        onEntryFocusConsumed: { learningFocusRequest = 0 },
                        onNewSession: startLearning,
                        onOpenKnowledge: { id in
                            selectedKnowledgeID = id
                            selection = .library
                        }
                    )
                case .library:
                    LibraryView(selectedID: $selectedKnowledgeID, coordinator: coordinator, onStartLearning: startLearning)
                case .inbox:
                    InboxView(onOpenSession: { id in selectedLearningSessionID = id; selection = .learning })
                }
            }
    }

    private var inboxCount: Int {
        inbox.filter { $0.status == "needs_attention" || $0.status == "retryable_failed" }.count +
        learningTasks.filter { LearningDecisionInbox.includes($0, sessions: learningSessions) }.count
    }

    private func startDueReview() {
        let developer = settingsRows.first?.developerMode == true
        let due = knowledge.filter { ReviewQueue.isDue($0, developerMode: developer) }
        guard !due.isEmpty else { return }
        coordinator.startFormal(knowledgeIDs: due.map(\.id))
        openWindow(id: "review")
    }

    private func handleSnooze(_ minutes: Int) {
        guard let settings = settingsRows.first else { return }
        let key = TodayView.todayStamp()
        if settings.snoozeDay != key {
            settings.snoozeDay = key
            settings.snoozeCount = 0
        }
        guard settings.snoozeCount < 2 else { return }
        settings.snoozeCount += 1
        ReminderNotifications.snooze(minutes: minutes)
        try? modelContext.save()
    }

    private func skipToday() {
        settingsRows.first?.skipToday = TodayView.todayStamp()
        try? modelContext.save()
    }
}

final class NotificationRelay: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationRelay()
    var onStart: (() -> Void)?
    var onSnooze: ((Int) -> Void)?
    var onSkip: (() -> Void)?

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        switch response.actionIdentifier {
        case "start", UNNotificationDefaultActionIdentifier:
            onStart?()
        case "later15":
            onSnooze?(15)
        case "later60":
            onSnooze?(60)
        case "skip":
            onSkip?()
        default:
            break
        }
        completionHandler()
    }
}

#Preview {
    ContentView(coordinator: ReviewCoordinator())
        .runwayAppearance()
        .modelContainer(
            for: [
                Source.self,
                Knowledge.self,
                Question.self,
                CaptureTask.self,
                AppSettings.self,
                FsrsState.self,
                ReviewSession.self,
                ReviewAttempt.self,
                AgentSession.self,
                SessionFolder.self,
                AgentMessage.self,
                LearningTask.self,
                TaskEventRecord.self,
                SourceReference.self,
                KnowledgeReference.self,
                SessionSummaryRecord.self,
                AgentRun.self,
                AgentRunControl.self,
                SessionEventRecord.self,
            ],
            inMemory: true
        )
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

private struct NavigationRowFrames: PreferenceKey {
    static let defaultValue: [SidebarItem: CGRect] = [:]
    static func reduce(value: inout [SidebarItem: CGRect], nextValue: () -> [SidebarItem: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}
