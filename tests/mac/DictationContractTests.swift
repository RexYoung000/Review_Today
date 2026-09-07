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
        precondition(!controller.busy && controller.notice == "已保留原始转写，可直接编辑")
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

        // Old caches have no reason field; new/unknown reason values are additive.
        let old = try JSONDecoder().decode(DictationResult.self, from: Data(#"{"text":"旧草稿","raw_text":"旧草稿","cleaned":false}"#.utf8))
        precondition(old.cleanup_reason == nil)
        let future = try JSONDecoder().decode(DictationResult.self, from: Data(#"{"text":"原文","cleaned":false,"cleanup_reason":"future_reason"}"#.utf8))
        precondition(future.cleaned == false)
        try JSONEncoder().encode(old).write(to: DictationFiles.result(id))
        let cached = DictationController(transport: { _, _ in preconditionFailure("cached cleanup must not call a provider") })
        cached.bind(id); cached.retry()
        try await Task.sleep(for: .milliseconds(30))
        precondition(cached.insertion?.text == "旧草稿")
        cached.applied(saved: true)
        precondition(cached.notice == "已保留原始转写，可直接编辑" && !cached.busy)
        cached.bind(other)
        precondition(cached.notice == nil)

        var tick = 0.0
        var successfulCalls = 0
        try Data([1]).write(to: DictationFiles.audio(id))
        let success = DictationController(transport: { action, _ in
            successfulCalls += 1; tick += action == "transcribe" ? 0.4 : 0.7
            return action == "transcribe" ? .init(text: "第一保留草稿第二手动发送") :
                .init(text: "1. 保留草稿\n2. 手动发送", raw_text: "第一保留草稿第二手动发送", cleaned: true)
        }, clock: { tick })
        success.bind(id); success.retry(); success.retry() // duplicate click
        try await Task.sleep(for: .milliseconds(40))
        precondition(successfulCalls == 2 && success.phase == .applying)
        precondition(success.mascotPhase == .idle && success.notice == nil)
        tick += 0.03; success.applied(saved: true)
        precondition(!success.busy && success.settling && success.notice == "已添加到草稿")
        precondition(abs(success.timings[.transcription]! - 0.4) < 0.001)
        precondition(abs(success.timings[.cleanup]! - 0.7) < 0.001)
        precondition(abs(success.timings[.draftSave]! - 0.03) < 0.001)
        precondition(success.timings[.recordingStart] == nil, "retry does not fabricate recording startup timing")
        for (phase, expected) in [(DictationController.Phase.permission, MascotPhase.idle), (.recording, .listening), (.transcribing, .thinking), (.cleaning, .thinking)] {
            success.phase = phase; precondition(success.mascotPhase == expected)
        }
        success.phase = .idle; success.cancel()
        precondition(success.notice == nil)

        let editor = LearningEditor(frame: NSRect(x: 0, y: 0, width: 400, height: 100))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 100), styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = editor
        editor.allowsUndo = true; editor.string = "原草稿"; editor.setSelectedRange(NSRange(location: 0, length: 0))
        var applied = ""
        editor.onInsertionApplied = { applied = $0 }
        editor.isEditable = false
        editor.queueInsertion(EditorInsertion(text: "1. 保留草稿\n2. 手动发送", appendToEnd: true)); editor.applyPendingInsertion()
        precondition(editor.string == "原草稿\n1. 保留草稿\n2. 手动发送" && applied == editor.string)
        precondition(!editor.isEditable, "insertion must preserve the processing lock")
        precondition(editor.undoManager != nil, "native editor requires a window undo manager")
        // Saving the draft clears controller.busy; SwiftUI then unlocks this editor.
        editor.isEditable = true
        editor.undoManager?.undo()
        precondition(editor.string == "原草稿", "dictation append must undo in one step")
        print("Dictation contracts passed: permission, cancellation, retention, fallback notices, cached compatibility, timing, duplicate callbacks, append and undo")
    }
}
