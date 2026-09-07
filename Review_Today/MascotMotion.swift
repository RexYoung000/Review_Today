import AppKit
import SwiftUI
import WebKit

enum MascotSurface: String, Codable { case recall, voice }
enum MascotPhase: String, Codable, CaseIterable {
    case listening, thinking, speaking, idle
    var title: String {
        switch self { case .listening: "聆听"; case .thinking: "思考"; case .speaking: "回答"; case .idle: "停止" }
    }
}

/// The audio input is reserved for a future real voice controller. Production
/// currently binds only recall to AgentRun; text streaming is never speech.
struct MascotMotionConfiguration: Codable, Equatable {
    var surface: MascotSurface = .recall
    var mode: MascotPhase = .idle
    var level: Double = 0
    var reduced = false
    var dark = false
    var visible = true
    var rate: Double = 1
    var material = "current"
    var palette: MascotMaterialPalette? = nil

    static func phase(runStatus: String, started: Bool) -> MascotPhase {
        started && ["running", "adjusting"].contains(runStatus) ? .thinking : .idle
    }
}

struct MascotMotion: View {
    var surface: MascotSurface = .recall
    var phase: MascotPhase
    var level: Double = 0
    var reduced = false
    var rate: Double = 1
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.brandMaterialTrial) private var materialTrial
    @Environment(\.brandReduceMotion) private var systemReduced
    @State private var ready = false
    var body: some View {
        ZStack {
            if !ready { Circle().fill(materialTrial ? Color(white: 0.18) : Color(red: 0.08, green: 0.39, blue: 0.37)).frame(width: 10, height: 10) }
            MascotWebSurface(configuration: .init(surface: surface, mode: phase, level: level,
                                                 reduced: reduced || systemReduced, dark: colorScheme == .dark, rate: rate,
                                                 material: materialTrial ? "graphite" : "current",
                                                 palette: .theme(dark: colorScheme == .dark))) { ready = $0 }
                .opacity(ready ? 1 : 0)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true) // the adjacent native status owns semantics
    }
}

struct MascotWebSurface: NSViewRepresentable {
    var configuration: MascotMotionConfiguration
    var onReady: (Bool) -> Void = { _ in }

    func makeCoordinator() -> Coordinator { Coordinator(onReady: onReady) }
    func makeNSView(context: Context) -> PassiveMascotWebView {
        let settings = WKWebViewConfiguration()
        settings.websiteDataStore = .nonPersistent()
        settings.userContentController.add(context.coordinator, name: "mascot")
        let view = PassiveMascotWebView(frame: .zero, configuration: settings)
        view.setValue(false, forKey: "drawsBackground")
        view.underPageBackgroundColor = .clear
        view.navigationDelegate = context.coordinator
        context.coordinator.webView = view
        view.visibilityChanged = { [weak coordinator = context.coordinator] visible in coordinator?.setVisible(visible) }
        context.coordinator.configuration = configuration
        if let url = Bundle.main.url(forResource: "MascotMotion", withExtension: "html"),
           let html = try? String(contentsOf: url, encoding: .utf8) {
            view.loadHTMLString(html, baseURL: nil)
        } else { context.coordinator.onReady(false) }
        return view
    }
    func updateNSView(_ view: PassiveMascotWebView, context: Context) {
        context.coordinator.onReady = onReady
        context.coordinator.configuration = configuration
        context.coordinator.send()
    }
    static func dismantleNSView(_ view: PassiveMascotWebView, coordinator: Coordinator) {
        coordinator.configuration.visible = false
        coordinator.send()
        view.stopLoading()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "mascot")
        view.navigationDelegate = nil
        view.dispose()
        coordinator.webView = nil
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        weak var webView: WKWebView?
        var configuration = MascotMotionConfiguration()
        var onReady: (Bool) -> Void
        var ready = false
        private var visible = true
        private var lastSent: Data?
        init(onReady: @escaping (Bool) -> Void) { self.onReady = onReady }
        func setVisible(_ value: Bool) { visible = value; send() }
        func send() {
            guard ready, let webView else { return }
            var value = configuration
            value.level = value.level.isFinite ? min(1, max(0, value.level)) : 0
            value.visible = value.visible && visible
            guard let data = try? JSONEncoder().encode(value), data != lastSent,
                  let json = String(data: data, encoding: .utf8) else { return }
            lastSent = data
            webView.evaluateJavaScript("window.mascotMotion.setState(\(json))")
        }
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let value = message.body as? [String: String] else { return }
            ready = value["type"] == "ready"
            lastSent = nil
            onReady(ready)
            if ready { send() }
        }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { ready = false; onReady(false) }
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { ready = false; onReady(false) }
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(navigationAction.request.url?.scheme == "about" ? .allow : .cancel)
        }
    }
}

/// Decorative content must not take focus, intercept clicks, or keep animating
/// in a hidden/minimized/background window. No microphone or network capability.
final class PassiveMascotWebView: WKWebView {
    var visibilityChanged: ((Bool) -> Void)?
    private var observers: [NSObjectProtocol] = []
    override var acceptsFirstResponder: Bool { false }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        dispose()
        guard window != nil else { visibilityChanged?(false); return }
        for name in [NSWindow.didChangeOcclusionStateNotification, NSWindow.didMiniaturizeNotification,
                     NSWindow.didDeminiaturizeNotification, NSApplication.didBecomeActiveNotification,
                     NSApplication.didResignActiveNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.updateVisibility() }
            })
        }
        updateVisibility()
    }
    override func viewDidHide() { super.viewDidHide(); updateVisibility() }
    override func viewDidUnhide() { super.viewDidUnhide(); updateVisibility() }
    private func updateVisibility() {
        visibilityChanged?(window?.isVisible == true && window?.occlusionState.contains(.visible) == true && NSApp.isActive && !isHiddenOrHasHiddenAncestor)
    }
    func dispose() { observers.forEach(NotificationCenter.default.removeObserver); observers.removeAll() }
}

/// Keep the same renderer alive for its short return instead of unmounting it
/// on the first completed/failed/cancelled status update.
struct RunMascotIndicator: View {
    var active: Bool
    var reduced: Bool
    var color: Color = .secondary
    @State private var showing = false
    var body: some View {
        Group {
            if showing || active {
                MascotMotion(phase: active ? .thinking : .idle, reduced: reduced)
            } else { Circle().fill(color).frame(width: 6, height: 6) }
        }
        .frame(width: 32, height: 28)
        .task(id: active) {
            if active { showing = true }
            else {
                if !reduced { try? await Task.sleep(for: .milliseconds(300)) }
                guard !Task.isCancelled else { return }
                showing = false
            }
        }
    }
}
