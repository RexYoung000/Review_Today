import AppKit
import SwiftUI
import SwiftData
import WebKit
import ScreenCaptureKit

@MainActor @Observable private final class HeaderQAState {
    var dark = false
    var reduced = false
    var shown = true
    var selected: UUID?
    let monitor = AgentServiceMonitor()
}

private struct HeaderQARoot: View {
    @Bindable var state: HeaderQAState
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("标题吉祥物 · 隔离原生验收").font(.caption)
                Spacer()
                Toggle("深色", isOn: $state.dark)
                Toggle("减少动态", isOn: $state.reduced)
                Toggle("显示页面", isOn: $state.shown)
            }.padding(12)
            if state.shown {
                LearningWorkspace(monitor: state.monitor, selectedSessionID: $state.selected, onOpenKnowledge: { _ in })
            } else { Spacer() }
        }
        .environment(\.runway, .brandMonochrome(dark: state.dark))
        .environment(\.brandMaterialTrial, true)
        .environment(\.brandTrialStill, state.reduced)
        .preferredColorScheme(state.dark ? .dark : .light)
    }
}

private struct HeaderQAError: Error { let message: String }
private final class HeaderRecordingDelegate: NSObject, SCRecordingOutputDelegate {
    var finished = false
    nonisolated func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) {
        Task { @MainActor in self.finished = true }
    }
}

@main struct AgentTitleMascotNativeTests {
    @MainActor static func main() {
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "learning", 1)
        unsetenv("REVIEW_TODAY_NATIVE_TEST_DIR")
        let app = NSApplication.shared; app.setActivationPolicy(.regular)
        let menu = NSMenu(), appItem = NSMenuItem(), appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu; menu.addItem(appItem)
        let editItem = NSMenuItem(), edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit; menu.addItem(editItem); app.mainMenu = menu
        let state = HeaderQAState()
        let container = try! M1DebugFixture.makeContainer(mode: "learning")
        let window = NSWindow(contentRect: NSRect(x: 120, y: 100, width: 1040, height: 760), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Review Today · 标题吉祥物验证"
        window.contentView = NSHostingView(rootView: HeaderQARoot(state: state).modelContainer(container))
        window.makeKeyAndOrderFront(nil); app.activate(ignoringOtherApps: true)
        Task { @MainActor in
            do {
                try await checks(window, state)
                print("PASS: Agent title mascot native checks", terminator: "\n"); fflush(stdout)
                if !CommandLine.arguments.contains("--interactive") { exit(0) }
            } catch { fputs("FAIL: \(error)\n", stderr); if !CommandLine.arguments.contains("--interactive") { exit(1) } }
        }
        app.run()
    }

