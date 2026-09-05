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

        let schema = Schema([AgentSession.self, AgentMessage.self, AgentRun.self, SessionEventRecord.self, AgentRunControl.self, AppSettings.self])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        let landing = try AgentComposerStore.prepare(context)
        let preparedID = landing.agentDraftID
        landing.agentDraftText = "RAG 草稿"
        landing.agentDraftMode = "source_learning"
        landing.agentDraftThinking = "deep"
        landing.lastThinkingStrength = "deep"
        try context.save()
        let sameLanding = try AgentComposerStore.prepare(context)
        precondition(sameLanding.agentDraftID == preparedID && sameLanding.agentDraftText == "RAG 草稿")
        let noSessions = try context.fetch(FetchDescriptor<AgentSession>())
        precondition(noSessions.isEmpty, "opening start page must not create a Session")
        enum SimulatedFailure: Error { case disk }
        do {
            _ = try AgentComposerStore.sendFirst("RAG 草稿", context: context, save: { throw SimulatedFailure.disk })
            preconditionFailure("save failure must propagate")
        } catch SimulatedFailure.disk {}
        let afterFailedSave = try context.fetch(FetchDescriptor<AgentSession>())
        let afterFailedMessage = try context.fetch(FetchDescriptor<AgentMessage>())
        precondition(afterFailedSave.isEmpty && afterFailedMessage.isEmpty)
        let recoveredDraft = try AgentComposerStore.prepare(context)
        precondition(recoveredDraft.agentDraftText == "RAG 草稿" && recoveredDraft.agentDraftID == preparedID)
        let (created, firstMessage) = try AgentComposerStore.sendFirst("RAG 草稿", context: context)
        precondition(created.id == preparedID && created.modePreset == "source_learning" && created.thinkingStrength == "deep")
        precondition(firstMessage.sessionID == created.id && firstMessage.clientMessageID == firstMessage.id)
        let nextDraft = try AgentComposerStore.prepare(context)
        precondition(nextDraft.agentDraftID != preparedID && nextDraft.agentDraftText.isEmpty && nextDraft.agentDraftMode == "auto" && nextDraft.agentDraftThinking == "deep")
        let one = AgentSession(title: "A"), two = AgentSession(title: "B")
        one.composerDraft = "A 的独立草稿"
        two.composerDraft = "B 的独立草稿"
        one.setAutomaticTopicTags(["RAG", "面试", "RAG"])
        precondition(one.displayTopicTags == ["RAG", "面试"])
        one.setManualTopicTags(["人工标签"])
        one.setAutomaticTopicTags(["自动更新"])
        precondition(one.displayTopicTags == ["人工标签"], "manual tags must win")
        one.restoreAutomaticTopicTags()
        precondition(one.displayTopicTags == ["自动更新"])
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
        let persisted = try ModelContext(container).fetch(FetchDescriptor<AgentMessage>()).first { $0.id == partial.id }!
        precondition(persisted.responseState == "interrupted" && persisted.responseRevision == 2 && persisted.responseChunkSeq == 4)
        let calendar = Calendar(identifier: .gregorian)
        let today = calendar.startOfDay(for: .now)
        let yesterday = calendar.date(byAdding: .day, value: -1, to: today)!
        let older = calendar.date(byAdding: .day, value: -2, to: today)!
        precondition(LearningActivityCalendar.uniqueDays([today, today.addingTimeInterval(200), yesterday]).count == 2)
        precondition(LearningActivityCalendar.currentStreak([yesterday, older], today: today, calendar: calendar) == 2)
        precondition(LearningActivityCalendar.longestStreak([today, yesterday, older], calendar: calendar) == 3)
        precondition([0, 1, 2, 3, 4, 5].map(LearningActivityCalendar.intensity) == [0, 1, 2, 3, 3, 4])
        print("PASS: native input, atomic first-send failure/retry, no empty Sessions, independent drafts/preferences, tags, partial persistence, activity")
    }
}
