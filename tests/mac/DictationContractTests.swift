import AppKit
import Foundation

@main struct DictationContractTests {
    @MainActor static func main() async throws {
        _ = NSApplication.shared
        try FileManager.default.createDirectory(at: DictationFiles.root, withIntermediateDirectories: true)
        let id = UUID(), other = UUID()
        defer { DictationFiles.remove(id); DictationFiles.remove(other) }
        let denied = DictationController(permission: { false })
        denied.bind(id); denied.start()
        try await Task.sleep(for: .milliseconds(20))
        precondition(!denied.busy && denied.error != nil)
        let cancelled = DictationController(permission: { try? await Task.sleep(for: .milliseconds(30)); return true })
        cancelled.bind(id); cancelled.start(); cancelled.cancel()
        try await Task.sleep(for: .milliseconds(50))
        precondition(!cancelled.busy && !DictationFiles.exists(id))

        try Data([1,2,3]).write(to: DictationFiles.audio(id))
        var actions: [String] = []
        let controller = DictationController(transport: { action, _ in
            actions.append(action)
            if action == "clean" { throw URLError(.timedOut) }
            return .init(text: "不要改成 30 秒。")
        })
        controller.bind(id); precondition(controller.pending)
        controller.retry()
        try await Task.sleep(for: .milliseconds(80))
        precondition(controller.phase == .applying && controller.insertion?.text == "不要改成 30 秒。")
        controller.applied(saved: false)
        precondition(controller.pending && DictationFiles.exists(id))
        controller.retry()
        try await Task.sleep(for: .milliseconds(80))
        precondition(actions == ["transcribe", "clean"], "retry saved text must never charge another transcription")
        controller.applied(saved: true)
        precondition(!controller.pending && !DictationFiles.exists(id) && controller.settling)
        try await Task.sleep(for: .milliseconds(500))
        precondition(!controller.settling)

        try Data([1]).write(to: DictationFiles.audio(id))
        let late = DictationController(transport: { _, _ in
            try? await Task.sleep(for: .milliseconds(50))
            return .init(text: "late response")
        })
        late.bind(id); late.retry(); late.bind(other)
        try await Task.sleep(for: .milliseconds(100))
        precondition(late.insertion == nil && late.owner == other && DictationFiles.exists(id))
        late.bind(id); precondition(late.pending); late.cancel()
        precondition(!DictationFiles.exists(id))

        let editor = LearningEditor(frame: NSRect(x: 0, y: 0, width: 400, height: 100))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 100), styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = editor
        editor.allowsUndo = true; editor.string = "原草稿"; editor.setSelectedRange(NSRange(location: 0, length: 0))
        var applied = ""
        editor.onInsertionApplied = { applied = $0 }
        editor.queueInsertion(EditorInsertion(text: "听写文本", appendToEnd: true)); editor.applyPendingInsertion()
        precondition(editor.string == "原草稿\n听写文本" && applied == editor.string)
        precondition(editor.undoManager != nil, "native editor requires a window undo manager")
        editor.undoManager?.undo()
        precondition(editor.string == "原草稿", "dictation append must undo in one step")
        print("Dictation contracts passed: permission, cancellation, retention, cleanup fallback, retry, late response, append and undo")
    }
}