    @MainActor private static func checks(_ window: NSWindow, _ state: HeaderQAState) async throws {
        func expect(_ value: Bool, _ message: String) throws { if !value { throw HeaderQAError(message: message) }; print("PASS: \(message)") }
        func find<T: NSView>(_ type: T.Type, in view: NSView?) -> T? {
            guard let view else { return nil }; if let match = view as? T { return match }
            return view.subviews.compactMap { find(type, in: $0) }.first
        }
        func region() -> AgentTitlePointerRegion.RegionView? { find(AgentTitlePointerRegion.RegionView.self, in: window.contentView) }
        func ready() async throws -> WKWebView {
            for _ in 0..<200 {
                if let driver = region()?.driver, driver.renderer?.ready == true, let web = driver.renderer?.webView { return web }
                try await Task.sleep(for: .milliseconds(30))
            }
            throw HeaderQAError(message: "header renderer not ready")
        }
        let web = try await ready()
        func inspect(_ current: WKWebView = web) async throws -> [String: Any] {
            try await current.evaluateJavaScript("window.mascotMotion.inspect()") as! [String: Any]
        }
        func mouse(_ point: NSPoint, type: NSEvent.EventType = .mouseMoved) {
            let event = NSEvent.mouseEvent(with: type, location: point, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                windowNumber: window.windowNumber, context: nil, eventNumber: 1, clickCount: type == .mouseMoved ? 0 : 1, pressure: 1)!
            NSApp.postEvent(event, atStart: false)
        }
        let folder = URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("docs/evidence/2026-09-15-agent-title")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let content = try await SCShareableContent.currentProcess
        let own = content.windows.first { $0.windowID == CGWindowID(window.windowNumber) }!
        let filter = SCContentFilter(desktopIndependentWindow: own)
        let capture = SCStreamConfiguration(); capture.width = 1040; capture.height = 788
        capture.minimumFrameInterval = CMTime(value: 1, timescale: 30); capture.showsCursor = true
        capture.capturesAudio = false; capture.captureMicrophone = false; capture.ignoreShadowsSingleWindow = true
        let recording = SCRecordingOutputConfiguration()
        recording.outputURL = folder.appendingPathComponent("native-interaction.mp4")
        try? FileManager.default.removeItem(at: recording.outputURL)
        let delegate = HeaderRecordingDelegate()
        let stream = SCStream(filter: filter, configuration: capture, delegate: nil)
        try stream.addRecordingOutput(SCRecordingOutput(configuration: recording, delegate: delegate))
        try await stream.startCapture()
        func screenshot(_ name: String) async throws {
            let config = SCStreamConfiguration(); config.width = Int(window.frame.width)*2; config.height = Int(window.frame.height)*2
            config.ignoreShadowsSingleWindow = true
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
            let bitmap = NSBitmapImageRep(cgImage: image)
            try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent(name + ".png"))
        }
        try await Task.sleep(for: .milliseconds(450))
        try await screenshot("light")
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        for _ in 0..<100 { if NSApp.isActive && window.isKeyWindow { break }; try await Task.sleep(for: .milliseconds(30)) }
        try expect(NSApp.isActive && window.isKeyWindow, "test window has native input focus")
        let anchor = web.convert(NSPoint(x: web.bounds.midX, y: web.bounds.midY), to: nil)
        for (dx, dy) in [(300.0,0.0),(-300.0,0.0),(0.0,100.0),(0.0,-180.0)] {
            let bounds = region()!.convert(region()!.visibleRect, to: nil)
            let point = NSPoint(x: max(bounds.minX+10, min(bounds.maxX-10, anchor.x+dx)), y: max(bounds.minY+10, min(bounds.maxY-10, anchor.y+dy)))
            mouse(point)
            try await Task.sleep(for: .milliseconds(450))
            let h = try await inspect()["header"] as! [String: Any]
            let value = h[dx == 0 ? "y" : "x"] as! Double
            try expect((dx+dy > 0 ? value : -value) > 0.3, "native pointer direction \(dx), \(dy); actual=\(value), point=\(point), region=\(bounds)")
        }
        let before = window.firstResponder
        mouse(anchor, type: .leftMouseDown); mouse(anchor, type: .leftMouseUp)
        try await Task.sleep(for: .milliseconds(130))
        let hit = try await inspect()["header"] as! [String: Any]
        try expect((hit["elapsed"] as! Double) < 0.6, "native button starts click reaction")
        try expect(window.firstResponder === before, "mascot click retains current responder")
        for _ in 0..<5 { mouse(anchor, type: .leftMouseDown); mouse(anchor, type: .leftMouseUp); try await Task.sleep(for: .milliseconds(45)) }
        try await Task.sleep(for: .milliseconds(850))
        try expect(try await inspect()["animating"] as? Bool == false, "rapid clicks settle without a queue")
        if let editor = find(LearningEditor.self, in: window.contentView) {
            editor.requestFocus()
            try expect(window.firstResponder === editor, "composer can acquire intentional focus")
            editor.setMarkedText("测试", selectedRange: NSRange(location: 2, length: 0), replacementRange: NSRange(location: NSNotFound, length: 0))
            mouse(anchor, type: .leftMouseDown); mouse(anchor, type: .leftMouseUp)
            try await Task.sleep(for: .milliseconds(200))
            try expect(window.firstResponder === editor && editor.hasMarkedText(), "click preserves Chinese marked text and editor focus")
            editor.unmarkText()
            mouse(NSPoint(x: anchor.x+300, y: anchor.y))
            try await Task.sleep(for: .milliseconds(300))
            let key = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 1, windowNumber: window.windowNumber, context: nil, characters: "a", charactersIgnoringModifiers: "a", isARepeat: false, keyCode: 0)!
            NSApp.postEvent(key, atStart: false)
            try await Task.sleep(for: .milliseconds(400))
            let quiet = try await inspect()["header"] as! [String: Any]
            try expect(abs(quiet["x"] as! Double) < 0.01, "typing returns gaze to rest")
        } else { throw HeaderQAError(message: "actual composer editor missing") }
        state.dark = true; try await Task.sleep(for: .milliseconds(500)); try await screenshot("dark")
        state.reduced = true; try await Task.sleep(for: .milliseconds(250))
        mouse(NSPoint(x: anchor.x+300, y: anchor.y)); mouse(anchor, type: .leftMouseDown); mouse(anchor, type: .leftMouseUp)
        try await Task.sleep(for: .milliseconds(450))
        let reduced = try await inspect()
        try expect(reduced["animating"] as? Bool == false && (reduced["header"] as? [String: Any])?["x"] as? Double == 0, "Reduce Motion stays static for pointer and click")
        try await screenshot("reduced")
        state.reduced = false
        window.setContentSize(NSSize(width: 520, height: 680)); try await Task.sleep(for: .milliseconds(650)); try await screenshot("narrow")
        window.miniaturize(nil); try await Task.sleep(for: .milliseconds(350))
        try expect(try await inspect()["animating"] as? Bool == false, "minimized renderer stops")
        window.deminiaturize(nil); window.makeKeyAndOrderFront(nil)
        state.shown = false; try await Task.sleep(for: .milliseconds(250))
        try expect(region() == nil, "leaving removes pointer monitor region")
        state.shown = true; let returned = try await ready()
        let restored = try await inspect(returned)
        try expect((restored["header"] as? [String: Any])?["elapsed"] as? Double == 1, "return never replays stale click")
        state.dark = false; window.setContentSize(NSSize(width: 1040,height: 760))
        try await Task.sleep(for: .milliseconds(400))
        try await stream.stopCapture()
        for _ in 0..<100 { if delegate.finished { break }; try await Task.sleep(for: .milliseconds(30)) }
        try expect(delegate.finished, "native recording finalized")
    }
}
