import SwiftData
import SwiftUI

struct KnowledgeSelection {
    private(set) var group: String?
    private(set) var ids = Set<UUID>()
    mutating func begin(_ group: String) { self.group = group; ids = [] }
    mutating func finish() { group = nil; ids = [] }
    mutating func toggle(_ id: UUID, visible: Set<UUID>) {
        guard group != nil, visible.contains(id) else { return }
        ids.formIntersection(visible)
        if !ids.insert(id).inserted { ids.remove(id) }
    }
    mutating func all(_ visible: Set<UUID>) { ids = !visible.isEmpty && ids == visible ? [] : visible }
    mutating func reconcile(_ visible: Set<UUID>) { ids.formIntersection(visible); if visible.isEmpty { finish() } }
}

enum KnowledgeAction: String, CaseIterable, Identifiable {
    case pause, restore, trash, delete
    var id: String { rawValue }
    var title: String {
        switch self { case .pause: "暂停"; case .restore: "恢复使用"; case .trash: "移到回收站"; case .delete: "永久删除" }
    }
    var destructive: Bool { self == .trash || self == .delete }
    var symbol: String {
        switch self { case .pause: "pause"; case .restore: "arrow.uturn.backward"; case .trash: "trash"; case .delete: "trash.slash" }
    }
    static func available(_ lifecycle: String) -> [Self] {
        switch lifecycle { case "active": [.pause, .trash]; case "paused": [.restore, .trash]; case "soft_deleted": [.restore, .delete]; default: [] }
    }
    var destination: String { switch self { case .pause: "paused"; case .restore: "active"; default: "soft_deleted" } }
}

struct KnowledgeDeletionImpact: Identifiable, Equatable {
    let ids: Set<UUID>
    let titles: [String]
    let questionIDs: Set<UUID>
    let attemptIDs: Set<UUID>
    var id: String { ids.map(\.uuidString).sorted().joined() }
}

