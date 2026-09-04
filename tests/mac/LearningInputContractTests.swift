// Run as an isolated AppKit/SwiftData test executable, not against user data.
import AppKit
import SwiftData
import SwiftUI

@main
struct LearningInputContractTests {
    @MainActor static func main() throws {
        _ = NSApplication.shared
        let editor = LearningEditor(frame: NSRect(x: 0, y: 0, width: 460, height: 160))
        editor.allowsUndo = true
        editor.isRichText = false
        var sends = 0
        editor.onSubmit = { sends += 1; editor.string = "" }

        func key(_ modifiers: NSEvent.ModifierFlags = [], repeating: Bool = false) -> NSEvent {
            NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: modifiers, timestamp: 0,
                             windowNumber: 0, context: nil, characters: "\r", charactersIgnoringModifiers: "\r",
                             isARepeat: repeating, keyCode: 36)!
        }
        editor.string = "问题 RAG 中文"
        editor.keyDown(with: key())
        precondition(sends == 1 && editor.string.isEmpty, "Return sends once")
        editor.keyDown(with: key())
        precondition(sends == 1, "empty Return must not submit")
        editor.string = "   \n "
        editor.keyDown(with: key(.command))
        precondition(sends == 1, "blank Cmd Return must not submit")
        editor.string = "新问题"
        editor.keyDown(with: key(repeating: true))
        precondition(sends == 1, "key repeat cannot duplicate submission")
        editor.keyDown(with: key(.command))
        precondition(sends == 2, "Cmd Return sends")
        editor.string = "first"
        editor.setSelectedRange(NSRange(location: 5, length: 0))
        editor.keyDown(with: key(.shift))
        precondition(sends == 2 && editor.string == "first\n", "Shift Return inserts a newline")
        editor.string = ""
        editor.setSelectedRange(NSRange(location: 0, length: 0))
        editor.setMarkedText("nihao", selectedRange: NSRange(location: 5, length: 0), replacementRange: NSRange(location: NSNotFound, length: 0))
        precondition(editor.hasMarkedText(), "marked text must exist")
        editor.keyDown(with: key())
        precondition(sends == 2, "composition Return never submits")
        editor.unmarkText()
        // A failed save leaves native contents intact; the submit callback owns clear.
        editor.string = "保存失败仍保留"
        editor.onSubmit = { sends += 1 }
        editor.keyDown(with: key())
        precondition(editor.string == "保存失败仍保留")

        let schema = Schema([AgentSession.self, AgentMessage.self, AgentRun.self, SessionEventRecord.self, AgentRunControl.self])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let one = AgentSession(title: "A"), two = AgentSession(title: "B")
        one.composerDraft = "A 的独立草稿"
        two.composerDraft = "B 的独立草稿"
        context.insert(one); context.insert(two)
        try context.save()
        let freshContext = ModelContext(container)
        let saved = try freshContext.fetch(FetchDescriptor<AgentSession>())
        precondition(saved.first(where: { $0.id == one.id })?.composerDraft == "A 的独立草稿")
        precondition(saved.first(where: { $0.id == two.id })?.composerDraft == "B 的独立草稿")
        precondition(AgentSession().composerDraft.isEmpty)
        let partial = AgentMessage(sessionID: one.id, role: "assistant", content: "未完成 **Markdown")
        partial.responseState = "interrupted"; partial.responseRevision = 2; partial.responseChunkSeq = 4
        context.insert(partial)
        try context.save()
        let persisted = try ModelContext(container).fetch(FetchDescriptor<AgentMessage>()).first!
        precondition(persisted.responseState == "interrupted" && persisted.responseRevision == 2 && persisted.responseChunkSeq == 4)
        print("PASS: Return/Shift Return/Cmd Return, blank/repeat guard, marked-text guard, failed-send retention, isolated Session drafts, partial response persistence")
    }
}
