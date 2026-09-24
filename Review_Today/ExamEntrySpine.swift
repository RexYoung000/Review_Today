import SwiftUI
import WebKit

/// Isolated Spine renderer for the checklist. Its canvas contains no mascot
/// skeleton, so a stale frame can never flash as a dark circle.
struct ExamEntrySpine: NSViewRepresentable {
    var playing: Bool
    var dark: Bool
    var onReady: (Bool) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onReady: onReady) }

    func makeNSView(context: Context) -> WKWebView {
        let settings = WKWebViewConfiguration()
        settings.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: settings)
        view.setValue(false, forKey: "drawsBackground")
        view.underPageBackgroundColor = .clear
        view.configuration.userContentController.add(context.coordinator, name: "examMotion")
        view.navigationDelegate = context.coordinator
        context.coordinator.view = view
        context.coordinator.update(playing: playing, dark: dark)
        if let url = Bundle.main.url(forResource: "ExamEntrySpine", withExtension: "html"),
           let html = try? String(contentsOf: url, encoding: .utf8) {
            view.loadHTMLString(html, baseURL: nil)
        } else {
            context.coordinator.onReady(false)
        }
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        context.coordinator.onReady = onReady
        context.coordinator.update(playing: playing, dark: dark)
    }

    static func dismantleNSView(_ view: WKWebView, coordinator: Coordinator) {
        coordinator.onReady = { _ in }
        coordinator.ready = false
        view.stopLoading()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "examMotion")
        view.navigationDelegate = nil
        coordinator.view = nil
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        weak var view: WKWebView?
        var onReady: (Bool) -> Void
        var ready = false
        private var playing = false
        private var dark = false
        private var lastSent: String?

        init(onReady: @escaping (Bool) -> Void) { self.onReady = onReady }

        func update(playing: Bool, dark: Bool) {
            self.playing = playing
            self.dark = dark
            send()
        }

        private func send() {
            guard ready, let view else { return }
            let state = "{\"playing\":\(playing),\"dark\":\(dark)}"
            guard state != lastSent else { return }
            lastSent = state
            view.evaluateJavaScript("window.examMotion.setState(\(state))")
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let value = message.body as? [String: Any], let type = value["type"] as? String else { return }
            ready = type == "ready"
            lastSent = nil
            onReady(ready)
            if ready { send() }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            ready = false
            onReady(false)
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            ready = false
            onReady(false)
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(navigationAction.request.url?.scheme == "about" ? .allow : .cancel)
        }
    }
}
