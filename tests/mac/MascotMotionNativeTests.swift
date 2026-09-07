import AppKit
import SwiftUI
import WebKit

private struct CheckFailure: Error, CustomStringConvertible { var description: String }
@main
struct MascotMotionNativeTests {
    @MainActor static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let menu = NSMenu(), item = NSMenuItem(), submenu = NSMenu()
        submenu.addItem(withTitle: "退出动画验证", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = submenu; menu.addItem(item); app.mainMenu = menu
        let window = NSWindow(contentRect: NSRect(x: 140, y: 140, width: 760, height: 600), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Review Today · 原生动效验证"
        if CommandLine.arguments.contains("--interactive") {
            window.contentView = NSHostingView(rootView: MascotMotionPreview().environment(\.runway, .light))
        } else {
            Task { @MainActor in
                do { try await checks(window); print("Native animation checks passed"); exit(0) }
                catch { fputs("Native animation check failed: \(error)\n", stderr); exit(1) }
            }
        }
        window.makeKeyAndOrderFront(nil); app.activate(ignoringOtherApps: true); app.run()
    }
    @MainActor static func checks(_ window: NSWindow) async throws {
        func expect(_ value: Bool, _ reason: String) throws { if !value { throw CheckFailure(description: reason) } }
        for status in ["queued", "accepted", "completed", "failed", "cancelled", "stopped"] {
            try expect(MascotMotionConfiguration.phase(runStatus: status, started: true) == .idle, "False thinking state: \(status)")
        }
        try expect(MascotMotionConfiguration.phase(runStatus: "running", started: true) == .thinking, "Running mapping")
        try expect(MascotMotionConfiguration.phase(runStatus: "adjusting", started: true) == .thinking, "Adjusting mapping")
        try expect(MascotMotionConfiguration.phase(runStatus: "running", started: false) == .idle, "Unstarted run")
        let coordinator = MascotWebSurface.Coordinator(onReady: { _ in })
        let settings = WKWebViewConfiguration(); settings.websiteDataStore = .nonPersistent(); settings.userContentController.add(coordinator, name: "mascot")
        let web = PassiveMascotWebView(frame: NSRect(x: 0, y: 0, width: 760, height: 600), configuration: settings)
        coordinator.webView = web; web.navigationDelegate = coordinator; window.contentView = web
        guard let url = Bundle.main.url(forResource: "MascotMotion", withExtension: "html") else { throw CheckFailure(description: "Bundled resource missing") }
        let html = try String(contentsOf: url, encoding: .utf8)
        try expect(html.contains("connect-src 'none'"), "Offline boundary")
        web.loadHTMLString(html, baseURL: nil)
        for _ in 0..<200 { if coordinator.ready { break }; try await Task.sleep(for: .milliseconds(50)) }
        try expect(coordinator.ready, "WKWebView did not load bundled Spine modules")
        func inspect() async throws -> [String: Any] { try await web.evaluateJavaScript("window.mascotMotion.inspect()") as! [String: Any] }
        coordinator.configuration.mode = .thinking; coordinator.send()
        try await Task.sleep(for: .milliseconds(500))
        var state = try await inspect()
        try expect((state["time"] as? Double ?? 0) > 0.1, "Recall did not advance")
        coordinator.configuration.mode = .idle; coordinator.send()
        try await Task.sleep(for: .milliseconds(400)); state = try await inspect()
        try expect(state["animating"] as? Bool == false && state["time"] as? Double == 0, "Recall return did not settle")
        coordinator.configuration.mode = .thinking; coordinator.configuration.reduced = true; coordinator.send()
        try await Task.sleep(for: .milliseconds(100)); state = try await inspect()
        try expect(state["animating"] as? Bool == false, "Reduce Motion still runs a clock")
        coordinator.configuration.reduced = false; coordinator.send(); try await Task.sleep(for: .milliseconds(200))
        coordinator.setVisible(false); try await Task.sleep(for: .milliseconds(100)); let hidden = try await inspect()
        try await Task.sleep(for: .milliseconds(200)); state = try await inspect()
        try expect(state["time"] as? Double == hidden["time"] as? Double && state["animating"] as? Bool == false, "Hidden renderer advances")
        coordinator.setVisible(true)
        for phase in [MascotPhase.listening, .thinking, .speaking] {
            coordinator.configuration.surface = .voice; coordinator.configuration.mode = phase; coordinator.configuration.level = 0.85; coordinator.send()
            try await Task.sleep(for: .milliseconds(700)); state = try await inspect()
            let config = state["config"] as! [String: Any], voice = state["voice"] as! [String: Any]
            try expect(config["mode"] as? String == phase.rawValue && state["animating"] as? Bool == true, "Voice mode not applied: \(phase)")
            try expect(abs((voice["area"] as? Double ?? 0)-1) <= 0.1, "Native body lost area")
        }
        coordinator.configuration.mode = .idle; coordinator.configuration.level = 0; coordinator.send()
        try await Task.sleep(for: .seconds(3)); state = try await inspect()
        try expect(state["animating"] as? Bool == false, "Voice did not stop")
        try expect(web.acceptsFirstResponder == false && web.hitTest(.zero) == nil, "Decorative surface steals input")
        web.configuration.userContentController.removeScriptMessageHandler(forName: "mascot"); web.dispose()
    }
}
