import AppKit
import WebKit

private struct Failure: Error, CustomStringConvertible { let description: String }

@main
struct ExamEntrySpineNativeTests {
    @MainActor static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 220, height: 220),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "Review Today · 模拟考 Spine 验证"
        let settings = WKWebViewConfiguration()
        settings.websiteDataStore = .nonPersistent()
        let web = WKWebView(frame: window.contentView!.bounds, configuration: settings)
        web.setValue(false, forKey: "drawsBackground")
        web.underPageBackgroundColor = .clear
        window.contentView = web
        window.makeKeyAndOrderFront(nil)
        app.activate(ignoringOtherApps: true)
        Task { @MainActor in
            do { try await check(web); print("Exam Spine native checks passed"); exit(0) }
            catch { fputs("Exam Spine native check failed: \(error)\n", stderr); exit(1) }
        }
        app.run()
    }

    @MainActor static func check(_ web: WKWebView) async throws {
        guard let url = Bundle.main.url(forResource: "ExamEntrySpine", withExtension: "html") else {
            throw Failure(description: "Bundled Spine resource missing")
        }
        let html = try String(contentsOf: url, encoding: .utf8)
        guard html.contains("connect-src 'none'") && !html.contains("mascot.json") else {
            throw Failure(description: "Renderer must be offline and contain no mascot rig")
        }
        web.loadHTMLString(html, baseURL: nil)
        func state() async throws -> [String: Any] {
            try await web.evaluateJavaScript("window.examMotion?.inspect()") as? [String: Any] ?? [:]
        }
        func pixels() async throws -> Int {
            try await web.evaluateJavaScript("(()=>{const c=document.querySelector('canvas'),p=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let n=0;for(let i=3;i<p.length;i+=4)if(p[i]>128)n++;return n})()") as? Int ?? 0
        }
        for _ in 0..<120 {
            if (try? await state()["ready"] as? Bool) == true { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        let loaded = try await state()
        guard loaded["ready"] as? Bool == true, loaded["hasMascot"] as? Bool == false else {
            throw Failure(description: "Dedicated checklist renderer did not load: \(loaded)")
        }
        guard try await pixels() == 0 else { throw Failure(description: "Idle canvas is not transparent") }
        _ = try await web.evaluateJavaScript("window.examMotion.setState({playing:true,dark:false})")
        try await Task.sleep(for: .milliseconds(1030))
        let running = try await state()
        guard running["playing"] as? Bool == true,
              (running["elapsed"] as? Double ?? 0) > 0.8,
              try await pixels() > 100 else {
            throw Failure(description: "Checklist did not finish sequential pop: \(running)")
        }
        _ = try await web.evaluateJavaScript("window.examMotion.setState({playing:false,dark:false})")
        guard try await pixels() == 0 else { throw Failure(description: "Mouse exit left a stale frame") }
        _ = try await web.evaluateJavaScript("window.examMotion.setState({playing:true,dark:true})")
        try await Task.sleep(for: .milliseconds(980))
        let dark = try await state()
        guard dark["dark"] as? Bool == true, try await pixels() > 100 else {
            throw Failure(description: "Dark checklist did not draw: \(dark)")
        }
        _ = try await web.evaluateJavaScript("window.examMotion.setState({playing:false,dark:true})")
        print("PASS: offline transparent Spine, visible sequence, exit reset, dark variant, no mascot rig")
    }
}
