import SwiftData
import Foundation

/// One actor-local fetch pass per wake. All Session controllers share these
/// indices; they still check each mutable model's current lifecycle before work.
struct ConversationWorkSnapshot {
    let sessions: [AgentSession]
    let messageOwners: Set<UUID>
    let controls: [AgentRunControl]
    let localMessages: [AgentMessage]
    let runs: [AgentRun]
    let controlsBySession: [UUID: [AgentRunControl]]
    let messagesBySession: [UUID: [AgentMessage]]
    let runsBySession: [UUID: [AgentRun]]

    init(context: ModelContext) throws {
        sessions = try context.fetch(FetchDescriptor<AgentSession>())
        var owners = FetchDescriptor<AgentMessage>()
        owners.propertiesToFetch = [\.sessionID]
        messageOwners = Set(try context.fetch(owners).map(\.sessionID))
        controls = try context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { !$0.sent }, sortBy: [SortDescriptor(\.createdAt)]))
        localMessages = try context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.role == "user" && $0.deliveryStatus == "local" }, sortBy: [SortDescriptor(\.createdAt)]))
        runs = try context.fetch(FetchDescriptor<AgentRun>())
        controlsBySession = Dictionary(grouping: controls, by: \.sessionID)
        messagesBySession = Dictionary(grouping: localMessages, by: \.sessionID)
        runsBySession = Dictionary(grouping: runs, by: \.sessionID)
    }

    func hasWorkHistory(_ session: AgentSession) -> Bool {
        messageOwners.contains(session.id) || session.lifecycleActionsJSON != "[]" || session.lastSessionEventSeq > 0
    }
    func needsControl(_ session: AgentSession) -> Bool {
        hasWorkHistory(session) && (session.memoryPolicySyncedRevision != session.memoryPolicyRevision ||
            session.memoryContentSyncedRevision != session.memoryContentRevision ||
            session.lifecycleSyncedRevision < session.lifecycleRevision ||
            LearningMemory.array(session.lifecycleActionsJSON).contains { ($0["lifecycle_revision"] as? Int ?? 0) > session.lifecycleSyncedRevision } ||
            !(controlsBySession[session.id] ?? []).isEmpty)
    }
}
