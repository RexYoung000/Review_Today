import Foundation
import SwiftData
import SwiftUI

struct SessionDeletionImpact: Identifiable, Equatable {
    var id: String { sessionIDs.map(\.uuidString).sorted().joined() }
    let sessionIDs: Set<UUID>
    let titles: [String]
    let cardIDs: Set<UUID>
    let retainedCardIDs: Set<UUID>
    let attemptIDs: Set<UUID>
}

@MainActor
enum SessionDeletion {
    static func records(_ context: ModelContext) throws -> [[String: Any]] {
        guard context.container.schema.entities.contains(where: { $0.name == "AppSettings" }) else { return [] }
        return try context.fetch(FetchDescriptor<AppSettings>()).flatMap { LearningMemory.array($0.sessionDeletionsJSON) }
    }
    static func contains(_ id: UUID, context: ModelContext) throws -> Bool {
        try records(context).contains { ($0["session_id"] as? String).flatMap(UUID.init(uuidString:)) == id }
    }
    static func pendingCount(_ raw: String) -> Int { LearningMemory.array(raw).filter { $0["cleaned"] as? Bool != true }.count }

    static func impact(_ ids: Set<UUID>, context: ModelContext) throws -> SessionDeletionImpact {
        let sessions = try context.fetch(FetchDescriptor<AgentSession>()).filter { ids.contains($0.id) }
        guard sessions.count == ids.count, !ids.isEmpty, sessions.allSatisfy({ $0.status == "archived" }) else {
            throw HarnessAPIError.server(code: "RT.SESSION.DELETE_SCOPE", message: "只能永久删除已归档的会话。")
        }
        let refs = try context.fetch(FetchDescriptor<KnowledgeReference>())
        let runs = try context.fetch(FetchDescriptor<AgentRun>())
        let tasks = try context.fetch(FetchDescriptor<LearningTask>())
        let messages = try context.fetch(FetchDescriptor<AgentMessage>())
        let allSessions = try context.fetch(FetchDescriptor<AgentSession>())
        let cards = try context.fetch(FetchDescriptor<Knowledge>())
        func uses(_ references: [[String: Any]], _ card: UUID) -> Bool {
            references.contains { value in
                (value["knowledge_id"] as? String).flatMap(UUID.init(uuidString:)) == card || uses(value["dependencies"] as? [[String: Any]] ?? [], card)
            }
        }
        var deletable = Set<UUID>(), retained = Set<UUID>()
        for card in cards {
            let originated = card.originSessionID.map(ids.contains) ?? false
            let referenced = refs.contains { ids.contains($0.sessionID) && $0.knowledgeID == card.id }
            guard originated || referenced else { continue }
            let shared = messages.contains { !ids.contains($0.sessionID) && $0.content.lowercased().contains("reviewtoday://knowledge/" + card.id.uuidString.lowercased()) }
                || refs.contains { !ids.contains($0.sessionID) && $0.knowledgeID == card.id }
                || runs.contains { !ids.contains($0.sessionID) && uses(LearningMemory.array($0.memoryReferencesJSON), card.id) }
                || tasks.contains { !ids.contains($0.sessionID) && uses(LearningMemory.array($0.memoryReferencesJSON), card.id) }
                || allSessions.contains { !ids.contains($0.id) && uses(LearningMemory.array($0.learningEvidenceJSON), card.id) }
            if originated && !shared { deletable.insert(card.id) } else { retained.insert(card.id) }
        }
        let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>()).filter { deletable.contains($0.knowledgeId) }
        return SessionDeletionImpact(sessionIDs: ids, titles: sessions.map(\.title).sorted(), cardIDs: deletable,
                                     retainedCardIDs: retained, attemptIDs: Set(attempts.map(\.attemptId)))
    }

    /// No suspension between revalidation, tombstone, explicit purge and save.
    static func perform(_ approved: SessionDeletionImpact, includeCards: Bool, context: ModelContext, save: (() throws -> Void)? = nil) throws -> SessionDeletionImpact? {
        let current = try impact(approved.sessionIDs, context: context)
        guard current == approved else { return current }
        do {
            let settings = try AgentComposerStore.settings(context)
            var markers = LearningMemory.array(settings.sessionDeletionsJSON)
            let sessions = try context.fetch(FetchDescriptor<AgentSession>())
            let targets = sessions.filter { approved.sessionIDs.contains($0.id) }
            for session in targets {
                markers.append(["session_id": session.id.uuidString.lowercased(), "action_id": UUID().uuidString.lowercased(),
                                "archive_action_id": UUID().uuidString.lowercased(), "action": "delete", "lifecycle_revision": session.lifecycleRevision + 1,
                                "deleted_at": Date.now.ISO8601Format(), "cleaned": false])
                session.memoryUseAllowed = false
                session.memoryPolicyRevision += 1
                session.status = "deleted"
            }
            settings.sessionDeletionsJSON = ConversationProcessor.json(markers)
            if includeCards {
                let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
                let removedAttempts = attempts.filter { approved.cardIDs.contains($0.knowledgeId) }
                for attempt in removedAttempts { context.delete(attempt) }
                for review in try context.fetch(FetchDescriptor<ReviewSession>()) {
                    let original = review.snapshotJSON.split(separator: ",").map(String.init)
                    let retained = original.filter { value in
                        guard let id = UUID(uuidString: value) else { return true }
                        return !approved.cardIDs.contains(id)
                    }
                    let touched = retained != original || removedAttempts.contains { $0.sessionId == review.id }
                    guard touched else { continue }
                    if retained.isEmpty && !attempts.contains(where: { $0.sessionId == review.id && !approved.cardIDs.contains($0.knowledgeId) }) {
                        context.delete(review)
                    } else { review.snapshotJSON = retained.joined(separator: ",") }
                }
                for state in try context.fetch(FetchDescriptor<FsrsState>()) where approved.cardIDs.contains(state.knowledgeId) { context.delete(state) }
                for card in try context.fetch(FetchDescriptor<Knowledge>()) where approved.cardIDs.contains(card.id) { context.delete(card) }
            }
            try LearningMemory.fenceInvalidReferences(context: context)
            // Keep surviving transcripts, but drop private derived checkpoints.
            let affectedRuns = try context.fetch(FetchDescriptor<AgentRun>()).filter { $0.memoryInvalidationRevision >= 0 }
            for session in sessions where !approved.sessionIDs.contains(session.id) {
                if session.sourceSessionID.map(approved.sessionIDs.contains) == true { session.handoffJSON = nil }
                if affectedRuns.contains(where: { $0.sessionID == session.id }) { session.checkpointJSON = nil }
            }
            for value in try context.fetch(FetchDescriptor<AgentMessage>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<AgentRun>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<AgentRunControl>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<SessionEventRecord>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            let ownedSources = Set(try context.fetch(FetchDescriptor<LearningTask>()).filter { approved.sessionIDs.contains($0.sessionID) }.compactMap(\.sourceID))
            for value in try context.fetch(FetchDescriptor<LearningTask>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<TaskEventRecord>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<SourceReference>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<KnowledgeReference>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for value in try context.fetch(FetchDescriptor<SessionSummaryRecord>()) where approved.sessionIDs.contains(value.sessionID) { context.delete(value) }
            for source in try context.fetch(FetchDescriptor<Source>()) where ownedSources.contains(source.id) && source.tasks.isEmpty {
                if !((try context.fetch(FetchDescriptor<Knowledge>())).contains { $0.source?.id == source.id }) { context.delete(source) }
            }
            for session in targets { context.delete(session) }
            if let save { try save() } else { try context.save() }
            ConversationSync.wake()
            return nil
        } catch { context.rollback(); throw error }
    }

    static func cleanPending(context: ModelContext) async {
        guard let initial = try? records(context) else { return }
        for marker in initial where marker["cleaned"] as? Bool != true {
            guard let sid = marker["session_id"] as? String else { continue }
            do {
                // Replay the offline archive before destructive service cleanup.
                // The same action ID and revision are reused across retries.
                if let archiveID = marker["archive_action_id"] as? String, let revision = marker["lifecycle_revision"] as? Int {
                    do {
                        _ = try await AgentAPI.conversationRequest("/v2/sessions/\(sid)/actions", body: ["action_id": archiveID, "action": "archive", "lifecycle_revision": revision - 1])
                    } catch {
                        let code = HarnessAPIError.code(for: error)
                        if !["RT.SESSION.DELETED", "RT.SESSION.VERSION_CONFLICT"].contains(code) { throw error }
                    }
                }
                let result = try await AgentAPI.conversationRequest("/v2/sessions/\(sid)/actions", body: marker)
                guard result["status"] as? String == "deleted" else { continue }
                let settings = try AgentComposerStore.settings(context)
                var updated = LearningMemory.array(settings.sessionDeletionsJSON)
                if let index = updated.firstIndex(where: { $0["session_id"] as? String == sid }) { updated[index]["cleaned"] = true }
                settings.sessionDeletionsJSON = ConversationProcessor.json(updated)
                try context.save()
            } catch { return } // durable queue retries on reconnect; no content in marker
        }
    }
}

struct SessionDeletionSheet: View {
    @State var impact: SessionDeletionImpact
    let onDeleted: (Set<UUID>) -> Void
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @State private var includeCards = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("永久删除会话", systemImage: "trash").font(.headline)
            Text(impact.titles.count == 1 ? "删除“\(impact.titles[0])”？" : "删除这 \(impact.titles.count) 个已归档会话？")
                .lineLimit(3).fixedSize(horizontal: false, vertical: true)
            Text("会话内容、草稿和学习进度将永久删除，无法恢复。")
            if !impact.cardIDs.isEmpty {
                Toggle("同时删除这些会话独有的知识卡片及对应复习记录", isOn: $includeCards)
                    .toggleStyle(.checkbox).fixedSize(horizontal: false, vertical: true)
                Text("\(impact.cardIDs.count) 张独有知识卡片 · \(impact.attemptIDs.count) 条练习记录")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Text(includeCards ? "保留 \(impact.retainedCardIDs.count) 张共享、仅引用或归属不明的卡片。" : "保留关联的 \(impact.cardIDs.count + impact.retainedCardIDs.count) 张知识卡片及其练习记录。")
                .font(.callout).foregroundStyle(.secondary)
            if let error { Text(error).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true) }
            HStack {
                Spacer()
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("永久删除", role: .destructive) {
                    do {
                        if let changed = try SessionDeletion.perform(impact, includeCards: includeCards, context: context) {
                            impact = changed; includeCards = false
                            error = "关联内容有变化，已更新删除范围，请重新确认。"
                        } else { onDeleted(impact.sessionIDs); dismiss() }
                    } catch { self.error = "未能删除，会话仍保留。请重试。" }
                }
            }
        }.padding(24).frame(width: 460)
    }
}
