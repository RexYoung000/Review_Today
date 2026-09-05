import Foundation
import SwiftData

extension AgentAPI {
    static func conversationRequest(_ path: String, body: [String: Any]? = nil) async throws -> [String: Any] {
        var request = URLRequest(url: base.appending(path: path.components(separatedBy: "?")[0]))
        if let query = path.components(separatedBy: "?").dropFirst().first {
            var components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!
            components.percentEncodedQuery = query
            request.url = components.url
        }
        request.timeoutInterval = 15
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw HarnessAPIError.http((response as? HTTPURLResponse)?.statusCode ?? 0)
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ... 299).contains(status) else {
            let detail = object["detail"] as? [String: Any]
            throw HarnessAPIError.server(code: detail?["error_code"] as? String ?? "RT.RUN.HTTP_FAILED",
                                         message: detail?["message"] as? String ?? "请求未完成")
        }
        return object
    }
}

enum ConversationProcessor {
    @MainActor
    static func tick(context: ModelContext, monitor: AgentServiceMonitor, pollEvents: Bool = true) async {
        guard monitor.serviceReachable && monitor.conversationSupported else { return }
        let sessions = (try? context.fetch(FetchDescriptor<AgentSession>())) ?? []
        // Durable controls run before pulling committable output. Never lose rapid
        // stop/mode/resume operations by storing only one pending field on a Task.
        let controls = (try? context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { !$0.sent }, sortBy: [SortDescriptor(\.createdAt)]))) ?? []
        var blockedSessions = Set<UUID>()
        for control in controls where !control.sent {
            guard !blockedSessions.contains(control.sessionID) else { continue }
            do {
                var body: [String: Any] = ["action_id": control.id.uuidString.lowercased(), "action": control.action]
                if let mode = control.mode { body["mode"] = mode }
                _ = try await AgentAPI.conversationRequest("/v2/runs/\(control.runID.uuidString.lowercased())/actions", body: body)
                control.sent = true
                control.lastError = nil
                try context.save()
            } catch {
                // Preserve FIFO within this Session, without blocking unrelated
                // Sessions or the event feed that explains a failed control.
                blockedSessions.insert(control.sessionID)
                control.sent = false
                control.lastError = HarnessAPIError.code(for: error)
                try? context.save()
            }
        }
        let messages = (try? context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.role == "user" && $0.deliveryStatus == "local" }, sortBy: [SortDescriptor(\.createdAt)]))) ?? []
        for message in messages where message.role == "user" && message.deliveryStatus == "local" {
            guard let session = sessions.first(where: { $0.id == message.sessionID }), session.status == "active" else { continue }
            guard !blockedSessions.contains(session.id) else { continue }
            // Historic inputs already attached to a v2 Task use its compatibility
            // processor. All newly-created UI input has no Task before recognition.
            if message.taskID != nil && message.runID == nil && message.operationJSON == nil { continue }
            do {
                let sid = session.id
                let before = message.createdAt
                var recentQuery = FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid && $0.createdAt < before && $0.responseState == "complete" }, sortBy: [SortDescriptor(\.createdAt, order: .reverse)])
                recentQuery.fetchLimit = 10
                let recent = try context.fetch(recentQuery).reversed().map { ["role": $0.role == "assistant" ? "coach" : $0.role, "content": String($0.content.prefix(3000))] }
                let knowledge = (try? context.fetch(FetchDescriptor<Knowledge>())) ?? []
                let relatedKnowledge = HarnessProcessor.relevantKnowledgeSummaries(for: message.content, candidates: knowledge.filter { $0.lifecycle == "active" })
                var body: [String: Any] = [
                    "client_message_id": (message.clientMessageID ?? message.id).uuidString.lowercased(),
                    "content": message.content, "content_type": message.contentType,
                    "mode_preset": session.modePreset, "delivery": message.deliveryMode,
                    "primary_language": UserLanguage.primaryCode,
                    "context": ["summary": String(session.summaryText.prefix(12000)), "recent_messages": Array(recent), "knowledge_summaries": Array(relatedKnowledge.prefix(5))],
                ]
                if let operation = object(message.operationJSON), !operation.isEmpty { body["operation"] = operation }
                // Import only the current unfinished legacy goal when this Session
                // has never used message/run processing. No cross-Session context.
                let runs = (try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
                if !runs.contains(where: { $0.sessionID == session.id }) {
                    let tasks = (try? context.fetch(FetchDescriptor<LearningTask>())) ?? []
                    if let legacy = tasks.filter({ $0.sessionID == session.id && !["completed", "cancelled", "terminal_failed", "accepted"].contains($0.status) })
                        .sorted(by: { $0.updatedAt < $1.updatedAt }).last {
                        body["task_id"] = legacy.id.uuidString.lowercased()
                    }
                }
                let response = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/messages", body: body)
                guard let rawID = response["run_id"] as? String, let id = UUID(uuidString: rawID) else { continue }
                message.runID = id
                message.lastDeliveryError = nil
                message.deliveryStatus = response["status"] as? String ?? "accepted"
                let latestRuns = (try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
                let run = latestRuns.first(where: { $0.id == id }) ?? AgentRun(id: id, sessionID: session.id)
                if !latestRuns.contains(where: { $0.id == id }) { context.insert(run); run.status = message.deliveryStatus }
                run.revision = max(run.revision, response["revision"] as? Int ?? 1)
                if run.status == "adjusting" { run.status = message.deliveryStatus }
                ConversationSync.wake()
                try context.save()
            } catch {
                // Keep the exact same message ID in the local outbox for recovery.
                message.lastDeliveryError = HarnessAPIError.code(for: error)
                try? context.save()
                continue
            }
        }
        guard pollEvents else { return }
        let allRuns = (try? context.fetch(FetchDescriptor<AgentRun>())) ?? []
        for session in sessions where allRuns.contains(where: { $0.sessionID == session.id }) {
            do {
                let page = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/events?after_seq=\(session.lastSessionEventSeq)")
                try persist(page, session: session, context: context)
                session.syncError = nil
                try context.save()
                _ = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/ack",
                                                          body: ["last_event_seq": session.lastSessionEventSeq])
            } catch {
                // Cursor is committed with all events/messages, so an uncertain ACK
                // is safe to repeat. It cannot skip an unpersisted event.
                context.rollback()
                session.syncError = HarnessAPIError.code(for: error)
                try? context.save()
                continue
            }
        }
    }

    @MainActor
    @discardableResult
    static func queueControl(_ run: AgentRun, action: String, mode: String? = nil, context: ModelContext) -> Bool {
        context.insert(AgentRunControl(runID: run.id, sessionID: run.sessionID, action: action, mode: mode))
        if action == "stop" || action == "cancel_task" {
            if let started = run.startedAt { run.elapsedMS = Int(Date.now.timeIntervalSince(started) * 1000) }
            run.startedAt = nil
            run.status = "stopping"
            run.userSummary = "停止请求已保存，等待服务确认"
            let rid = run.id
            for message in (try? context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.runID == rid }))) ?? [] where message.responseState == "streaming" {
                message.responseState = "interrupted"
            }
        } else if action == "resume" || action == "retry" {
            run.userSummary = "恢复请求已保存"
        }
        do {
            try context.save()
            ConversationSync.wake()
            return true
        } catch {
            context.rollback()
            return false
        }
    }

    @MainActor
    static func persist(_ page: [String: Any], session: AgentSession, context: ModelContext) throws {
        let sid = session.id
        guard uuid(page["session_id"]) == sid else { throw HarnessAPIError.http(409) }
        var messages = try context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid }))
        var tasks = try context.fetch(FetchDescriptor<LearningTask>(predicate: #Predicate { $0.sessionID == sid }))
        var runs = try context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))
        let steering = Set(runs.filter { $0.status == "adjusting" }.map(\.id))
        let pendingControls = try context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { $0.sessionID == sid && !$0.sent }))
        let stopping = Set(pendingControls.filter { ["stop", "cancel_task"].contains($0.action) }.map(\.runID))
        for raw in page["runs"] as? [[String: Any]] ?? [] {
            guard uuid(raw["session_id"]) == sid else { throw HarnessAPIError.http(409) }
            guard let id = uuid(raw["run_id"]) else { continue }
            let run = runs.first(where: { $0.id == id }) ?? AgentRun(id: id, sessionID: session.id)
            if !runs.contains(where: { $0.id == id }) { context.insert(run); runs.append(run) }
            guard (raw["revision"] as? Int ?? 1) >= run.revision else { continue }
            let rawActivityKind = raw.keys.contains("activity_kind") ? raw["activity_kind"] as? String : run.activityKind
            let rawCompletedAt = raw.keys.contains("completed_at") ? optionalDate(raw["completed_at"]) : run.completedAt
            // Delta-only pages do not change the run header or its clock. Avoid
            // invalidating every session/header observer on each text fragment.
            if run.updatedAt == date(raw["updated_at"]), run.status == raw["status"] as? String,
               run.revision == raw["revision"] as? Int,
               run.activityKind == rawActivityKind, run.completedAt == rawCompletedAt { continue }
            run.taskID = uuid(raw["task_id"])
            run.status = raw["status"] as? String ?? "accepted"
            run.stage = raw["stage"] as? String ?? "received"
            run.userSummary = raw["user_summary"] as? String ?? "已保存"
            run.revision = raw["revision"] as? Int ?? 1
            run.attempt = raw["attempt"] as? Int ?? 1
            run.errorCode = raw["error_code"] as? String
            run.inputMessageIDsJSON = json(raw["input_ids"] ?? [])
            run.updatedAt = date(raw["updated_at"])
            if !stopping.contains(id) {
                run.startedAt = (raw["started_at"] as? String).map { date($0) }
                run.elapsedMS = raw["elapsed_ms"] as? Int ?? 0
            }
            run.firstTextMS = raw["first_text_ms"] as? Int
            run.attemptDurationsJSON = json(raw["attempt_durations"] ?? [])
            run.transport = raw["transport"] as? String ?? ""
            run.activityKind = rawActivityKind
            run.completedAt = rawCompletedAt
            for message in messages where message.runID == id && message.responseState == "streaming" && message.responseRevision < run.revision {
                message.responseState = "interrupted"
            }
        }
        let events = (page["events"] as? [[String: Any]] ?? []).sorted { ($0["seq"] as? Int ?? 0) < ($1["seq"] as? Int ?? 0) }
        for raw in events {
            guard uuid(raw["session_id"]) == sid else { throw HarnessAPIError.http(409) }
            guard let id = uuid(raw["event_id"]), let runID = uuid(raw["run_id"]), let seq = raw["seq"] as? Int else { continue }
            if seq <= session.lastSessionEventSeq { continue }
            guard seq == session.lastSessionEventSeq + 1 else { throw HarnessAPIError.http(409) }
            let event = SessionEventRecord(id: id, sessionID: session.id, runID: runID, seq: seq)
            event.stage = raw["stage"] as? String ?? ""
            event.summary = raw["user_summary"] as? String ?? ""
            event.detail = raw["detail_summary"] as? String ?? ""
            event.model = raw["model"] as? String ?? ""
            event.attempt = raw["attempt"] as? Int ?? 1
            event.durationMS = raw["duration_ms"] as? Int
            event.errorCode = raw["error_code"] as? String
            var audit = raw
            if var auditPayload = audit["payload"] as? [String: Any],
               var auditResponse = auditPayload["response"] as? [String: Any] {
                auditResponse.removeValue(forKey: "text")
                auditResponse.removeValue(forKey: "delta")
                auditPayload["response"] = auditResponse
                audit["payload"] = auditPayload
            }
            event.payloadJSON = json(audit) // event metadata only; no repeated answer body or hidden reasoning
            event.occurredAt = date(raw["occurred_at"])
            context.insert(event)
            let payload = raw["payload"] as? [String: Any] ?? [:]
            let revision = raw["revision"] as? Int ?? 1
            let currentRevision = runs.first(where: { $0.id == runID })?.revision ?? revision
            // Archiving is a durable UI fence, not only a navigation filter. The
            // service may still replay an event that was already in flight after
            // the stop control was accepted; keep its audit record, but never let
            // it revive visible output, task state, tags, or follow-on effects.
            let blocked = session.status == "archived" || stopping.contains(runID) || steering.contains(runID)
            if !blocked, revision >= currentRevision,
               let intent = payload["intent"] as? [String: Any],
               let tags = intent["session_tags"] as? [String], !tags.isEmpty {
                session.setAutomaticTopicTags(tags)
            }
            if let response = payload["response"] as? [String: Any], let messageID = uuid(response["response_id"]),
               let text = response["text"] as? String, !text.isEmpty {
                let state = response["status"] as? String ?? "streaming"
                let chunk = response["chunk_seq"] as? Int ?? 0
                if !blocked && (revision >= currentRevision || ["interrupted", "failed"].contains(state)) {
                    let saved = messages.first(where: { $0.id == messageID }) ?? AgentMessage(id: messageID, sessionID: sid, role: "assistant", content: "", createdAt: event.occurredAt, deliveryStatus: "received")
                    if !messages.contains(where: { $0.id == messageID }) { context.insert(saved); messages.append(saved) }
                    if revision >= saved.responseRevision && chunk > saved.responseChunkSeq {
                        saved.runID = runID
                        if saved.responseState != "interrupted" { saved.content = text }
                        saved.responseState = state
                        saved.responseRevision = revision
                        saved.responseChunkSeq = chunk
                        if saved.firstReceivedAt == nil { saved.firstReceivedAt = .now }
                    }
                }
            }
            if !blocked, let message = raw["message"] as? [String: Any], let messageID = uuid(message["message_id"]),
               payload["response"] == nil || revision >= currentRevision {
                let saved = messages.first(where: { $0.id == messageID }) ?? AgentMessage(id: messageID, sessionID: sid, taskID: uuid(raw["task_id"]), role: "assistant", content: "", createdAt: date(message["created_at"]), deliveryStatus: "received")
                if !messages.contains(where: { $0.id == messageID }) { context.insert(saved); messages.append(saved) }
                saved.runID = runID
                saved.content = message["content"] as? String ?? ""
                saved.responseState = "complete"
                if saved.firstReceivedAt == nil { saved.firstReceivedAt = .now }
            }
            if !blocked, let summary = payload["session_summary"] as? [String: Any] {
                let record = SessionSummaryRecord(sessionID: session.id, version: summary["version"] as? Int ?? 1,
                                                  goal: summary["goal"] as? String ?? session.title)
                record.confirmedDecisionsJSON = json(summary["confirmed_decisions"] ?? [])
                record.openQuestionsJSON = json(summary["open_questions"] ?? [])
                session.summaryText = summary["summary"] as? String ?? session.summaryText
                context.insert(record)
            }
            if !blocked, payload["source_type"] as? String == "agent_generated" {
                let sources = try context.fetch(FetchDescriptor<SourceReference>())
                if !sources.contains(where: { $0.sessionID == session.id && $0.locator == runID.uuidString }) {
                    let source = SourceReference(sessionID: session.id, taskID: uuid(raw["task_id"]), url: "", title: "Agent 生成讲义",
                                                 locator: runID.uuidString)
                    source.sourceType = "agent_generated"
                    context.insert(source)
                }
            }
            if !blocked, revision >= currentRevision, let taskJSON = payload["task"] as? [String: Any], let taskID = uuid(taskJSON["task_id"]),
               let inputID = uuid(taskJSON["client_message_id"]) {
                let view = try JSONDecoder().decode(AgentAPI.LearningTaskView.self, from: JSONSerialization.data(withJSONObject: taskJSON))
                let task = tasks.first(where: { $0.id == taskID }) ?? LearningTask(id: taskID, sessionID: session.id, inputMessageID: inputID)
                if !tasks.contains(where: { $0.id == taskID }) { context.insert(task); tasks.append(task) }
                task.conversationManaged = true
                HarnessProcessor.apply(view, to: task)
            }
            for source in !blocked ? (payload["sources"] as? [[String: Any]] ?? []) : [] {
                guard let url = source["url"] as? String else { continue }
                let sources = try context.fetch(FetchDescriptor<SourceReference>())
                let saved = sources.first(where: { $0.sessionID == session.id && $0.url == url }) ??
                    SourceReference(sessionID: session.id, taskID: uuid(raw["task_id"]), url: url, title: source["title"] as? String ?? url)
                if !sources.contains(where: { $0.id == saved.id }) { context.insert(saved) }
                saved.sourceType = source["type"] as? String ?? "public_source"
                if let content = source["content"] as? String, !content.isEmpty { saved.locator = content }
            }
            if !blocked, let handoff = payload["handoff"] as? [String: Any], let key = handoff["handoff_id"] as? String {
                let sessions = try context.fetch(FetchDescriptor<AgentSession>())
                if !sessions.contains(where: { $0.handoffID == key }) {
                    let destination = AgentSession(title: String((handoff["goal"] as? String ?? "新学习目标").prefix(28)),
                                                   modePreset: handoff["mode"] as? String ?? "auto", sourceSessionID: session.id)
                    destination.handoffID = key
                    destination.summaryText = handoff["summary"] as? String ?? ""
                    context.insert(destination)
                    let message = AgentMessage(sessionID: destination.id, role: "user", content: handoff["goal"] as? String ?? "")
                    context.insert(message)
                }
            }
            session.lastSessionEventSeq = seq
        }
        if session.status != "archived" {
            session.runPaused = page["paused"] as? Bool ?? false
        }
        for control in pendingControls {
            if let run = runs.first(where: { $0.id == control.runID }) {
                run.userSummary = control.lastError.map { "控制请求尚未送达，将继续重试：\($0)" } ?? "操作已保存在本机，等待服务确认"
                if ["stop", "cancel_task"].contains(control.action) { run.status = "stopping" }
            }
        }
        for run in runs where steering.contains(run.id) {
            run.status = "adjusting"
            run.userSummary = "已收到补充，正在调整"
        }
        if session.status != "archived" {
            if !pendingControls.contains(where: { $0.action == "set_mode" }), let mode = page["mode"] as? String { session.modePreset = mode }
            session.pendingOperationJSON = (page["pending"] as? [String: Any]).map(json)
        }
        try context.save()
    }

    nonisolated static func object(_ value: String?) -> [String: Any]? {
        guard let value, let data = value.data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    nonisolated static func json(_ value: Any) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: value) else { return "{}" }
        return String(decoding: data, as: UTF8.self)
    }
    private static func uuid(_ value: Any?) -> UUID? { (value as? String).flatMap(UUID.init(uuidString:)) }
    private static func date(_ value: Any?) -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return (value as? String).flatMap(formatter.date(from:)) ?? .now
    }
    private static func optionalDate(_ value: Any?) -> Date? {
        guard let value = value as? String else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value)
    }
}
