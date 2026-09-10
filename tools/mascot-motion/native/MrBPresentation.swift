import AppKit
import SwiftUI
import WebKit

struct MrBConfiguration: Codable, Equatable {
    var kind = "thinking"
    var stage = "answer"
    var token = 0
    var dark = false
    var reduced = false
    var visible = true
    var lines: [String] = []
    var count = 1
    var title = "检索与生成的分工"
    var language = "zh"
    var framing = "presence"
    var paused = false
    var seekTime: Double? = nil
    var seekToken = 0
    var debugMesh = false
    var reviewRecording = false
    var compact = false
    var flowOutcome = "processing"
    var flowSignalToken = 0
}

/// This bridge is exclusively bundled by the isolated preview runner.
/// The daily application does not load its animations or preferences.
struct MrBMotionView: NSViewRepresentable {
    var configuration: MrBConfiguration
    var simulateFailure = false
    var onEvent: (String) -> Void = { _ in }
    var onTime: (Double) -> Void = { _ in }
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> MrBPassiveWebView {
        let settings = WKWebViewConfiguration()
        settings.websiteDataStore = .nonPersistent()
        settings.userContentController.add(context.coordinator, name: "mrB")
        let view = MrBPassiveWebView(frame: .zero, configuration: settings)
        view.setValue(false, forKey: "drawsBackground")
        view.underPageBackgroundColor = .clear
        view.navigationDelegate = context.coordinator
        context.coordinator.view = view
        context.coordinator.configuration = configuration
        context.coordinator.onEvent = onEvent
        context.coordinator.onTime = onTime
        view.visibilityChanged = { [weak c = context.coordinator] value in c?.visible = value; c?.send() }
        guard !simulateFailure, let url = Bundle.main.url(forResource: "MrBMotion", withExtension: "html"),
              let html = try? String(contentsOf: url, encoding: .utf8) else {
            DispatchQueue.main.async { onEvent("failed") }; return view
        }
        view.loadHTMLString(html, baseURL: nil)
        return view
    }
    func updateNSView(_ view: MrBPassiveWebView, context: Context) {
        context.coordinator.configuration = configuration
        context.coordinator.onEvent = onEvent
        context.coordinator.onTime = onTime
        context.coordinator.send()
    }
    static func dismantleNSView(_ view: MrBPassiveWebView, coordinator: Coordinator) {
        coordinator.visible = false; coordinator.configuration.visible = false; coordinator.send()
        view.stopLoading(); view.configuration.userContentController.removeScriptMessageHandler(forName: "mrB")
        view.navigationDelegate = nil; view.dispose(); coordinator.view = nil
    }
    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        weak var view: WKWebView?
        var configuration = MrBConfiguration()
        var onEvent: (String) -> Void = { _ in }
        var onTime: (Double) -> Void = { _ in }
        var visible = true, ready = false
        var last: Data?
        func send() {
            guard ready else { return }
            var next = configuration; next.visible = next.visible && (visible || (next.reviewRecording && ["walk_study","stamp_study","continuity_study","flow_study","review_study"].contains(next.kind)))
            guard let data = try? JSONEncoder().encode(next), data != last, let json = String(data: data, encoding: .utf8) else { return }
            last = data
            view?.evaluateJavaScript("window.mrB.setState(\(json))") { [weak self] _, error in
                if let error { NSLog("MrB bridge failed: %@",error.localizedDescription); self?.onEvent("failed") }
            }
        }
        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            if type == "ready" { ready = true; last = nil; send(); onEvent(type) }
            else if type == "failed" { ready = false; onEvent(type) }
            else if body["token"] as? Int == configuration.token {
                if type == "studyTime", let time = body["time"] as? Double { onTime(time) }
                else { onEvent(type) }
            }
        }
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { ready = false; onEvent("failed") }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { ready = false; onEvent("failed") }
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(action.request.url?.scheme == "about" ? .allow : .cancel)
        }
    }
}

final class MrBPassiveWebView: WKWebView {
    var visibilityChanged: ((Bool) -> Void)?
    private var observers: [NSObjectProtocol] = []
    override var acceptsFirstResponder: Bool { false }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow(); dispose()
        for name in [NSWindow.didChangeOcclusionStateNotification, NSApplication.didBecomeActiveNotification, NSApplication.didResignActiveNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.updateVisibility() }
            })
        }; updateVisibility()
    }
    override func viewDidHide() { super.viewDidHide(); updateVisibility() }
    override func viewDidUnhide() { super.viewDidUnhide(); updateVisibility() }
    private func updateVisibility() { visibilityChanged?(window?.isVisible == true && window?.occlusionState.contains(.visible) == true && NSApp.isActive && !isHiddenOrHasHiddenAncestor) }
    func dispose() { observers.forEach(NotificationCenter.default.removeObserver); observers = [] }
}

/// Pure eligibility state used by simulated events and its contract tests.
struct MrBSettlementGate {
    private(set) var consumed = Set<String>()
    mutating func accept(id: String, saved: Bool, foreground: Bool, modalBusy: Bool, historical: Bool = false) -> Bool {
        guard saved, !consumed.contains(id) else { return false }
        consumed.insert(id)
        return foreground && !modalBusy && !historical
    }
    static func reviewEligible(formal: Bool, saved: Bool, reason: String, count: Int) -> Bool {
        formal && saved && reason == "complete" && count > 0
    }
}
