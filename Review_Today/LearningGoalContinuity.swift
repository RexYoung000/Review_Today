import Foundation
import SwiftData

/// Durable logical ownership; old task segments keep their original history.
enum LearningGoalContinuity {
    static func ownership(_ task: LearningTask) -> [String: Any] {
        ConversationProcessor.object(task.goalOwnershipJSON) ?? [
            "goal_id": task.id.uuidString.lowercased(), "owner_task_id": task.id.uuidString.lowercased(),
            "owner_session_id": task.sessionID.uuidString.lowercased(), "version": 1]
    }
    static func owns(_ task: LearningTask) -> Bool {
        ownership(task)["owner_task_id"] as? String == task.id.uuidString.lowercased()
    }
    static func destination(_ task: LearningTask) -> UUID? {
        guard !owns(task), let raw = ownership(task)["owner_session_id"] as? String else { return nil }
        return UUID(uuidString: raw)
    }
    static func unfinished(_ tasks: [LearningTask], sessions: [AgentSession]) -> [LearningTask] {
        var seen = Set<String>()
        return tasks.sorted { (ownership($0)["version"] as? Int ?? 1) > (ownership($1)["version"] as? Int ?? 1) }.filter { task in
            guard owns(task), !["completed", "cancelled", "terminal_failed"].contains(task.status),
                  sessions.contains(where: { $0.id == task.sessionID && $0.status == "active" }) else { return false }
            return seen.insert(ownership(task)["goal_id"] as? String ?? task.id.uuidString).inserted
        }
    }
    @MainActor static func candidates(excluding id: UUID, context: ModelContext) throws -> [[String: Any]] {
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        return try context.fetch(FetchDescriptor<LearningTask>()).compactMap { task in
            guard task.sessionID != id, owns(task), task.learningPlanJSON != nil,
                  !["completed", "cancelled", "terminal_failed"].contains(task.status),
                  let session = sessions.first(where: { $0.id == task.sessionID }), session.memoryUseAllowed,
                  session.memoryPolicyRevision == session.memoryPolicySyncedRevision,
                  session.memoryContentRevision == session.memoryContentSyncedRevision else { return nil }
            return ["task_id": task.id.uuidString.lowercased(), "session_id": task.sessionID.uuidString.lowercased(),
                    "owner_version": ownership(task)["version"] as? Int ?? 1,
                    "policy_version": session.memoryPolicyRevision, "content_version": session.memoryContentRevision]
        }
    }
    @MainActor static func prepareSources(excluding id: UUID, context: ModelContext) async throws {
        let refs = try candidates(excluding: id, context: context)
        let ids = Array(Set(refs.compactMap { $0["session_id"] as? String }))
        guard !ids.isEmpty else { return }
        let state = try await AgentAPI.conversationRequest("/v2/continuation/sources", body: ["session_ids": ids])
        try apply(state["goal_ownership"] as? [[String: Any]] ?? [], context: context)
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        for raw in state["missing_session_ids"] as? [String] ?? [] {
            guard let source = sessions.first(where: { $0.id.uuidString.lowercased() == raw }), source.memoryUseAllowed else { continue }
            // Recovery is paused; it restores history but grants no old consent.
            do {
                try await ConversationProcessor.restoreCheckpoint(source, context: context)
                _ = try await AgentAPI.conversationRequest("/v2/sessions/\(raw)/actions", body: [
                    "action_id": UUID().uuidString.lowercased(), "action": "memory_policy", "allowed": source.memoryUseAllowed,
                    "policy_version": source.memoryPolicyRevision, "content_version": source.memoryContentRevision])
            } catch { source.syncError = HarnessAPIError.code(for: error) }
        }
        try context.save()
    }
    @MainActor static func apply(_ values: [[String: Any]], context: ModelContext) throws {
        guard !values.isEmpty else { return }
        let tasks = try context.fetch(FetchDescriptor<LearningTask>())
        for value in values {
            guard let goal = value["goal_id"] as? String, let owner = value["owner_task_id"] as? String,
                  let destination = value["owner_session_id"] as? String, UUID(uuidString: owner) != nil,
                  UUID(uuidString: destination) != nil, let version = value["version"] as? Int else { continue }
            for task in tasks where ownership(task)["goal_id"] as? String == goal {
                let previous = ownership(task)["version"] as? Int ?? 1
                guard version > previous || (version == previous && task.goalOwnershipJSON == nil) else { continue }
                task.goalOwnershipJSON = ConversationProcessor.json(value)
                if owner != task.id.uuidString.lowercased() {
                    task.status = "completed"; task.stage = "continued_elsewhere"; task.userSummary = "已在另一会话继续"
                    task.requiredActionType = nil; task.requiredActionPrompt = nil; task.requiredActionOptionsJSON = nil
                    task.pendingActionID = nil; task.pendingActionType = nil; task.pendingActionContent = nil
                }
            }
        }
    }
    /// Apply the latest locally committed ownership even if an old checkpoint
    /// reaches restore after its destination. This does not advance event cursors.
    @MainActor static func fenceCheckpoint(_ checkpoint: inout [String: Any], context: ModelContext) throws {
        let tasks = try context.fetch(FetchDescriptor<LearningTask>())
        var rows = checkpoint["tasks"] as? [String: [String: Any]] ?? [:]
        for (key, var row) in rows {
            guard let local = tasks.first(where: { $0.id.uuidString.lowercased() == key }), local.goalOwnershipJSON != nil else { continue }
            var state = row["context"] as? [String: Any] ?? [:]
            state["goal_ownership"] = ownership(local); row["context"] = state
            if !owns(local) {
                row["status"] = "completed"; row["stage"] = "continued_elsewhere"; row["required_action"] = NSNull()
                row["user_summary"] = "已在另一会话继续"
                if checkpoint["active_task_id"] as? String == key {
                    checkpoint["active_task_id"] = NSNull(); checkpoint["focus_goal"] = ""; checkpoint["pending"] = NSNull(); checkpoint["draft"] = NSNull()
                }
            }
            rows[key] = row
        }
        checkpoint["tasks"] = rows
    }
}
