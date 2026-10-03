import AppKit
import SwiftUI

enum DictationComposerPhase: Equatable {
    case permission, recording, transcribing, cleaning, applying, failed
}

/// Presentation only. Audio levels, elapsed time and phase come from the real
/// dictation controller; this surface never starts audio or generates a signal.
struct DictationComposerStatus: View {
    let phase: DictationComposerPhase
    let level: Double
    let elapsed: Double
    var error: String? = nil
    let onCancel: () -> Void
    let onFinish: () -> Void
    let onRetry: () -> Void

    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.colorScheme) private var colorScheme
    @State private var visible = false
    @FocusState private var focusedAction: Action?

    private enum Action: Hashable { case cancel, confirm }
    private var recording: Bool { phase == .recording }
    private var failed: Bool { phase == .failed }
    private var safeLevel: Double { level.isFinite ? max(0, min(1, level)) : 0 }
    private var seconds: Int { elapsed.isFinite ? Int(max(0, min(300, elapsed))) : 0 }
    private var elapsedText: String { String(format: "%d:%02d", seconds / 60, seconds % 60) }
    private var inputStrength: String {
        safeLevel < 0.018 ? "等待声音" : safeLevel < 0.2 ? "声音较轻" : "有声音输入"
    }
    private var remainingText: String? { seconds >= 240 ? "剩余 \(300 - seconds) 秒" : nil }
    private var title: String {
        switch phase {
        case .permission: return "正在请求麦克风权限"
        case .recording: return "正在听写"
        case .transcribing: return "正在转成文字…"
        case .cleaning: return "正在整理文字…"
        case .applying: return "正在保存草稿…"
        case .failed: return "听写未完成"
        }
    }
    private var detail: String {
        switch phase {
        case .permission: return "允许后才会开始收音。"
        case .recording: return [remainingText, reduced ? inputStrength : nil].compactMap { $0 }.joined(separator: " · ")
        case .transcribing, .cleaning: return "完成后添加到草稿，由你确认发送。"
        case .applying: return "保存完成后可编辑并发送。"
        case .failed: return "本次听写已保留，可重试或丢弃。"
        }
    }
    private var accessibleValue: String {
        guard recording else { return detail }
        return (["已录 \(seconds / 60) 分 \(seconds % 60) 秒", inputStrength] + [remainingText].compactMap { $0 })
            .joined(separator: "，")
    }
    private var processing: Bool {
        phase == .transcribing || phase == .cleaning || phase == .applying
    }
    private var animateDecoration: Bool {
        visible && !reduced && (processing || (recording && safeLevel > 0))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                if phase != .applying { cancelButton }
                VStack(alignment: .leading, spacing: 8) {
                    statusHeading
                    if recording {
                        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !animateDecoration)) { context in
                            DictationComposerWaveform(level: safeLevel,
                                time: context.date.timeIntervalSinceReferenceDate, reduced: reduced)
                        }
                        .frame(height: 43)
                        .accessibilityHidden(true)
                    } else {
                        statusDetail
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if recording || failed { confirmButton }
            }
            if failed, let error, !error.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(error)
                    .font(.system(size: 12))
                    .foregroundStyle(.white.opacity(0.82))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 20)
        .frame(maxWidth: .infinity, minHeight: 137, alignment: .leading)
        .foregroundStyle(.white)
        .background(Color(white: colorScheme == .dark ? 0.055 : 0.085), in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(.white.opacity(colorScheme == .dark ? 0.24 : 0.04), lineWidth: 1))
        .shadow(color: runway.liftShadow.opacity(0.35), radius: 8, y: 2)
        .background(DictationComposerVisibility { visible = $0 })
        .onDisappear { visible = false }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("听写")
    }

    private var statusHeading: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(title)
                    .font(.system(size: 13, weight: .medium))
                    .fixedSize(horizontal: false, vertical: true)
                if recording {
                    Text(elapsedText)
                        .font(.system(size: 12, design: .monospaced))
                        .monospacedDigit()
                        .foregroundStyle(.white.opacity(0.65))
                        .fixedSize()
                }
            }
            if recording, !detail.isEmpty {
                Text(detail)
                    .font(.system(size: 11))
                    .foregroundStyle(.white.opacity(0.65))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityValue(recording ? accessibleValue : "")
    }

    private var statusDetail: some View {
        HStack(alignment: .top, spacing: 8) {
            if processing {
                TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !animateDecoration)) { context in
                    ZStack {
                        Circle().stroke(.white.opacity(0.24), lineWidth: 2)
                        Circle().trim(from: 0, to: 0.72)
                            .stroke(.white, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                            .rotationEffect(.degrees(reduced ? -90 : context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.2) * 300))
                    }
                }
                .frame(width: 16, height: 16)
                .accessibilityHidden(true)
            } else {
                Image(systemName: failed ? "exclamationmark.circle" : "mic.slash")
                    .font(.system(size: 16))
                    .accessibilityHidden(true)
            }
            Text(detail)
                .font(.system(size: 12))
                .foregroundStyle(.white.opacity(0.70))
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var cancelButton: some View {
        Button(action: onCancel) {
            Image(systemName: "xmark")
                .font(.system(size: 13, weight: .medium))
                .frame(width: 34, height: 34)
                .background(.white.opacity(0.09), in: Circle())
                .overlay(Circle().strokeBorder(focusedAction == .cancel ? .white : .clear, lineWidth: 1).padding(-3))
        }
        .buttonStyle(.plain)
        .focusable().focusEffectDisabled().focused($focusedAction, equals: .cancel)
        .keyboardShortcut(.cancelAction)
        .help(failed ? "丢弃本次听写，保留原草稿 · Esc" : "取消听写，保留原草稿 · Esc")
        .accessibilityLabel(failed ? "丢弃听写" : "取消听写")
    }

    private var confirmButton: some View {
        Button(action: failed ? onRetry : onFinish) {
            Label(failed ? "重试" : "完成听写", systemImage: failed ? "arrow.clockwise" : "checkmark")
                .font(.system(size: 13, weight: .semibold))
                .padding(.horizontal, 14)
                .frame(height: 38)
                .foregroundStyle(Color(white: 0.08))
                .background(.white, in: Capsule())
                .overlay(Capsule().strokeBorder(focusedAction == .confirm ? .white : .clear, lineWidth: 1).padding(-3))
        }
        .buttonStyle(.plain).fixedSize()
        .focusable().focusEffectDisabled().focused($focusedAction, equals: .confirm)
        // Only mounted during recording or recovery; plain Return remains an
        // editor action when the parent restores the ordinary composer.
        .keyboardShortcut(.return, modifiers: .command)
        .help(failed ? "重试本次听写 · ⌘Return" : "停止收音并转成草稿，不会发送 · ⌘Return")
    }
}

