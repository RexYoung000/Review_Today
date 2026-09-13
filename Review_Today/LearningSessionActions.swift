import SwiftData
import SwiftUI
import UserNotifications

enum LearningSessionActions {
    @discardableResult
    static func archive(_ session: AgentSession, context: ModelContext) -> Bool {
        let sid = session.id
        let runs = (try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
        for run in runs where ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) {
            if let started = run.startedAt { run.elapsedMS = max(0, Int(Date.now.timeIntervalSince(started) * 1000)) }
            run.startedAt = nil
            run.status = "interrupted"
            run.revision += 1
            run.userSummary = "已停止；会话已归档"
        }
        let messages = (try? context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
        for message in messages {
            if message.responseState == "streaming" { message.responseState = "interrupted" }
            if message.deliveryStatus == "local" { message.deliveryStatus = "held" }
        }
        for control in (try? context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { $0.sessionID == sid && !$0.sent }))) ?? [] {
            control.sent = true // superseded by the atomic Session lifecycle action
            control.lastError = "RT.SESSION.ARCHIVED"
        }
        session.runPaused = true
        session.pendingOperationJSON = nil
        appendLifecycle("archive", session: session)
        session.status = "archived"
        session.archivedAt = .now
        session.updatedAt = .now
        do { try context.save(); ConversationSync.wake(); return true }
        catch { context.rollback(); return false }
    }

    @discardableResult
    static func restore(_ session: AgentSession, context: ModelContext) -> Bool {
        appendLifecycle("restore", session: session)
        session.status = "active"
        session.runPaused = true
        session.archivedAt = nil
        session.updatedAt = .now
        do { try context.save(); ConversationSync.wake(); return true }
        catch { context.rollback(); return false }
    }

    private static func appendLifecycle(_ action: String, session: AgentSession) {
        session.lifecycleRevision += 1
        var actions = (session.lifecycleActionsJSON.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [[String: Any]]) ?? []
        actions.append(["action_id": UUID().uuidString.lowercased(), "action": action, "lifecycle_revision": session.lifecycleRevision])
        session.lifecycleActionsJSON = ConversationProcessor.json(actions)
    }
}
