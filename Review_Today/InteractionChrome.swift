import AppKit
import Combine
import SwiftUI

enum InteractionOutline: Equatable {
    case rounded(CGFloat)
    case capsule
    var shape: InteractionGeometry { InteractionGeometry(outline: self) }
}

struct InteractionGeometry: InsettableShape {
    var outline: InteractionOutline
    var amount: CGFloat = 0
    func path(in rect: CGRect) -> Path {
        switch outline {
        case .capsule: Capsule().inset(by: amount).path(in: rect)
        case .rounded(let radius): RoundedRectangle(cornerRadius: radius, style: .continuous).inset(by: amount).path(in: rect)
        }
    }
    func inset(by amount: CGFloat) -> InteractionGeometry {
        var copy = self; copy.amount += amount; return copy
    }
}

/// Track input modality without moving first responder or consuming events.
@MainActor
final class InteractionInputMode: ObservableObject {
    static let shared = InteractionInputMode()
    @Published private(set) var keyboardNavigation = false
    private var monitor: Any?

    init() {
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .leftMouseDown, .rightMouseDown, .otherMouseDown]) { [weak self] event in
            self?.receive(event)
            return event
        }
    }

    deinit { if let monitor { NSEvent.removeMonitor(monitor) } }

    func receive(_ event: NSEvent) {
        switch event.type {
        case .leftMouseDown, .rightMouseDown, .otherMouseDown:
            keyboardNavigation = false
        case .keyDown:
            // Tab, arrows and Escape are navigation; typing alone is not.
            if [48, 53, 123, 124, 125, 126].contains(event.keyCode) {
                keyboardNavigation = true
            }
        default: break
        }
    }
}

/// Shared feedback, without changing the geometry of navigation or text rows.
struct InteractionButtonStyle: ButtonStyle {
    var selected = false
    // Owned by the control, not inherited from a focusable list/container.
    var focused = false
    var padding: CGFloat = 6
    var outline: InteractionOutline = .rounded(9)

    func makeBody(configuration: Configuration) -> some View {
        Feedback(configuration: configuration, selected: selected, focused: focused, padding: padding, outline: outline)
    }

    private struct Feedback: View {
        let configuration: ButtonStyle.Configuration
        let selected: Bool
        let focused: Bool
        let padding: CGFloat
        let outline: InteractionOutline
        @State private var hovering = false
        @ObservedObject private var inputMode = InteractionInputMode.shared
        @Environment(\.isEnabled) private var enabled
        @Environment(\.controlActiveState) private var controlState
        @Environment(\.brandReduceMotion) private var reduced
        @Environment(\.runway) private var runway

        var body: some View {
            configuration.label
                .padding(padding)
                .background(background, in: outline.shape)
                .overlay(outline.shape
                    .fill(hovering && enabled ? runway.hoverWash.opacity(0.035) : .clear)
                    .allowsHitTesting(false))
                .overlay(outline.shape
                    .strokeBorder(focused && inputMode.keyboardNavigation && enabled && controlState == .key ? runway.agent : .clear, lineWidth: 1.5))
                .contentShape(outline.shape)
                .opacity(enabled ? (configuration.isPressed ? 0.78 : 1) : 0.4)
                .onHover { hovering = $0 }
                .onChange(of: controlState) { _, state in if state != .key { hovering = false } }
                .onDisappear { hovering = false }
                .animation(reduced ? nil : .easeOut(duration: 0.12), value: hovering)
        }

        private var background: Color {
            guard enabled else { return .clear }
            if configuration.isPressed { return runway.ink.opacity(0.12) }
            if selected { return runway.monochrome ? runway.agent.opacity(0.10) : runway.field }
            return hovering ? runway.field.opacity(0.7) : .clear
        }
    }
}

struct ChromeIconButton: View {
    let title: String
    let symbol: String
    var selected = false
    let action: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 14))
                .frame(width: 28, height: 28)
        }
        .buttonStyle(InteractionButtonStyle(selected: selected, focused: focused, padding: 2))
        .focusable().focusEffectDisabled().focused($focused)
        .help(title).accessibilityLabel(title)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

struct ChoiceMenuItem: Identifiable {
    let id: String
    let title: String
    let symbol: String
    var detail = ""
    var destructive = false
}

/// A native, single-level popover. No nested Menu/Picker and no hidden option layer.
struct SingleLevelMenu: View {
    let title: String
    let symbol: String
    var label = ""
    var selectedID: String? = nil
    var arrowEdge: Edge = .bottom
    let items: [ChoiceMenuItem]
    var onPointerSelection: () -> Void = {}
    var onPresentationChange: (Bool) -> Void = { _ in }
    var onFocusChange: (Bool) -> Void = { _ in }
    let action: (String) -> Void
    @State private var presented = false
    @State private var closeReason = CloseReason.outside
    @State private var selectionTime: TimeInterval = 0
    @FocusState private var triggerFocused: Bool
    @Environment(\.runway) private var runway

    private enum CloseReason { case outside, keyboard, pointerSelection }

