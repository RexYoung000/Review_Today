import AppKit
import SwiftUI

@main
struct DictationPrototypeApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = DictationPrototypeDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}

@MainActor
final class DictationPrototypeDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = DictationDemoState()
    let capture = DictationDemoCapture()
    var window: NSWindow!
    func applicationDidFinishLaunching(_ notification: Notification) {
        let bar = NSMenu()
        let appItem = NSMenuItem(); let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出听写小样", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu; bar.addItem(appItem)
        let editItem = NSMenuItem(); let editMenu = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        editItem.submenu = editMenu; bar.addItem(editItem)
        let demoItem = NSMenuItem(); let demoMenu = NSMenu(title: "小样")
        for (title, selector, key) in [("截取当前小样", #selector(snapshot), "s"), ("开始／停止原速录像", #selector(record), "r"), ("窄窗口", #selector(narrow), "9"), ("默认窗口", #selector(normal), "0"), ("开始听写", #selector(start), "d"), ("完成听写", #selector(finish), "\r")] {
            let item = demoMenu.addItem(withTitle: title, action: selector, keyEquivalent: key); item.target = self
        }
        demoItem.submenu = demoMenu; bar.addItem(demoItem)
        NSApp.mainMenu = bar
        window = NSWindow(contentRect: .init(x: 0, y: 0, width: 1000, height: 790), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Review Today · 听写对照"
        window.titlebarAppearsTransparent = true
        window.contentMinSize = .init(width: 650, height: 620)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = NSHostingView(rootView: DictationDemoView(model: model, capture: capture))
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard capture.savingRecording else { return .terminateNow }
        capture.recording = false
        Task { @MainActor in
            while capture.savingRecording { try? await Task.sleep(for: .milliseconds(100)) }
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
    func windowWillClose(_ notification: Notification) { model.cancel(); capture.recording = false }
    @objc func snapshot() { capture.snapshot() }
    @objc func record() { capture.toggleRecording() }
    @objc func narrow() { window.setContentSize(.init(width: 650, height: 760)) }
    @objc func normal() { window.setContentSize(.init(width: 1000, height: 790)) }
    @objc func start() { model.start() }
    @objc func finish() { model.finish() }
}
