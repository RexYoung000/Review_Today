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
            Text("人工标签会覆盖自动标签；Agent 不会静默改回。")
                .font(.caption).foregroundStyle(.secondary)
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
    var inboxCount: Int
    @Environment(\.modelContext) private var modelContext
    @Environment(\.runway) private var runway
    @Query(sort: \AgentSession.updatedAt, order: .reverse) private var sessions: [AgentSession]
    @Query(sort: \AgentRun.updatedAt, order: .reverse) private var runs: [AgentRun]
    @Query(sort: \LearningTask.updatedAt, order: .reverse) private var tasks: [LearningTask]
    @State private var searchText = ""
    @State private var showArchived = false
    @State private var hoveredSessionID: UUID?
    @State private var openMenuSessionID: UUID?
    @State private var focusedMenuSessionID: UUID?
    @FocusState private var focusedNavigation: SidebarItem?
    @FocusState private var focusedSessionID: UUID?
    @State private var editingSessionID: UUID?
    @State private var undoSessionID: UUID?
    @State private var searchVisible = false
    @State private var multiSelect = false
    @State private var selectedIDs = Set<UUID>()
    @State private var rangeAnchor: UUID?
    @State private var deletionImpact: SessionDeletionImpact?
    @Query private var deletionSettings: [AppSettings]
    @State private var batchError: String?
    @State private var visibleRowIDs = Set<UUID>()
    @State private var selectionDelays: [UUID: Double] = [:]
    @State private var undoBatchIDs = Set<UUID>()
    @FocusState private var sessionListFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var visibleSessions: [AgentSession] {
        sessions.filter { session in
            let statusMatch = showArchived ? session.status == "archived" : session.status == "active"
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
            return statusMatch && (query.isEmpty || session.title.localizedCaseInsensitiveContains(query) ||
                                   session.displayTopicTags.contains(where: { $0.localizedCaseInsensitiveContains(query) }))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SidebarWindowControls().frame(height: 32).padding(.horizontal, 18).padding(.top, 8)
            brand
            VStack(spacing: 4) {
                ForEach(SidebarItem.allCases) { item in sidebarRow(item) }
            }
            .padding(.horizontal, 10)

            Divider().padding(.vertical, 12)
            sessionNavigation

            if !undoBatchIDs.isEmpty {
                HStack {
                    Text("已归档 \(undoBatchIDs.count) 个会话")
                    Spacer()
                    Button("撤销") {
                        undoBatchIDs = Set(undoBatchIDs.filter { id in
                            guard let session = sessions.first(where: { $0.id == id }), session.status == "archived" else { return false }
                            return !LearningSessionActions.restore(session, context: modelContext)
                        })
                    }.buttonStyle(.borderless)
                }.font(.caption).padding(10)
            }

            if let undoSessionID, let session = sessions.first(where: { $0.id == undoSessionID }) {
                HStack(spacing: 8) {
                    Text("已归档").font(.caption)
                    Spacer()
                    Button("撤销") {
                        if LearningSessionActions.restore(session, context: modelContext) {
                            showArchived = false
                            selectedSessionID = session.id
                            self.undoSessionID = nil
                        }
                    }
                    .buttonStyle(.borderless)
                }
                .padding(10)
                .background(runway.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .padding(.horizontal, 10)
                .padding(.bottom, 6)
            }

            HStack {
                SettingsLink {
                    HStack(spacing: 8) {
                        Image(systemName: "gearshape").frame(width: 27)
                        Text("设置")
                    }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 8)
                        .contentShape(Rectangle()).foregroundStyle(Color.secondary)
                }.buttonStyle(InteractionButtonStyle(padding: 0))
                AnimatedThemeToggler()
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 16)
        }
        .background(runway.field.opacity(0.45))
        .sheet(item: $deletionImpact) { impact in
            SessionDeletionSheet(impact: impact) { ids in
                if selectedSessionID.map(ids.contains) == true { selectedSessionID = nil }
                selectedIDs.subtract(ids)
                undoBatchIDs.subtract(ids)
                undoSessionID = nil
            }
        }
        .sheet(isPresented: Binding(
            get: { editingSessionID != nil },
            set: { if !$0 { editingSessionID = nil } }
        )) {
            if let id = editingSessionID, let session = sessions.first(where: { $0.id == id }) {
                SessionTagEditor(session: session)
            }
        }
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

    private var sessionNavigation: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 0) {
                Text("会话").font(.subheadline.weight(.medium)).padding(4)
                Spacer(minLength: 0)
                ChromeIconButton(title: "搜索会话", symbol: "magnifyingglass", selected: searchVisible) {
                    searchVisible.toggle(); if !searchVisible { searchText = "" }
                }
                ChromeIconButton(title: showArchived ? "显示进行中会话" : "显示已归档会话", symbol: "archivebox", selected: showArchived) {
                    showArchived.toggle(); selectedIDs.removeAll()
                }
                ChromeIconButton(title: "多选会话", symbol: "checklist", selected: multiSelect) {
                    multiSelect.toggle(); selectedIDs.removeAll()
                }
                ChromeIconButton(title: "新对话", symbol: "plus", action: createSession)
            }
            .padding(.horizontal, 10)
            .environment(\.defaultMinListRowHeight, 30)

            if searchVisible {
              TextField("搜索会话", text: $searchText)
                .textFieldStyle(BrandMaterialTextFieldStyle())
                .padding(.horizontal, 10)
            }
            if showArchived { Text("已归档").font(.caption).foregroundStyle(.secondary).padding(.horizontal, 14) }
            if multiSelect {
                HStack(spacing: 8) {
                    Button(selectedIDs.count == visibleSessions.count ? "取消全选" : "全选") { selectAll() }
                    Text("\(selectedIDs.count)").monospacedDigit()
                    Spacer(minLength: 0)
                    if showArchived {
                        Button("永久删除", role: .destructive) { prepareDeletion(selectedIDs) }.disabled(selectedIDs.isEmpty)
                    }
                    Button(showArchived ? "恢复" : "归档") { batchArchive() }.disabled(selectedIDs.isEmpty)
                    Button { multiSelect = false; selectedIDs.removeAll() } label: { Image(systemName: "xmark") }.help("退出多选")
                }.font(.caption).buttonStyle(.borderless).padding(.horizontal, 12)
            }
            if deletionSettings.contains(where: { SessionDeletion.pendingCount($0.sessionDeletionsJSON) > 0 }) {
                Text("会话已从本机删除，后台清理待完成").font(.caption).foregroundStyle(.secondary).padding(.horizontal, 12)
            }
            if let batchError { Text(batchError).font(.caption).foregroundStyle(.orange).padding(.horizontal, 12) }
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(visibleSessions, id: \.id) { session in sessionRow(session) }
                    if visibleSessions.isEmpty {
                        if !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Text("没有匹配的会话").font(.callout).foregroundStyle(.secondary).padding(.top, 24)
                        } else if showArchived {
                            Text("没有归档会话").font(.callout).foregroundStyle(.secondary).padding(.top, 24)
                        }
                    }
                }
                .scrollTargetLayout()
                .padding(.horizontal, 8)
            }
            .overlay {
                if visibleSessions.isEmpty && !showArchived && searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    SessionWelcome(action: createSession)
                }
            }
            .scrollPosition(id: $scrollAnchor, anchor: .top)
            .scrollIndicators(.automatic)
            .focusable().focusEffectDisabled().focused($sessionListFocused)
            .onKeyPress("a", phases: .down) { press in
                guard multiSelect && press.modifiers.contains(.command) else { return .ignored }
                selectAll(); return .handled
            }
            .onKeyPress(.escape) {
                guard multiSelect else { return .ignored }
                multiSelect = false; selectedIDs.removeAll(); return .handled
            }
        }
        .frame(maxHeight: .infinity)
    }

    private func prepareDeletion(_ ids: Set<UUID>) {
        do { deletionImpact = try SessionDeletion.impact(ids, context: modelContext) }
        catch { batchError = "无法确认删除范围，请重试。" }
    }

    private func sessionRow(_ session: AgentSession) -> some View {
        let selected = multiSelect ? selectedIDs.contains(session.id) : selectedSessionID == session.id && selection == .learning
        let state = sessionState(session)
        return Button {
                if multiSelect || NSEvent.modifierFlags.contains(.command) || NSEvent.modifierFlags.contains(.shift) {
                    multiSelect = true
                    sessionListFocused = true
                    selectionDelays = [:]
                    if NSEvent.modifierFlags.contains(.shift), let anchor = rangeAnchor,
                       let a = visibleSessions.firstIndex(where: { $0.id == anchor }), let b = visibleSessions.firstIndex(where: { $0.id == session.id }) {
                        selectedIDs.formUnion(visibleSessions[min(a,b)...max(a,b)].map(\.id))
                    } else if !selectedIDs.insert(session.id).inserted { selectedIDs.remove(session.id) }
                    rangeAnchor = session.id
                } else { selectedSessionID = session.id; selection = .learning }
            } label: {
                HStack(spacing: 7) {
                    Group {
                      if multiSelect { SelectionDot(selected: selected, delay: selectionDelays[session.id] ?? 0) }
                      else if state.symbol == "circle" { Circle().fill(.secondary.opacity(0.4)).frame(width: 5, height: 5) }
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
                .init(id: "memory", title: session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", symbol: "brain")
            ] + (session.status == "archived" ? [.init(id: "delete", title: "永久删除", symbol: "trash", destructive: true)] : []), onPresentationChange: { openMenuSessionID = $0 ? session.id : nil },
               onFocusChange: { focusedMenuSessionID = $0 ? session.id : nil }) { action in
                switch action {
                case "archive": if session.status == "active" { archive(session) } else { restore(session) }
                case "delete": prepareDeletion([session.id])
                case "tags": editingSessionID = session.id
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
        .onAppear { visibleRowIDs.insert(session.id) }
        .onDisappear { visibleRowIDs.remove(session.id) }
        .contextMenu {
            if session.status == "active" { Button("归档", systemImage: "archivebox") { archive(session) } }
            else { Button("恢复", systemImage: "arrow.uturn.backward") { restore(session) } }
            if session.status == "archived" {
                Button("永久删除", systemImage: "trash", role: .destructive) { prepareDeletion([session.id]) }
            }
            Button("编辑标签", systemImage: "tag") { editingSessionID = session.id }
            Button(session.memoryUseAllowed ? "不用于跨会话记忆" : "允许跨会话记忆", systemImage: "brain") {
                if !LearningMemory.setAllowed(!session.memoryUseAllowed, session: session, context: modelContext) { batchError = "记忆设置未保存，请重试。" }
            }
        }
    }

    private func sidebarRow(_ item: SidebarItem) -> some View {
        let selected = selection == item && (item != .learning || selectedSessionID == nil)
        return Button { if item == .learning { selectedSessionID = nil }; selection = item } label: {
            HStack(spacing: 8) {
                Image(systemName: item.systemImage).frame(width: 27)
                Text(item.title)
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
        .buttonStyle(InteractionButtonStyle(focused: focusedNavigation == item, padding: 0, outline: .rounded(10)))
        .focusable().focusEffectDisabled().focused($focusedNavigation, equals: item)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    private func createSession() {
        showArchived = false
        onStartLearning()
    }

    private func selectAll() {
        let selecting = selectedIDs.count != visibleSessions.count
        selectionDelays = Dictionary(uniqueKeysWithValues: visibleSessions.filter { visibleRowIDs.contains($0.id) }.enumerated().map { ($0.element.id, min(Double($0.offset) * 0.012, 0.09)) })
        selectedIDs = selecting ? Set(visibleSessions.map(\.id)) : []
    }

    private func batchArchive() {
        var failed = Set<UUID>()
        var archived = Set<UUID>()
        for session in visibleSessions where selectedIDs.contains(session.id) {
            let saved = showArchived ? LearningSessionActions.restore(session, context: modelContext) : LearningSessionActions.archive(session, context: modelContext)
            if !saved { failed.insert(session.id) }
            else if !showArchived { archived.insert(session.id) }
        }
        undoBatchIDs = archived
        selectedIDs = failed
        batchError = failed.isEmpty ? nil : "\(failed.count) 个会话未保存，请重试。已成功的操作不会重复执行。"
        if failed.isEmpty { multiSelect = false }
    }

    private func archive(_ session: AgentSession) {
        if LearningSessionActions.archive(session, context: modelContext) { undoSessionID = session.id }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(6))
            if undoSessionID == session.id { undoSessionID = nil }
        }
    }

    private func restore(_ session: AgentSession) {
        if LearningSessionActions.restore(session, context: modelContext) {
            showArchived = false
            selectedSessionID = session.id
        }
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

private struct SidebarIconRail: View {
    @Binding var selection: SidebarItem?
    @Binding var selectedSessionID: UUID?
    let onExpand: () -> Void
    let onSessions: () -> Void
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
            ChromeIconButton(title: "新对话", symbol: "plus") { selectedSessionID = nil; selection = .learning }
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
                           scrollAnchor: $sidebarScrollAnchor, onCollapse: { setSidebar(expanded: false) }, onStartLearning: startLearning, inboxCount: inboxCount)
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
                                onSessions: { setSidebar(expanded: true) }, inboxCount: inboxCount)
                    .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous)).padding(8)
            }
            detailContent.padding(.top, 20).frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(PaperSurface())
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
        .onDisappear { monitor.stop() }
        .onAppear {
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
        selectedLearningSessionID = nil
        selection = .learning
        learningFocusRequest += 1
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
                    Text("开始").font(.system(size: 11, weight: .regular)).tracking(3)
                        .foregroundStyle(runway.copy).padding(.leading, 1)
                    Text("学习").font(.system(size: 20, weight: .medium, design: .rounded)).tracking(2)
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