    var body: some View {
        Button {
            closeReason = .outside
            presented.toggle()
        } label: {
            HStack(spacing: 6) {
                Image(systemName: symbol).frame(width: 18)
                if !label.isEmpty { Text(label).lineLimit(1) }
            }.frame(minHeight: 26)
        }
        .buttonStyle(InteractionButtonStyle(selected: presented, focused: triggerFocused))
        .focusable().focusEffectDisabled()
        .focused($triggerFocused)
        .help(title).accessibilityLabel(label.isEmpty ? title : "\(title)：\(label)")
        .accessibilityValue(presented ? "已展开" : "已收起")
        .onChange(of: triggerFocused) { _, value in onFocusChange(value) }
        .onChange(of: presented) { _, value in onPresentationChange(value) }
        .popover(isPresented: $presented, arrowEdge: arrowEdge) {
            ChoiceMenuContent(items: items, selectedID: selectedID, onSelect: { id in
                selectionTime = NSApp.currentEvent?.timestamp ?? 0
                closeReason = NSApp.currentEvent?.type == .keyDown ? .keyboard : .pointerSelection
                presented = false
                action(id)
            }, onEscape: {
                selectionTime = NSApp.currentEvent?.timestamp ?? 0
                closeReason = .keyboard
                presented = false
            })
            .environment(\.runway, runway)
            .onDisappear {
                // Outside clicks keep their new focus. Only deliberate menu actions restore it.
                switch closeReason {
                case .keyboard:
                    if FocusReturnPolicy.allows(since: selectionTime, current: NSApp.currentEvent) { triggerFocused = true }
                case .pointerSelection:
                    if FocusReturnPolicy.allows(since: selectionTime, current: NSApp.currentEvent) { onPointerSelection() }
                case .outside: break
                }
            }
        }
    }
}

enum FocusReturnPolicy {
    /// A second deliberate interaction wins over a delayed popover dismissal.
    static func allows(since timestamp: TimeInterval, current: NSEvent?) -> Bool {
        guard let current, current.timestamp > timestamp else { return true }
        return ![NSEvent.EventType.leftMouseDown, .rightMouseDown, .keyDown].contains(current.type)
    }
}

private struct ChoiceMenuContent: View {
    let items: [ChoiceMenuItem]
    let selectedID: String?
    let onSelect: (String) -> Void
    let onEscape: () -> Void
    @FocusState private var focus: String?
    @Environment(\.runway) private var runway

    var body: some View {
        VStack(spacing: 3) {
            ForEach(items) { item in
                Button(role: item.destructive ? .destructive : nil) { onSelect(item.id) } label: {
                    HStack(spacing: 12) {
                        Image(systemName: item.symbol).font(.system(size: 17))
                            .foregroundStyle(.secondary).frame(width: 22)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.title).font(.callout.weight(.medium)).foregroundStyle(item.destructive ? Color.red : runway.ink)
                            if !item.detail.isEmpty {
                                Text(item.detail).font(.caption).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        Image(systemName: "checkmark").foregroundStyle(runway.agent)
                            .opacity(selectedID == item.id ? 1 : 0).frame(width: 14)
                    }.padding(9).contentShape(Rectangle())
                }
                .buttonStyle(InteractionButtonStyle(selected: selectedID == item.id, focused: focus == item.id, padding: 0))
                .focusable().focusEffectDisabled()
                .focused($focus, equals: item.id)
                .accessibilityAddTraits(selectedID == item.id ? [.isSelected] : [])
            }
        }
        .padding(7).frame(width: 290).foregroundStyle(runway.ink)
        .onAppear { DispatchQueue.main.async { focus = selectedID ?? items.first?.id } }
        .onKeyPress(.escape) { onEscape(); return .handled }
        .onKeyPress(.downArrow) { move(1); return .handled }
        .onKeyPress(.upArrow) { move(-1); return .handled }
        .onKeyPress(.return) {
            if let focus { onSelect(focus) }
            return .handled
        }
    }

    private func move(_ direction: Int) {
        guard !items.isEmpty else { return }
        let current = items.firstIndex { $0.id == focus } ?? 0
        focus = items[(current + direction + items.count) % items.count].id
    }
}

struct QuickStartCard: View {
    let start: AgentQuickStart
    let action: () -> Void
    @State private var hovering = false
    @FocusState private var focused: Bool
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.runway) private var runway

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 7) {
                Label(start.title, systemImage: start.symbol).font(.callout.weight(.semibold))
                Text(start.detail).font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: 66, alignment: .topLeading)
            .padding(14)
            .background(runway.card, in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16)
                .strokeBorder(hovering ? runway.decorativeAccent.opacity(0.45) : runway.hairline, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: 16))
        }
        .buttonStyle(InteractionButtonStyle(focused: focused, padding: 0, outline: .rounded(16)))
        .focusable().focusEffectDisabled().focused($focused)
        .scaleEffect(hovering && !reduced ? 1.012 : 1)
        .onHover { hovering = $0 }
        .animation(reduced ? nil : .easeOut(duration: 0.16), value: hovering)
        .help("填入可编辑草稿，不会自动发送")
    }
}

/// The user's preference is separate from transient automatic width adaptation.
struct SidebarVisibilityPolicy {
    var preferredExpanded = true
    private(set) var narrow = false
    private var explicitlyExpandedInNarrowWindow = false
    var expanded: Bool { preferredExpanded && (!narrow || explicitlyExpandedInNarrowWindow) }

    mutating func resize(narrow value: Bool) {
        if value != narrow { explicitlyExpandedInNarrowWindow = false }
        narrow = value
    }

    mutating func choose(expanded value: Bool) {
        preferredExpanded = value
        explicitlyExpandedInNarrowWindow = value && narrow
    }
}