@MainActor
enum KnowledgeManagement {
    enum Failure: LocalizedError {
        case changed
        var errorDescription: String? { "知识或选择范围已变化，请关闭后重新选择。" }
    }
    static func targets(_ ids: Set<UUID>, context: ModelContext) throws -> [Knowledge] {
        let items = try context.fetch(FetchDescriptor<Knowledge>()).filter { ids.contains($0.id) }
        guard !ids.isEmpty, items.count == ids.count else { throw Failure.changed }
        return items
    }
    /// Lifecycle, invalidated dependencies and the durable stop control share one save.
    @discardableResult
    static func apply(_ action: KnowledgeAction, ids: Set<UUID>, context: ModelContext, save: (() throws -> Void)? = nil) throws -> [UUID: String] {
        let items = try targets(ids, context: context)
        guard action != .delete, items.allSatisfy({ KnowledgeAction.available($0.lifecycle).contains(action) }) else { throw Failure.changed }
        let original = Dictionary(uniqueKeysWithValues: items.map { ($0.id, $0.lifecycle) })
        let restoreDependencies = try dependencySnapshot(context)
        do {
            for item in items { item.lifecycle = action.destination }
            try LearningMemory.fenceInvalidReferences(context: context)
            if let save { try save() } else { try context.save() }
            ConversationSync.wake()
            return original
        } catch {
            context.processPendingChanges(); context.rollback()
            for item in items { item.lifecycle = original[item.id]! }
            restoreDependencies()
            throw error
        }
    }
    static func undoTrash(_ original: [UUID: String], context: ModelContext) throws {
        let items = try targets(Set(original.keys), context: context)
        guard items.allSatisfy({ $0.lifecycle == "soft_deleted" }) else { throw Failure.changed }
        do {
            for item in items { item.lifecycle = original[item.id]! }
            try context.save(); ConversationSync.wake()
        } catch { context.processPendingChanges(); context.rollback(); for item in items { item.lifecycle = "soft_deleted" }; throw error }
    }
    static func impact(_ ids: Set<UUID>, context: ModelContext) throws -> KnowledgeDeletionImpact {
        let items = try targets(ids, context: context)
        guard items.allSatisfy({ $0.lifecycle == "soft_deleted" }) else { throw Failure.changed }
        let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>()).filter { ids.contains($0.knowledgeId) }
        return KnowledgeDeletionImpact(ids: ids, titles: items.map { $0.title.isEmpty ? $0.learningGoal : $0.title }.sorted(),
                                       questionIDs: Set(items.flatMap(\.questions).map(\.id)), attemptIDs: Set(attempts.map(\.attemptId)))
    }
    private static func dependencySnapshot(_ context: ModelContext) throws -> () -> Void {
        let sessions = try context.fetch(FetchDescriptor<AgentSession>()).map { ($0, $0.summaryText, $0.pendingOperationJSON) }
        let runs = try context.fetch(FetchDescriptor<AgentRun>()).map { ($0, $0.status, $0.elapsedMS, $0.startedAt, $0.userSummary, $0.memoryInvalidationRevision) }
        let messages = try context.fetch(FetchDescriptor<AgentMessage>()).map { ($0, $0.responseState) }
        return {
            for (model, summary, pending) in sessions { model.summaryText = summary; model.pendingOperationJSON = pending }
            for (model, status, elapsed, started, summary, invalidation) in runs {
                model.status = status; model.elapsedMS = elapsed; model.startedAt = started; model.userSummary = summary; model.memoryInvalidationRevision = invalidation
            }
            for (model, state) in messages { model.responseState = state }
        }
    }
    static func delete(_ approved: KnowledgeDeletionImpact, context: ModelContext, save: (() throws -> Void)? = nil) throws {
        guard try impact(approved.ids, context: context) == approved else { throw Failure.changed }
        let restoreDependencies = try dependencySnapshot(context)
        let reviewSnapshots = try context.fetch(FetchDescriptor<ReviewSession>()).map { ($0, $0.snapshotJSON) }
        do {
            let items = try targets(approved.ids, context: context)
            let sourceIDs = Set(items.compactMap { $0.source?.id })
            let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
            for attempt in attempts where approved.ids.contains(attempt.knowledgeId) { context.delete(attempt) }
            for review in try context.fetch(FetchDescriptor<ReviewSession>()) {
                let original = review.snapshotJSON.split(separator: ",").map(String.init)
                let retained = original.filter { UUID(uuidString: $0).map { !approved.ids.contains($0) } ?? true }
                let touched = retained != original || attempts.contains { $0.sessionId == review.id && approved.ids.contains($0.knowledgeId) }
                guard touched else { continue }
                if retained.isEmpty && !attempts.contains(where: { $0.sessionId == review.id && !approved.ids.contains($0.knowledgeId) }) { context.delete(review) }
                else { review.snapshotJSON = retained.joined(separator: ",") }
            }
            for state in try context.fetch(FetchDescriptor<FsrsState>()) where approved.ids.contains(state.knowledgeId) { context.delete(state) }
            for reference in try context.fetch(FetchDescriptor<KnowledgeReference>()) where approved.ids.contains(reference.knowledgeID) { context.delete(reference) }
            for item in items { context.delete(item) }
            try LearningMemory.fenceInvalidReferences(context: context)
            let referencedSources = Set(try context.fetch(FetchDescriptor<LearningTask>()).compactMap(\.sourceID))
            let referencedURLs = Set(try context.fetch(FetchDescriptor<SourceReference>()).map(\.url))
            let surviving = try context.fetch(FetchDescriptor<Knowledge>()).filter { !approved.ids.contains($0.id) }
            for source in try context.fetch(FetchDescriptor<Source>()) where sourceIDs.contains(source.id) {
                if !referencedSources.contains(source.id) && source.url.map(referencedURLs.contains) != true && source.tasks.isEmpty && !surviving.contains(where: { $0.source?.id == source.id }) { context.delete(source) }
            }
            if let save { try save() } else { try context.save() }
            ConversationSync.wake()
        } catch {
            context.processPendingChanges(); context.rollback(); restoreDependencies()
            for (review, snapshot) in reviewSnapshots { review.snapshotJSON = snapshot }
            throw error
        }
    }
}

struct KnowledgeActionButtons: View {
    let lifecycle: String
    let perform: (KnowledgeAction) -> Void
    var body: some View {
        ForEach(KnowledgeAction.available(lifecycle)) { action in
            Button(action.title, role: action.destructive ? .destructive : nil) { perform(action) }
        }
    }
}

struct KnowledgeDeletionSheet: View {
    let impact: KnowledgeDeletionImpact
    var onDeleted: () -> Void = {}
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @State private var error: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("永久删除 \(impact.ids.count) 条知识？", systemImage: "trash").font(.headline)
            ScrollView { Text(impact.titles.joined(separator: "\n")).frame(maxWidth: .infinity, alignment: .leading) }.frame(maxHeight: 130)
            Text("将删除这些知识、\(impact.questionIDs.count) 道题目及 \(impact.attemptIDs.count) 条复习记录，无法恢复。历史会话文本和仍被使用的来源会保留。")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            HStack {
                Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("永久删除", role: .destructive) {
                    do { try KnowledgeManagement.delete(impact, context: context); onDeleted(); dismiss() }
                    catch { self.error = error.localizedDescription }
                }
            }
        }.padding(24).frame(width: 420)
    }
}
