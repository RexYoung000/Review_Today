@testable import ReviewTodayContractSupport
import AppKit
import SwiftUI

@main struct AgentVoiceIntegrationApp {
    static func main() {
        do { try AgentVoiceIntegrationIsolation.prepare() }
        catch { fputs("Voice integration refused to launch outside its isolated home.\n", stderr); exit(78) }
        let app = NSApplication.shared, delegate = AgentVoiceIntegrationDelegate()
        app.delegate = delegate; app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}

@MainActor final class AgentVoiceIntegrationDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = AgentVoiceIntegrationState()
    let capture = AgentVoiceIntegrationCapture()
    var window: NSWindow!
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu(), appItem = NSMenuItem(), appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出连续语音验收", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu; menu.addItem(appItem)
        let editItem = NSMenuItem(), editMenu = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        editItem.submenu = editMenu; menu.addItem(editItem)
        let validationItem = NSMenuItem(), validationMenu = NSMenu(title: "验收")
        for (title, selector, key) in [("截取当前窗口", #selector(snapshot), "s"), ("开始／停止原速录像", #selector(record), "r"), ("400 pt 输入区", #selector(narrow), "9"), ("1000 pt 输入区", #selector(wide), "0"), ("开始模拟语音", #selector(start), "d"), ("模拟下一轮发言", #selector(nextTurn), "t"), ("模拟开口打断", #selector(bargeIn), "b"), ("结束语音", #selector(end), "e"), ("导出运行记录", #selector(export), "j")] {
            let item = validationMenu.addItem(withTitle: title, action: selector, keyEquivalent: key); item.target = self
        }
        for (title, selector, key) in [("自动验证播报中打断", #selector(automaticBargeIn), "k"), ("自动验证播报中静音", #selector(automaticMute), "m")] {
            let item = validationMenu.addItem(withTitle: title, action: selector, keyEquivalent: key); item.target = self
        }
        validationItem.submenu = validationMenu; menu.addItem(validationItem); NSApp.mainMenu = menu
        window = NSWindow(contentRect: .init(x: 0, y: 0, width: 1036, height: 760), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Review Today · 连续语音集成验收"
        window.titlebarAppearsTransparent = true; window.contentMinSize = .init(width: 436, height: 650)
        window.isReleasedWhenClosed = false; window.delegate = self
        window.contentView = NSHostingView(rootView: AgentVoiceIntegrationView(model: model, capture: capture, audit: auditEditor))
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { model.close() }
    func windowWillClose(_ notification: Notification) { model.close(); capture.recording = false }
    @objc func snapshot() { capture.snapshot() }
    @objc func record() { capture.toggleRecording() }
    @objc func narrow() { window.setContentSize(.init(width: 436, height: 792)) }
    @objc func wide() { window.setContentSize(.init(width: 1036, height: 760)) }
    @objc func start() { model.start() }
    @objc func nextTurn() { model.speak() }
    @objc func bargeIn() { model.speak(interrupt: true) }
    @objc func automaticBargeIn() { model.verifyDuringPlayback(mute: false) }
    @objc func automaticMute() { model.verifyDuringPlayback(mute: true) }
    @objc func end() { model.end() }
    @objc func export() { model.export() }
    func auditEditor() {
        func editors(_ view: NSView) -> [LearningEditor] {
            (view as? LearningEditor).map { [$0] } ?? view.subviews.flatMap(editors)
        }
        let values = window.contentView.map(editors) ?? []
        model.editorAudit = "正式编辑器：\(values.count) 个；" + values.map {
            "\(ObjectIdentifier($0))，可编辑 \($0.isEditable ? "是" : "否")"
        }.joined(separator: "；")
    }
}
