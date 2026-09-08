import Foundation
import SwiftData

@main
struct LibraryManagementContractTests {
    enum Disk: Error { case failed }
    static func require(_ value: Bool, _ message: String = "Contract failed", file: StaticString = #filePath, line: UInt = #line) { precondition(value, message, file: file, line: line) }
    @MainActor static func main() throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        context.autosaveEnabled = false
        func card(_ title: String, _ theme: String, source: Source) -> Knowledge {
            let item = Knowledge(learningGoal: title, knowledgeType: "concept", theme: theme, contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: title, evidenceLocator: "", title: title)
            item.source = source; context.insert(item)
            let question = Question(variantIndex: 0, promptText: title, scoringSpecJSON: "{}")
            question.knowledge = item; context.insert(question)
            return item
        }
        let source = Source(rawText: "shared")
        context.insert(source)
        let a = card("A", "RAG", source: source), b = card("B", "RAG", source: source), c = card("C", "Other", source: source)
        let duplicate = card("A", "Other", source: source)
        let catalog = [a,b,c,duplicate]
        let resolved = KnowledgeLexicon.resolvedTitles(for: catalog)
        for item in catalog {
            require(resolved[item.id] == KnowledgeLexicon.keyword(for: item, among: catalog), "bulk title resolution preserves duplicate and fallback semantics")
        }
        context.delete(duplicate)
        try context.save()
        let aID = a.id, bID = b.id, cID = c.id, sourceID = source.id
        let due = a.dueAt
        let review = ReviewSession(mode: "formal", snapshotJSON: [aID,bID,cID].map(\.uuidString).joined(separator: ","))
        context.insert(review)
        let attempt = ReviewAttempt(sessionId: review.id, knowledgeId: aID, knowledgeVersion: 1, questionId: a.questions[0].id, mode: "formal")
        context.insert(attempt)
        let state = FsrsState(knowledgeId: aID, dueAt: due); context.insert(state)
        try context.save()
        var selection = KnowledgeSelection()
        selection.begin("RAG"); selection.all([aID,bID]); selection.toggle(cID, visible: [aID,bID])
        require(selection.ids == [aID,bID])
        selection.reconcile([bID]); require(selection.ids == [bID] && selection.group == "RAG")
        selection.begin("Other"); require(selection.ids.isEmpty)
        selection.reconcile([]); require(selection.group == nil)
        do { _ = try KnowledgeManagement.apply(.pause, ids: [aID,bID], context: context, save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
        require(a.lifecycle == "active" && b.lifecycle == "active", "one failed save rolls back the entire batch")
        _ = try KnowledgeManagement.apply(.pause, ids: [aID,bID], context: context)
        require(a.lifecycle == "paused" && b.lifecycle == "paused" && c.lifecycle == "active")
        require(!LearningMemory.valid([["knowledge_id":aID.uuidString, "content_version":1]], sessions: [], knowledge: [a,b,c]))
        _ = try KnowledgeManagement.apply(.restore, ids: [aID,bID], context: context)
        require(a.dueAt == due)
        do { _ = try KnowledgeManagement.impact([aID], context: context); preconditionFailure() } catch KnowledgeManagement.Failure.changed {}
        let undo = try KnowledgeManagement.apply(.trash, ids: [aID,bID], context: context)
        require(KnowledgeLexicon.previewUnavailableReason(for: a) == "恢复使用后可以试一题。", "trash cannot start a practice preview")
        try KnowledgeManagement.undoTrash(undo, context: context)
        require(a.lifecycle == "active" && b.lifecycle == "active")
        _ = try KnowledgeManagement.apply(.trash, ids: [aID,bID], context: context)
        let impact = try KnowledgeManagement.impact([aID,bID], context: context)
        require(impact.questionIDs.count == 2 && impact.attemptIDs.count == 1)
        do { try KnowledgeManagement.delete(impact, context: context, save: { throw Disk.failed }); preconditionFailure() } catch Disk.failed {}
        require(try context.fetch(FetchDescriptor<Knowledge>()).count == 3)
        require(try context.fetch(FetchDescriptor<ReviewAttempt>()).count == 1)
        _ = try KnowledgeManagement.apply(.restore, ids: [bID], context: context)
        do { try KnowledgeManagement.delete(impact, context: context); preconditionFailure() } catch KnowledgeManagement.Failure.changed {}
        _ = try KnowledgeManagement.apply(.trash, ids: [bID], context: context)
        try KnowledgeManagement.delete(try KnowledgeManagement.impact([aID,bID], context: context), context: context)
        let remaining = try context.fetch(FetchDescriptor<Knowledge>())
        require(remaining.map(\.id) == [cID])
        require(try context.fetch(FetchDescriptor<Source>()).contains { $0.id == sourceID })
        require(try context.fetch(FetchDescriptor<ReviewAttempt>()).isEmpty)
        require(try context.fetch(FetchDescriptor<FsrsState>()).isEmpty)
        require(review.snapshotJSON == cID.uuidString)
        require(try context.fetch(FetchDescriptor<Question>()).count == 1)
        // Current IDs, not the old card index, determine deletion after list changes.
        do { _ = try KnowledgeManagement.apply(.trash, ids: [aID,cID], context: context); preconditionFailure() } catch KnowledgeManagement.Failure.changed {}
        require(c.lifecycle == "active")
        _ = try KnowledgeManagement.apply(.trash, ids: [cID], context: context)
        try KnowledgeManagement.delete(try KnowledgeManagement.impact([cID], context: context), context: context)
        require(try context.fetch(FetchDescriptor<Source>()).isEmpty)
        require(try context.fetch(FetchDescriptor<ReviewSession>()).isEmpty)
        for count in [0,1,25,100] {
            require(KnowledgeLocator.index(y: -50, height: 400, count: count) == 0)
            require(KnowledgeLocator.index(y: 500, height: 400, count: count) == max(0,count-1))
            for index in 0..<count {
                let y = KnowledgeLocator.y(index: index, height: 400, count: count)
                require(KnowledgeLocator.index(y: y, height: 400, count: count) == index)
            }
        }
        var navigation = KnowledgeDeckNavigation<Int>()
        navigation.select(0, ids: Array(0..<100)); navigation.navigate(1)
        let stale = navigation.generation
        for y: CGFloat in stride(from: 400, through: 0, by: -4) {
            navigation.select(KnowledgeLocator.index(y: y, height: 400, count: 100), ids: Array(0..<100))
        }
        navigation.finish(generation: stale)
        require(navigation.selectedID == 0 && navigation.phase == .idle)
        print("PASS: scoped knowledge selection, atomic lifecycle rollback, recycle/undo, permanent-delete revalidation, shared source retention, question/review cleanup, continuous locator and stale motion")
    }
}