private struct DictationComposerWaveform: View {
    let level: Double
    let time: Double
    let reduced: Bool

    var body: some View {
        GeometryReader { geometry in
            let strength = reduced ? 0.3 : level
            ZStack {
                Ellipse()
                    .fill(.white.opacity(reduced ? 0.08 : 0.05 + strength * 0.22))
                    .frame(width: geometry.size.width * (reduced ? 0.60 : 0.32 + strength * 0.45), height: reduced ? 20 : 8 + strength * 24)
                    .blur(radius: 15)
                Capsule()
                    .fill(LinearGradient(colors: [.clear, .white.opacity(reduced ? 0.2 : 0.15 + strength * 0.6), .clear], startPoint: .leading, endPoint: .trailing))
                    .frame(height: 1)
                    .blur(radius: 1)
                Canvas { context, size in
                    let count = max(20, min(70, Int(size.width / 8)))
                    let spacing = size.width / CGFloat(count)
                    for index in 0..<count {
                        let normalized = Double(index) / Double(count - 1)
                        let envelope = 0.3 + 0.7 * pow(sin(normalized * .pi), 0.7)
                        let oscillation = reduced ? 0.5 : 0.25 + 0.75 * abs(sin(time * 7.4 - Double(index) * 0.58) * cos(time * 3.1 + Double(index) * 0.22))
                        let height = 3 + strength * 39 * envelope * oscillation
                        let rect = CGRect(x: CGFloat(index) * spacing + (spacing - 3) / 2, y: (size.height - height) / 2, width: 3, height: height)
                        context.fill(Path(roundedRect: rect, cornerRadius: 1.5), with: .color(.white.opacity(0.4 + envelope * 0.6)))
                    }
                }
                .shadow(color: .white.opacity(reduced ? 0.12 : strength * 0.8), radius: 5)
            }
        }
    }
}

/// Observes this surface's actual window, including AppKit-hosted test windows.
/// It never intercepts input or asks for microphone/screen access.
private struct DictationComposerVisibility: NSViewRepresentable {
    var changed: (Bool) -> Void

    func makeNSView(context: Context) -> Probe { Probe() }
    func updateNSView(_ view: Probe, context: Context) {
        view.changed = changed
        view.updateVisibility()
    }
    static func dismantleNSView(_ view: Probe, coordinator: ()) {
        view.changed = nil
        view.dispose()
    }

    final class Probe: NSView {
        var changed: ((Bool) -> Void)?
        private var lastReported: Bool?
        private var observers: [NSObjectProtocol] = []
        override var acceptsFirstResponder: Bool { false }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override init(frame: NSRect) {
            super.init(frame: frame)
            setAccessibilityElement(false)
            setAccessibilityHidden(true)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            dispose()
            guard window != nil else { updateVisibility(); return }
            for name in [NSWindow.didChangeOcclusionStateNotification, NSWindow.didMiniaturizeNotification,
                         NSWindow.didDeminiaturizeNotification, NSWindow.didBecomeKeyNotification,
                         NSWindow.didResignKeyNotification, NSApplication.didBecomeActiveNotification,
                         NSApplication.didResignActiveNotification, NSApplication.didHideNotification,
                         NSApplication.didUnhideNotification] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                    MainActor.assumeIsolated { self?.updateVisibility() }
                })
            }
            updateVisibility()
        }
        override func viewDidHide() { super.viewDidHide(); updateVisibility() }
        override func viewDidUnhide() { super.viewDidUnhide(); updateVisibility() }
        func updateVisibility() {
            let next = window?.isVisible == true && window?.isMiniaturized == false && window?.isKeyWindow == true
                && window?.occlusionState.contains(.visible) == true && NSApp.isActive
                && !NSApp.isHidden && !isHiddenOrHasHiddenAncestor
            guard lastReported != next else { return }
            lastReported = next
            // AppKit may notify during SwiftUI layout. Publish on the next turn,
            // and discard an obsolete visibility result if the window moved.
            DispatchQueue.main.async { [weak self] in
                guard let self, self.lastReported == next else { return }
                self.changed?(next)
            }
        }
        func dispose() {
            observers.forEach(NotificationCenter.default.removeObserver)
            observers.removeAll()
        }
        deinit { observers.forEach(NotificationCenter.default.removeObserver) }
    }
}
