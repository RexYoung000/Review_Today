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
struct SidebarIconRail: View {
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

private struct NavigationRowFrames: PreferenceKey {
    static let defaultValue: [SidebarItem: CGRect] = [:]
    static func reduce(value: inout [SidebarItem: CGRect], nextValue: () -> [SidebarItem: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

/// Pointer updates stay in these four rows, outside the session queries/list.
struct SidebarPrimaryNavigation: View {
    @Binding var selection: SidebarItem?
    @Binding var selectedSessionID: UUID?
    var inboxCount: Int
    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduceMotion
    @FocusState private var focusedNavigation: SidebarItem?
    @State private var navigationFrames: [SidebarItem: CGRect] = [:]
    @State private var hoveredNavigation: SidebarItem?
    @Environment(\.controlActiveState) private var navigationWindowState
    var body: some View {
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
                    .fill(runway.navigationHover)
                    .frame(width: rect.width, height: rect.height)
                    .offset(x: rect.minX, y: rect.minY)
                    .animation(reduceMotion ? nil : .easeOut(duration: 0.08), value: item)
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
                // Keep the transaction out of labels, buttons and the destination page.
                hoveredNavigation = nearest
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
            .foregroundStyle(selected || hoveredNavigation == item ? runway.ink : Color.secondary)
            .background(selected ? runway.navigationSelection : .clear, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
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

}
