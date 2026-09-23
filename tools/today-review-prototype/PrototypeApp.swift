import AppKit
import SwiftUI

@main
struct TodayReviewPrototypeApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = PrototypeAppDelegate()
        app.delegate = delegate; app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}
@MainActor
final class PrototypeAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = PrototypeState()
    let capture = PrototypeCapture()
    var mainWindow: NSWindow!
    var reviewWindow: NSWindow?
    var summaryWindow: NSWindow?
    var summaryModel: PrototypeState?
    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        mainWindow = window(title: "Review Today · 交互原型", size: .init(width: 1160, height: 820), minimum: .init(width: 940, height: 640))
        mainWindow.contentView = NSHostingView(rootView: PrototypeAppearance(model: model) {
            PrototypeShell(model: self.model, openReview: self.openReview, openSummary: self.openSummary, capture: self.capture).frame(minWidth: 940, minHeight: 640)
        })
        mainWindow.center(); mainWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func window(title: String, size: NSSize, minimum: NSSize) -> NSWindow {
        let w = NSWindow(contentRect: .init(origin: .zero, size: size), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        w.title = title; w.contentMinSize = minimum; w.isReleasedWhenClosed = false
        w.titlebarAppearsTransparent = true; w.delegate = self
        return w
    }
    func openReview() {
        model.prepare()
        if reviewWindow == nil {
            let w = window(title: "复习 · 交互原型", size: .init(width: 860, height: 820), minimum: .init(width: 700, height: 650))
            w.contentView = NSHostingView(rootView: PrototypeAppearance(model: model) {
                PrototypeReview(model: self.model, capture: self.capture, close: { self.reviewWindow?.performClose(nil) }).frame(minWidth: 700, minHeight: 650)
            })
            reviewWindow = w; w.center()
        }
        reviewWindow?.makeKeyAndOrderFront(nil)
    }
    func openSummary() {
        if let summaryWindow, summaryWindow.isVisible {
            summaryWindow.makeKeyAndOrderFront(nil); return
        }
        let preview = PrototypeState.makeSummaryPreview(dark: model.dark, reduced: model.reduced)
        summaryModel = preview
        let w = window(title: "本轮小结 · 示例预览", size: .init(width: 980, height: 880), minimum: .init(width: 700, height: 700))
        w.contentView = NSHostingView(rootView: PrototypeAppearance(model: preview) {
            PrototypeSummaryPreview(model: preview, capture: self.capture, close: { self.summaryWindow?.performClose(nil); self.showToday() })
                .frame(minWidth: 700, minHeight: 700)
        })
        summaryWindow = w; w.center(); w.makeKeyAndOrderFront(nil)
    }
    func windowWillClose(_ notification: Notification) {
        if notification.object as? NSWindow === reviewWindow { model.close() }
        if notification.object as? NSWindow === summaryWindow { summaryModel?.close() }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool { mainWindow.makeKeyAndOrderFront(nil); return true }
    private func buildMenu() {
        let bar = NSMenu()
        let app = NSMenuItem(); let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于此原型", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator()); appMenu.addItem(withTitle: "退出原型", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu; bar.addItem(app)
        let edit = NSMenuItem(); let em = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] { em.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key) }
        edit.submenu = em; bar.addItem(edit)
        let preview = NSMenuItem(); let pm = NSMenu(title: "原型")
        for (title, selector, key) in [("打开今天", #selector(showToday), "1"), ("打开复习", #selector(showReview), "2"), ("打开小结预览", #selector(showSummary), "4"), ("截取当前窗口", #selector(snapshot), "s"), ("开始／停止原速录制", #selector(record), "r"), ("默认窗口尺寸", #selector(defaultSize), "0"), ("最小窗口尺寸", #selector(minimumSize), "9")] { let item = pm.addItem(withTitle: title, action: selector, keyEquivalent: key); item.target = self }
        pm.addItem(.separator()); pm.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        let reflection = pm.addItem(withTitle: "切换入口流光演示", action: #selector(previewGlass), keyEquivalent: "3")
        reflection.target = self
        preview.submenu = pm; bar.addItem(preview)
        NSApp.mainMenu = bar
    }
    @objc func showToday() { model.page = .today; mainWindow.makeKeyAndOrderFront(nil) }
    @objc func showReview() { openReview() }
    @objc func showSummary() { openSummary() }
    @objc func previewGlass() {
        showToday()
        model.previewGlassEntry = model.previewGlassEntry == nil ? "开始学习" : model.previewGlassEntry == "开始学习" ? "模拟考" : nil
    }
    @objc func snapshot() { capture.snapshot() }
    @objc func record() { capture.toggleRecording() }
    @objc func defaultSize() { NSApp.keyWindow?.setContentSize(NSApp.keyWindow === summaryWindow ? .init(width: 980, height: 880) : NSApp.keyWindow === reviewWindow ? .init(width: 860, height: 820) : .init(width: 1160, height: 820)) }
    @objc func minimumSize() { NSApp.keyWindow?.setContentSize(NSApp.keyWindow === summaryWindow ? .init(width: 700, height: 700) : NSApp.keyWindow === reviewWindow ? .init(width: 700, height: 650) : .init(width: 940, height: 640)) }
    @objc func about() { let alert = NSAlert(); alert.messageText = "今天＋语音复习交互原型"; alert.informativeText = "独立合成数据。判断、保存、声音与排期均为演示；不调用真实模型，不使用麦克风，不写正式复习成绩。关闭复习窗口保留本次运行的进度，退出原型后重置。"; alert.runModal() }
}
struct PrototypeAppearance<Content: View>: View {
    @Bindable var model: PrototypeState
    @ViewBuilder var content: () -> Content
    var body: some View {
        content().environment(\.runway, .brandMonochrome(dark: model.dark))
            .environment(\.brandMaterialTrial, true).environment(\.brandTrialStill, model.reduced)
            .preferredColorScheme(model.dark ? .dark : .light)
            .tint(model.dark ? .white : .black).background(PaperSurface())
            .foregroundStyle(model.dark ? Color(white: 0.96) : Color(white: 0.10))
            .onChange(of: model.dark) { _, dark in NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua) }
    }
}

struct PrototypeButton: View {
    @Environment(\.isEnabled) private var enabled
    var title: String
    var symbol: String? = nil
    var selected = false
    var action: () -> Void
    @FocusState private var focused: Bool
    var body: some View {
        Button(action: action) { HStack(spacing: 7) { if let symbol { Image(systemName: symbol) }; Text(title).fixedSize() }.fixedSize(horizontal: true, vertical: false).padding(.horizontal, 9).padding(.vertical, 6).frame(minHeight: 30) }
            .buttonStyle(InteractionButtonStyle(selected: selected, focused: focused, padding: 0, outline: .rounded(10)))
            .focusable().focusEffectDisabled().focused($focused)
            .onKeyPress(keys: [.return, .space], phases: .down) { _ in
                guard focused && enabled else { return .ignored }; action(); return .handled
            }
    }
}
struct PrototypeBadge: View {
    var body: some View { Text("交互原型").font(.system(size: 11, weight: .medium)).padding(.horizontal, 9).padding(.vertical, 4).background(.primary.opacity(0.055), in: Capsule()).accessibilityLabel("交互原型，使用独立合成数据") }
}

/// Shared paper metric surface for Today and the review summary.
struct PrototypeMetricCard: View {
    let title: String
    let value: Int
    var minimumHeight: CGFloat = 84
    @Environment(\.runway) private var palette
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("\(value)").font(.system(size: 30, weight: .semibold)).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: minimumHeight, alignment: .leading).padding(16)
        .background(palette.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
        .shadow(color: palette.liftShadow, radius: 8, y: 2)
        .accessibilityElement(children: .combine)
    }
}

