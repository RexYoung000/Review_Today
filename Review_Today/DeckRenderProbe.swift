import AppKit
import SwiftUI

/// Opt-in debug probe: input-handler entry to AppKit draw on the selected card.
/// This measures native rendering work, not the display's physical scanout.
@MainActor
enum DeckRenderMetrics {
#if DEBUG
    static var enabled: Bool { ProcessInfo.processInfo.environment["REVIEW_TODAY_DECK_METRICS"] != nil }
    private static var pending: (id: AnyHashable, start: TimeInterval)?
    static func begin<ID: Hashable>(_ id: ID) { if enabled { pending = (AnyHashable(id), ProcessInfo.processInfo.systemUptime) } }
    static func painted(_ id: AnyHashable) {
        guard let pending, pending.id == id else { return }
        self.pending = nil
        let ms = (ProcessInfo.processInfo.systemUptime - pending.start) * 1000
        guard let path = ProcessInfo.processInfo.environment["REVIEW_TODAY_DECK_METRICS"], path.hasPrefix("/tmp/review-today-") else { return }
        let data = Data(String(format: "%.3f\n", ms).utf8)
        if !FileManager.default.fileExists(atPath: path) { FileManager.default.createFile(atPath: path, contents: nil) }
        guard let file = FileHandle(forWritingAtPath: path) else { return }
        defer { try? file.close() }
        _ = try? file.seekToEnd(); try? file.write(contentsOf: data)
    }
#else
    static let enabled = false
    static func begin<ID: Hashable>(_ id: ID) {}
    static func painted(_ id: AnyHashable) {}
#endif
}

struct DeckRenderProbe: NSViewRepresentable {
    let id: AnyHashable
    func makeNSView(context: Context) -> ProbeView { let view = ProbeView(); view.identity = id; return view }
    func updateNSView(_ view: ProbeView, context: Context) { view.identity = id; view.needsDisplay = true }
    final class ProbeView: NSView {
        var identity: AnyHashable = 0
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func draw(_ dirtyRect: NSRect) { DeckRenderMetrics.painted(identity) }
    }
}
