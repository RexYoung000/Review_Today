import Foundation
import SwiftData

extension AgentAPI {
    static func conversationRequest(_ path: String, body: [String: Any]? = nil) async throws -> [String: Any] {
        try AppRuntime.current.requireSending()
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
    static func acceptedRunID(_ response: [String: Any]) throws -> UUID {
        guard let raw = response["run_id"] as? String, let id = UUID(uuidString: raw) else {
            throw HarnessAPIError.server(code: "RT.RUN.INVALID_ACCEPTANCE", message: "服务未返回有效的运行标识，输入已保留，可重试发送。")
        }
        return id
    }

    @MainActor static func recordAcceptance(_ response: [String: Any], message: AgentMessage, context: ModelContext, save: (() throws -> Void)? = nil) throws {
        let id = try acceptedRunID(response)
        let sid = message.sessionID
        guard try !SessionDeletion.contains(sid, context: context) else { return }
        let latestRuns = try context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))
        let run = latestRuns.first(where: { $0.id == id }) ?? AgentRun(id: id, sessionID: sid)
        let existingRun = latestRuns.contains(where: { $0.id == id })
        let priorMessage = (message.runID, message.lastDeliveryError, message.deliveryStatus)
        let priorRun = (run.revision, run.status)
        message.runID = id
        message.lastDeliveryError = nil
        message.deliveryStatus = response["status"] as? String ?? "accepted"
        if !existingRun { context.insert(run); run.status = message.deliveryStatus }
        run.revision = max(run.revision, response["revision"] as? Int ?? 1)
        if run.status == "adjusting" { run.status = message.deliveryStatus }
        do { if let save { try save() } else { try context.save() } }
        catch {
            context.rollback()
            // SwiftData rollback can leave an already-observed model's optional
            // fields cached. Restore the outbox object as well as the transaction.
            message.runID = priorMessage.0
            message.lastDeliveryError = priorMessage.1
            message.deliveryStatus = priorMessage.2
            if existingRun { run.revision = priorRun.0; run.status = priorRun.1 }
            throw error
        }
        ConversationSync.wake()
    }
    @MainActor
    static func tick(context: ModelContext, monitor: AgentServiceMonitor, pollEvents: Bool = true, onlySession: UUID? = nil, controlsOnly: Bool = false, skipControls: Bool = false, work: ConversationWorkSnapshot? = nil) async {
        guard monitor.serviceReachable && monitor.conversationSupported else { return }
        guard let work = work ?? (try? ConversationWorkSnapshot(context: context)) else { return }
        let allSessions = work.sessions
        let messageOwners = work.messageOwners
        // Empty local conversations have no server work until a message or explicit lifecycle action exists.
        let sessions = allSessions.filter {
            (onlySession == nil || $0.id == onlySession) &&
            (messageOwners.contains($0.id) || $0.lifecycleActionsJSON != "[]" || $0.lastSessionEventSeq > 0)
        }
        // Durable controls run before pulling committable output. Never lose rapid
        // stop/mode/resume operations by storing only one pending field on a Task.
        let controls = onlySession.map { work.controlsBySession[$0] ?? [] } ?? work.controls
        var blockedSessions = Set<UUID>()
        for session in sessions where !skipControls {
            if session.memoryPolicySyncedRevision != session.memoryPolicyRevision || session.memoryContentSyncedRevision != session.memoryContentRevision {
                let policy = session.memoryPolicyRevision, content = session.memoryContentRevision
                do {
                    _ = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/actions", body: [
                        "action_id": UUID().uuidString.lowercased(), "action": "memory_policy", "allowed": session.memoryUseAllowed,
                        "policy_version": policy, "content_version": content])
                    session.memoryPolicySyncedRevision = policy
                    session.memoryContentSyncedRevision = content
                    try context.save()
                } catch { session.syncError = HarnessAPIError.code(for: error); blockedSessions.insert(session.id) }
            }
            let actions = (session.lifecycleActionsJSON.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [[String: Any]]) ?? []
            for action in actions where (action["lifecycle_revision"] as? Int ?? 0) > session.lifecycleSyncedRevision {
                do {
                    _ = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/actions", body: action)
                    session.lifecycleSyncedRevision = action["lifecycle_revision"] as? Int ?? session.lifecycleSyncedRevision
                    try context.save()
                } catch {
                    blockedSessions.insert(session.id)
                    session.syncError = HarnessAPIError.code(for: error)
                    try? context.save()
                    break
                }
            }
        }
        for control in controls where !skipControls && !control.sent && sessions.contains(where: { $0.id == control.sessionID }) {
            guard !blockedSessions.contains(control.sessionID) else { continue }
            do {
                var body: [String: Any] = ["action_id": control.id.uuidString.lowercased(), "action": control.action]
                if let mode = control.mode { body["mode"] = mode }
                if let strength = control.thinkingStrength { body["thinking_strength"] = strength }
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
        if controlsOnly { return }
        let messages = onlySession.map { work.messagesBySession[$0] ?? [] } ?? work.localMessages
        for message in messages where message.role == "user" && message.deliveryStatus == "local" {
            guard message.lastDeliveryError != "RT.RUN.INVALID_ACCEPTANCE" else { continue }
            guard let session = sessions.first(where: { $0.id == message.sessionID }), session.status == "active" else { continue }
            // Durable acceptance is not a model invocation. Bound confirmations
            // and stop/recovery must not wait for an unrelated routing-role probe.
            guard session.lifecycleRevision == session.lifecycleSyncedRevision else { continue }
            guard session.memoryPolicySyncedRevision == session.memoryPolicyRevision && session.memoryContentSyncedRevision == session.memoryContentRevision else { continue }
            guard !controls.contains(where: { $0.sessionID == session.id && !$0.sent }) else { continue }
            guard !blockedSessions.contains(session.id) else { continue }
            // Historic inputs already attached to a v2 Task use its compatibility
            // processor. All newly-created UI input has no Task before recognition.
            if message.taskID != nil && message.runID == nil && message.operationJSON == nil { continue }
            do {
                monitor.beginDelivery(message.id)
                defer { monitor.endDelivery(message.id) }
                let sid = session.id
                let lifecycle = session.lifecycleRevision
                let before = message.createdAt
                var recentQuery = FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid && $0.createdAt < before && $0.responseState == "complete" }, sortBy: [SortDescriptor(\.createdAt, order: .reverse)])
                recentQuery.fetchLimit = 10
                let knowledge = (try? context.fetch(FetchDescriptor<Knowledge>())) ?? []
                let sessionRuns = try context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))
                let invalidRuns = Set(sessionRuns.filter {
                    !LearningMemory.valid(LearningMemory.array($0.memoryReferencesJSON), sessions: allSessions, knowledge: knowledge)
                }.map(\.id))
                let recent = try context.fetch(recentQuery).reversed().filter { message in
                    message.runID.map { !invalidRuns.contains($0) } ?? true
                }.map { ["role": $0.role == "assistant" ? "coach" : $0.role, "content": $0.content] }
                let relatedKnowledge = HarnessProcessor.relevantKnowledgeSummaries(for: message.content, candidates: knowledge.filter { $0.lifecycle == "active" })
                // Make Mac-owned unfinished checkpoints available after backend recovery.
                // This performs no teaching or goal selection.
                // A missing unrelated checkpoint must never block a new question.
                try? await LearningGoalContinuity.prepareSources(excluding: sid, context: context)
                let memoryCandidates = try LearningMemory.candidates(for: message.content, excluding: sid, context: context)
                var body: [String: Any] = [
                    "client_message_id": (message.clientMessageID ?? message.id).uuidString.lowercased(),
                    "content": message.content, "content_type": message.contentType,
                    "mode_preset": session.modePreset, "delivery": message.deliveryMode,
                    "thinking_strength": session.thinkingStrength,
                    "primary_language": UserLanguage.primaryCode,
                    "expected_event_seq": session.lastSessionEventSeq, "lifecycle_revision": session.lifecycleRevision,
                    "context": ["summary": invalidRuns.isEmpty ? String(session.summaryText.prefix(12000)) : "", "recent_messages": Array(recent),
                                "knowledge_summaries": memoryCandidates.isEmpty ? Array(relatedKnowledge.prefix(5)) : [],
                                "continuation_candidates": try LearningGoalContinuity.candidates(excluding: sid, context: context),
                                "memory_candidates": memoryCandidates, "memory_lookup_available": knowledge.contains(where: { $0.lifecycle == "active" }) || allSessions.contains(where: { $0.id != sid && $0.memoryUseAllowed && !LearningMemory.array($0.learningEvidenceJSON).isEmpty }),
                                "invalid_memory_run_ids": invalidRuns.map { $0.uuidString.lowercased() }],
                ]
                if let operation = object(message.operationJSON), !operation.isEmpty { body["operation"] = operation }
                if let handoff = object(session.handoffJSON), var supplied = body["context"] as? [String: Any] {
                    supplied["handoff"] = handoff
                    body["context"] = supplied
                }
                // Import only the current unfinished legacy goal when this Session
                // has never used message/run processing. No cross-Session context.
                let runs = (try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
                if !runs.contains(where: { $0.sessionID == session.id }) {
                    let tasks = (try? context.fetch(FetchDescriptor<LearningTask>(predicate: #Predicate { $0.sessionID == sid }))) ?? []
                    if let legacy = tasks.filter({ $0.sessionID == session.id && !["completed", "cancelled", "terminal_failed", "accepted"].contains($0.status) })
                        .sorted(by: { $0.updatedAt < $1.updatedAt }).last {
                        body["task_id"] = legacy.id.uuidString.lowercased()
                    }
                }
                let response = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/messages", body: body)
                guard session.status == "active", session.lifecycleRevision == lifecycle else {
                    message.deliveryStatus = "held"
                    try context.save()
                    continue
                }
                try recordAcceptance(response, message: message, context: context)
            } catch {
                // Keep the exact same message ID in the local outbox for recovery.
                message.lastDeliveryError = HarnessAPIError.code(for: error)
                if message.lastDeliveryError == "RT.SESSION.CHECKPOINT_REQUIRED" {
                    try? await restoreCheckpoint(session, context: context)
                }
                try? context.save()
                continue
            }
        }
        guard pollEvents else { return }
        let allRuns = (try? context.fetch(FetchDescriptor<AgentRun>())) ?? []
        for session in sessions where allRuns.contains(where: { $0.sessionID == session.id }) {
            do {
                let page = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/events?after_seq=\(session.lastSessionEventSeq)&recovery_version=\(ConversationCheckpoint.version(session.checkpointJSON))")
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
    static func restoreCheckpoint(_ session: AgentSession, context: ModelContext) async throws {
        guard try !SessionDeletion.contains(session.id, context: context) else { return }
        guard var snapshot = object(session.checkpointJSON), var checkpoint = snapshot["checkpoint"] as? [String: Any] else {
            throw HarnessAPIError.server(code: "RT.SESSION.NO_LOCAL_CHECKPOINT", message: "历史仍在本机，执行检查点需要恢复")
        }
        let lifecycle = session.lifecycleRevision
        let storedSeq = (checkpoint["event_base_seq"] as? Int ?? 0) + (checkpoint["events"] as? [Any] ?? []).count
        guard storedSeq >= session.lastSessionEventSeq,
              (checkpoint["event_base_seq"] as? Int ?? 0) <= session.lastSessionEventSeq else {
            // Never pretend a stale checkpoint contains newer learning decisions.
            throw HarnessAPIError.server(code: "RT.SESSION.SNAPSHOT_STALE", message: "历史已保留，执行快照尚未补齐，不能自动恢复")
        }
        // Local history/cursor wins; restore is deliberately paused and never
        // replays a model call or grants a former save confirmation.
        checkpoint["lifecycle_revision"] = lifecycle
        checkpoint["status"] = session.status
        checkpoint["last_acked_seq"] = min(checkpoint["last_acked_seq"] as? Int ?? 0, session.lastSessionEventSeq)
        checkpoint["paused"] = true
        checkpoint["pending"] = NSNull()
        try LearningGoalContinuity.fenceCheckpoint(&checkpoint, context: context)
        snapshot["checkpoint"] = checkpoint
        _ = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/snapshot/restore", body: snapshot)
        guard session.lifecycleRevision == lifecycle else { return }
        session.runPaused = true
        session.pendingOperationJSON = nil
        session.syncError = nil
        let sid = session.id
        for run in try context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid })) where ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) {
            run.status = "interrupted"
            if let start = run.startedAt { run.elapsedMS = Int(Date.now.timeIntervalSince(start) * 1000) }
            run.startedAt = nil
            run.userSummary = "执行记录已恢复，未完成回复需要手动重试"
        }
        try context.save()
    }

    @MainActor
    @discardableResult
    static func queueControl(_ run: AgentRun, action: String, mode: String? = nil, thinkingStrength: String? = nil, context: ModelContext) -> Bool {
        let sid = run.sessionID
        guard let session = try? context.fetch(FetchDescriptor<AgentSession>(predicate: #Predicate { $0.id == sid })).first,
              session.status == "active" else { return false }
        let control = AgentRunControl(runID: run.id, sessionID: run.sessionID, action: action, mode: mode)
        control.thinkingStrength = thinkingStrength
        context.insert(control)
        if action == "stop" || action == "cancel_task" {
            if let started = run.startedAt { run.elapsedMS = Int(Date.now.timeIntervalSince(started) * 1000) }
            run.startedAt = nil
            run.status = "stopping"
            run.userSummary = "停止请求已保存，等待服务确认"
            let rid = run.id
            for message in (try? context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.runID == rid }))) ?? [] where ["streaming", "recovering"].contains(message.responseState) {
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
        guard try !SessionDeletion.contains(session.id, context: context) else { return }
        let sid = session.id
        guard uuid(page["session_id"]) == sid else { throw HarnessAPIError.http(409) }
        var messages = try context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == sid }))
        var tasks = try context.fetch(FetchDescriptor<LearningTask>(predicate: #Predicate { $0.sessionID == sid }))
        var runs = try context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == sid }))
        let steering = Set(runs.filter { $0.status == "adjusting" }.map(\.id))
        let pendingControls = try context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { $0.sessionID == sid && !$0.sent }))
        let stopping = Set(pendingControls.filter { ["stop", "cancel_task"].contains($0.action) }.map(\.runID))
        var memorySessions: [AgentSession]?
        var memoryKnowledge: [Knowledge]?
        var invalidMemoryInPage = false
        for raw in page["runs"] as? [[String: Any]] ?? [] {
            guard uuid(raw["session_id"]) == sid else { throw HarnessAPIError.http(409) }
            guard session.status == "active", (raw["lifecycle_revision"] as? Int ?? 0) >= session.lifecycleRevision else { continue }
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
            run.thinkingStrength = raw["thinking_strength"] as? String ?? run.thinkingStrength
            run.activityKind = rawActivityKind
            run.completedAt = rawCompletedAt
            for message in messages where message.runID == id && ["streaming", "recovering"].contains(message.responseState) && message.responseRevision < run.revision {
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
            let lifecycleBlocked = session.status == "archived" || (raw["lifecycle_revision"] as? Int ?? 0) < session.lifecycleRevision || stopping.contains(runID) || steering.contains(runID) || revision < currentRevision
            if !lifecycleBlocked, let references = payload["memory_references"] as? [[String: Any]], let run = runs.first(where: { $0.id == runID }) {
                if !(LearningMemory.array(run.memoryReferencesJSON) as NSArray).isEqual(to: references) {
                    run.memoryInvalidationRevision = -1
                }
                run.memoryReferencesJSON = json(references)
            }
            let memoryRefs = LearningMemory.array(runs.first(where: { $0.id == runID })?.memoryReferencesJSON ?? "[]")
            if !memoryRefs.isEmpty && memorySessions == nil {
                memorySessions = try context.fetch(FetchDescriptor<AgentSession>())
                memoryKnowledge = try context.fetch(FetchDescriptor<Knowledge>())
            }
            let memoryValid = memoryRefs.isEmpty || LearningMemory.valid(memoryRefs, sessions: memorySessions ?? [], knowledge: memoryKnowledge ?? [])
            // Archiving is a durable UI fence, not only a navigation filter. The
            // service may still replay an event that was already in flight after
            // the stop control was accepted; keep its audit record, but never let
            // it revive visible output, task state, tags, or follow-on effects.
            let blocked = !memoryValid || lifecycleBlocked
            if !memoryValid { invalidMemoryInPage = true; try LearningMemory.fenceInvalidReferences(context: context) }
            if !blocked, let capacity = payload["context_capacity"] as? [String: Any] { session.contextCapacityJSON = json(capacity) }
            if !blocked, payload["invalidate_memory"] as? Bool == true {
                session.memoryContentRevision += 1
                try LearningMemory.fenceInvalidReferences(context: context)
            }
            if !blocked, let lookup = payload["memory_lookup"] as? [String: Any], let run = runs.first(where: { $0.id == runID }) {
                run.memoryLookupJSON = json(lookup)
            }
            if !blocked, let evidence = payload["learning_evidence"] as? [String: Any] { LearningMemory.store(evidence, session: session) }
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
            if !blocked, payload["source_type"] as? String == "agent_generated", (payload["sources"] as? [[String: Any]] ?? []).isEmpty {
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
                task.memoryReferencesJSON = json(payload["memory_references"] ?? memoryRefs)
            }
            for source in !blocked ? (payload["sources"] as? [[String: Any]] ?? []) : [] {
                guard let url = source["url"] as? String else { continue }
                let sources = try context.fetch(FetchDescriptor<SourceReference>())
                let sourceID = uuid(source["source_id"])
                let version = source["version"] as? Int ?? 1
                let saved = sources.first(where: { $0.sessionID == session.id && (sourceID != nil ? $0.id == sourceID : $0.url == url && !url.isEmpty) }) ??
                    SourceReference(sessionID: session.id, taskID: uuid(raw["task_id"]), url: url, title: source["title"] as? String ?? url)
                guard version >= saved.sourceVersion else { continue }
                if version > saved.sourceVersion && !saved.contentSnapshot.isEmpty {
                    var history = LearningMemory.array(saved.versionHistoryJSON)
                    if !history.contains(where: { $0["version"] as? Int == saved.sourceVersion }) {
                        history.append(["version": saved.sourceVersion, "type": saved.sourceType, "title": saved.title,
                                        "content": saved.contentSnapshot, "locator": saved.locator,
                                        "fetched_at": saved.fetchedAt?.ISO8601Format() ?? ""])
                        saved.versionHistoryJSON = json(history)
                    }
                }
                if let sourceID { saved.id = sourceID }
                if !sources.contains(where: { $0.id == saved.id }) { context.insert(saved) }
                saved.sourceType = source["type"] as? String ?? "public_source"
                saved.sourceVersion = version
                saved.title = source["title"] as? String ?? saved.title
                saved.fetchedAt = optionalDate(source["fetched_at"])
                if let locator = source["locator"] as? String { saved.locator = locator }
                if let content = source["content"] as? String, !content.isEmpty { saved.contentSnapshot = content }
            }
            if !blocked, let handoff = payload["handoff"] as? [String: Any], let key = handoff["handoff_id"] as? String {
                let sessions = try context.fetch(FetchDescriptor<AgentSession>())
                if !sessions.contains(where: { $0.handoffID == key }) {
                    let destination = AgentSession(title: String((handoff["goal"] as? String ?? "新学习目标").prefix(28)),
                                                   modePreset: handoff["mode"] as? String ?? "auto", sourceSessionID: session.id)
                    destination.handoffID = key
                    destination.handoffJSON = json(handoff)
                    destination.summaryText = handoff["summary"] as? String ?? ""
                    context.insert(destination)
                    let message = AgentMessage(sessionID: destination.id, role: "user", content: handoff["goal"] as? String ?? "")
                    context.insert(message)
                }
            }
            session.lastSessionEventSeq = seq
        }
        if session.status != "archived" && (page["lifecycle_revision"] as? Int ?? 0) >= session.lifecycleRevision {
            session.runPaused = page["paused"] as? Bool ?? false
        }
        for control in pendingControls {
            if let run = runs.first(where: { $0.id == control.runID }) {
                run.userSummary = control.lastError != nil ? "控制请求尚未送达，操作已保留，将继续重试" : "操作已保存在本机，等待服务确认"
                if ["stop", "cancel_task"].contains(control.action) { run.status = "stopping" }
            }
        }
        for run in runs where steering.contains(run.id) {
            run.status = "adjusting"
            run.userSummary = "已收到补充，正在调整"
        }
        if session.status != "archived" && (page["lifecycle_revision"] as? Int ?? 0) >= session.lifecycleRevision {
            if !pendingControls.contains(where: { $0.action == "set_mode" }), let mode = page["mode"] as? String { session.modePreset = mode }
            if !pendingControls.contains(where: { $0.action == "set_thinking" }), let strength = page["thinking_strength"] as? String {
                session.thinkingStrength = strength
            }
            if let offers = page["capture_offers"] as? [[String: Any]],
               let revision = page["capture_offers_revision"] as? Int, revision >= session.captureOffersRevision {
                session.captureOffersJSON = json(offers)
                session.captureOffersRevision = revision
            }
            if !invalidMemoryInPage {
                let pending = page["pending"] as? [String: Any]
                let target = pending?["target_id"] as? String
                let targetTask = tasks.first { $0.draftTargetID == target || $0.id.uuidString.lowercased() == target }
                let targetRun = runs.first { $0.id.uuidString.lowercased() == target }
                let references = LearningMemory.array(targetTask?.memoryReferencesJSON ?? targetRun?.memoryReferencesJSON ?? "[]")
                let valid = try references.isEmpty || LearningMemory.valid(references, sessions: context.fetch(FetchDescriptor<AgentSession>()), knowledge: context.fetch(FetchDescriptor<Knowledge>()))
                session.pendingOperationJSON = valid ? pending.map(json) : nil
            }
        }
        if let recovery = page["recovery"] as? [String: Any] {
            session.checkpointJSON = try ConversationCheckpoint.merge(recovery, into: session.checkpointJSON,
                                                                      sessionID: sid, cursor: session.lastSessionEventSeq)
        }
        try LearningGoalContinuity.apply(page["goal_ownership"] as? [[String: Any]] ?? [], context: context)
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
