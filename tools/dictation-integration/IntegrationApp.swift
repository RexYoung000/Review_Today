@testable import ReviewTodayContractSupport
import AppKit
import SwiftUI

@main
struct DictationIntegrationApp {
    static func main() {
        do { try DictationIntegrationIsolation.prepare() }
        catch {
            fputs("Dictation integration refused to launch: isolated home verification failed. No fixture was created.\n", stderr)
            exit(78)
        }
        let app = NSApplication.shared
        let delegate = DictationIntegrationDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}

@MainActor
final class DictationIntegrationDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = DictationIntegrationState()
    let capture = DictationIntegrationCapture()
    var window: NSWindow!
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出集成验收", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu; menu.addItem(appItem)
        let editItem = NSMenuItem(); let editMenu = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        editItem.submenu = editMenu; menu.addItem(editItem)
        let validationItem = NSMenuItem(); let validationMenu = NSMenu(title: "验收")
        for (title, selector, key) in [("截取当前窗口", #selector(snapshot), "s"), ("开始／停止原速录像", #selector(record), "r"), ("400 pt 输入区", #selector(narrow), "9"), ("1000 pt 输入区", #selector(wide), "0"), ("开始模拟听写", #selector(start), "d"), ("完成听写", #selector(finish), "\r"), ("检查编辑器实例", #selector(auditEditor), "i")] {
            let item = validationMenu.addItem(withTitle: title, action: selector, keyEquivalent: key); item.target = self
        }
        validationItem.submenu = validationMenu; menu.addItem(validationItem)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: .init(x: 0, y: 0, width: 1036, height: 700), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Review Today · 听写集成验收"
        window.titlebarAppearsTransparent = true
        window.contentMinSize = .init(width: 436, height: 600)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = NSHostingView(rootView: DictationIntegrationView(model: model, capture: capture, audit: auditEditor))
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { model.close() }
    func windowWillClose(_ notification: Notification) { model.close(); capture.recording = false }
    @objc func snapshot() { capture.snapshot() }
    @objc func record() { capture.toggleRecording() }
    @objc func narrow() { window.setContentSize(.init(width: 436, height: 760)) }
    @objc func wide() { window.setContentSize(.init(width: 1036, height: 700)) }
    @objc func start() { model.start() }
    @objc func finish() { model.finish() }
    @objc func auditEditor() {
        func editors(_ view: NSView) -> [LearningEditor] {
            (view as? LearningEditor).map { [$0] } ?? view.subviews.flatMap(editors)
        }
        let values = window.contentView.map(editors) ?? []
        model.editorAudit = "正式编辑器实例：\(values.count)；" + values.map {
            "\(ObjectIdentifier($0))，可编辑 \($0.isEditable ? "是" : "否")，焦点 \(window.firstResponder === $0 ? "是" : "否")"
        }.joined(separator: "；")
    }
}
