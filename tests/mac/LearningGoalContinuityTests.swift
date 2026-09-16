import Foundation
import SwiftData

@main struct LearningGoalContinuityTests {
    @MainActor static func main() throws {
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: AgentSession.self, LearningTask.self, configurations: config)
        let context = container.mainContext
        let old = AgentSession(title: "RAG"), current = AgentSession(title: "继续 RAG")
        old.memoryPolicySyncedRevision = old.memoryPolicyRevision
        old.memoryContentSyncedRevision = old.memoryContentRevision
        context.insert(old); context.insert(current)
        let first = LearningTask(sessionID: old.id, inputMessageID: UUID(), status: "awaiting_user")
        let next = LearningTask(sessionID: current.id, inputMessageID: UUID(), status: "awaiting_user")
        first.learningPlanJSON = "{\"goal\":\"RAG\"}"
        next.learningPlanJSON = first.learningPlanJSON
        context.insert(first); context.insert(next); try context.save()
        let legacy = LearningGoalContinuity.ownership(first)
        precondition(legacy["goal_id"] as? String == first.id.uuidString.lowercased())
        let refs = try LearningGoalContinuity.candidates(excluding: current.id, context: context)
        precondition(refs.count == 1 && refs[0]["owner_version"] as? Int == 1)
        let value: [String: Any] = ["goal_id": first.id.uuidString.lowercased(), "owner_task_id": next.id.uuidString.lowercased(),
                                   "owner_session_id": current.id.uuidString.lowercased(), "version": 2]
        next.goalOwnershipJSON = ConversationProcessor.json(value)
        try LearningGoalContinuity.apply([value], context: context); try context.save()
        precondition(first.status == "completed" && first.stage == "continued_elsewhere")
        precondition(LearningGoalContinuity.destination(first) == current.id)
        precondition(LearningGoalContinuity.unfinished([first, next], sessions: [old, current]).map(\.id) == [next.id])
        precondition(!LearningDecisionInbox.includes(first, sessions: [old,current]))
        try LearningGoalContinuity.apply([legacy], context: context)
        precondition(!LearningGoalContinuity.owns(first), "old projection cannot reclaim progress")
        var checkpoint: [String: Any] = ["tasks": [first.id.uuidString.lowercased(): ["context": [:], "status": "awaiting_user"]],
                                         "active_task_id": first.id.uuidString.lowercased(), "pending": ["consent_received": true]]
        try LearningGoalContinuity.fenceCheckpoint(&checkpoint, context: context)
        precondition(checkpoint["active_task_id"] is NSNull && checkpoint["pending"] is NSNull)
        let rows = checkpoint["tasks"] as! [String: [String: Any]]
        precondition(rows[first.id.uuidString.lowercased()]?["stage"] as? String == "continued_elsewhere")
        old.status = "archived"
        precondition(LearningGoalContinuity.unfinished([first,next], sessions: [old,current]).count == 1)
        current.memoryUseAllowed = false; try context.save()
        let excluded = try LearningGoalContinuity.candidates(excluding: old.id, context: context)
        precondition(excluded.isEmpty)
        print("PASS: legacy identity, unique progress, historic navigation, stale projection fence, checkpoint restore, archive/exclusion")
    }
}