/// Keep native keyboard focus explicit even when macOS's "all controls" setting is off.
struct PrototypePrimaryButton: View {
    var title: String
    var enabled = true
    var action: () -> Void
    @FocusState private var focused: Bool
    @Environment(\.runway) private var palette
    var body: some View {
        RunwayPrimaryButton(title: title, enabled: enabled, action: action)
            .focusable(enabled).focusEffectDisabled().focused($focused)
            .overlay(Capsule().strokeBorder(focused ? palette.ink : .clear, lineWidth: 1).padding(-3).allowsHitTesting(false))
            .onKeyPress(keys: [.return, .space], phases: .down) { _ in
                guard enabled else { return .ignored }; action(); return .handled
            }
    }
}

struct PrototypeKeyboardAction: ViewModifier {
    var radius: CGFloat = 18
    var action: () -> Void
    @FocusState private var focused: Bool
    @Environment(\.isEnabled) private var enabled
    @Environment(\.runway) private var palette
    @ObservedObject private var input = InteractionInputMode.shared
    func body(content: Content) -> some View {
        content.focusable(enabled).focusEffectDisabled().focused($focused)
            .overlay(RoundedRectangle(cornerRadius: radius).strokeBorder(focused && input.keyboardNavigation ? palette.ink : .clear, lineWidth: 1.5).allowsHitTesting(false))
            .onKeyPress(keys: [.return, .space], phases: .down) { _ in
                guard enabled && focused else { return .ignored }; action(); return .handled
            }
    }
}
