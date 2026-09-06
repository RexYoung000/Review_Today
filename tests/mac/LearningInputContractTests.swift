// Run as an isolated AppKit/SwiftData test executable, not against user data.
import AppKit
import SwiftData
import SwiftUI

@main
struct LearningInputContractTests {
    @MainActor static func main() throws {
        _ = NSApplication.shared
        precondition(AgentQuickStart.allCases.count == 12, "quick starts must include the twelve approved local learning scenarios")
        checkQuickStartsAndSidebar()
        checkTemplateInput()
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
        precondition(Array(one.displayTopicTags.prefix(1)) == ["RAG"] && one.automaticTopicTags.count == 2,
                     "showing one tag must not delete hidden tags")
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
        print("PASS: 12 scenarios, 6-card refresh, protected prefill/IME/undo, sidebar preference, native input, atomic first-send failure/retry, no empty Sessions, independent drafts/preferences, tags, partial persistence, activity")
    }

    @MainActor private static func checkQuickStartsAndSidebar() {
        precondition(AgentQuickStart.initial == [.concept, .material, .organize, .explore, .compare, .interview])
        var group = AgentQuickStart.initial
        for _ in 0..<100 {
            let next = AgentQuickStart.refreshed(after: group)
            precondition(next.count == 6 && Set(next).count == 6 && Set(next) != Set(group))
            precondition(next.allSatisfy { !$0.title.isEmpty && !$0.detail.isEmpty && !$0.symbol.isEmpty && !$0.prompt.isEmpty })
            group = next
        }
        var prefill = QuickStartPrefill()
        let first = AgentQuickStart.concept.prompt
        let second = AgentQuickStart.material.prompt
        precondition(prefill.apply(id: "concept", prompt: first, to: "") == first)
        precondition(prefill.apply(id: "concept", prompt: first, to: first) == nil)
        precondition(prefill.apply(id: "material", prompt: second, to: first) == second, "untouched template is replaceable")
        prefill.userEdited()
        let edited = second + "RAG 中文材料"
        let appended = edited + "\n" + first
        precondition(prefill.apply(id: "concept", prompt: first, to: edited) == appended)
        precondition(prefill.apply(id: "concept", prompt: first, to: appended) == nil)
        var restored = QuickStartPrefill()
        precondition(restored.apply(id: "material", prompt: second, to: first) == first + "\n" + second,
                     "unproven template provenance after restore is protected")
        var sidebar = SidebarVisibilityPolicy()
        precondition(sidebar.expanded)
        let laterClick = NSEvent.mouseEvent(with: .leftMouseDown, location: .zero, modifierFlags: [],
                                            timestamp: 2, windowNumber: 0, context: nil,
                                            eventNumber: 1, clickCount: 1, pressure: 1)!
        precondition(!FocusReturnPolicy.allows(since: 1, current: laterClick), "menu dismissal cannot steal a newer pointer focus")
        precondition(FocusReturnPolicy.allows(since: 2, current: laterClick))
        sidebar.resize(narrow: true)
        precondition(!sidebar.expanded && sidebar.preferredExpanded, "auto collapse isn't a preference change")
        sidebar.resize(narrow: false)
        precondition(sidebar.expanded)
        sidebar.choose(expanded: false)
        sidebar.resize(narrow: true); sidebar.resize(narrow: false)
        precondition(!sidebar.expanded && !sidebar.preferredExpanded)
        sidebar.resize(narrow: true); sidebar.choose(expanded: true)
        precondition(sidebar.expanded, "a narrow window can explicitly open the same sidebar")
        sidebar.resize(narrow: false)
        precondition(sidebar.expanded)
    }

    @MainActor private static func checkTemplateInput() {
        // A real NSTextView undo manager, but no window is shown and no user data is loaded.
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 160),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let editor = LearningEditor(frame: NSRect(x: 0, y: 0, width: 460, height: 160))
        window.contentView = editor
        editor.allowsUndo = true; editor.isRichText = false
        var sends = 0
        editor.onSubmit = { sends += 1 }
        func choose(_ start: AgentQuickStart) {
            editor.queueInsertion(EditorInsertion(text: start.prompt, templateID: start.id))
            editor.applyPendingInsertion()
        }
        choose(.concept)
        precondition(editor.string == AgentQuickStart.concept.prompt)
        choose(.material)
        precondition(editor.string == AgentQuickStart.material.prompt)
        choose(.material)
        precondition(editor.string == AgentQuickStart.material.prompt)
        editor.insertText("中文 + English 资料", replacementRange: NSRange(location: (editor.string as NSString).length, length: 0))
        let original = editor.string
        editor.setSelectedRange(NSRange(location: 0, length: 4))
        editor.breakUndoCoalescing()
        editor.undoManager?.removeAllActions()
        editor.undoManager?.beginUndoGrouping()
        choose(.organize)
        editor.undoManager?.endUndoGrouping()
        precondition(editor.string == original + "\n" + AgentQuickStart.organize.prompt, "a template appends instead of replacing selected user text")
        precondition(editor.undoManager?.canUndo == true, "native undo must be available")
        editor.undoManager?.undo()
        precondition(editor.string == original, "one undo restores the complete edited draft")
        editor.string = ""; editor.resetPrefill()
        editor.queueInsertion(EditorInsertion(text: AgentQuickStart.concept.prompt, templateID: "concept"))
        editor.queueInsertion(EditorInsertion(text: AgentQuickStart.explore.prompt, templateID: "explore"))
        editor.applyPendingInsertion()
        precondition(editor.string == AgentQuickStart.explore.prompt, "rapid pending selection uses the latest card")
        editor.string = "已有内容："; editor.resetPrefill()
        editor.setSelectedRange(NSRange(location: (editor.string as NSString).length, length: 0))
        editor.setMarkedText("zhongwen", selectedRange: NSRange(location: 8, length: 0), replacementRange: NSRange(location: NSNotFound, length: 0))
        let composing = editor.string
        choose(.compare)
        precondition(editor.hasMarkedText() && editor.string == composing, "cards cannot disturb IME composition")
        editor.insertText("中文", replacementRange: editor.markedRange())
        editor.unmarkText()
        editor.applyPendingInsertion()
        precondition(editor.string == "已有内容：中文\n" + AgentQuickStart.compare.prompt)
        editor.queueInsertion(EditorInsertion(text: "旧会话模板", templateID: "old"))
        editor.resetPrefill(); editor.string = "另一会话的草稿"
        editor.applyPendingInsertion()
        precondition(editor.string == "另一会话的草稿", "session switch cancels pending insertions")
        precondition(sends == 0, "no quick-start operation can submit")
        window.close()
    }
}
