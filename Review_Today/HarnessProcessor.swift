import Foundation
import SwiftData

enum HarnessProcessor {
    @MainActor
    static func tick(context: ModelContext, monitor: AgentServiceMonitor) async {
        let descriptor = FetchDescriptor<LearningTask>(
            sortBy: [SortDescriptor(\.createdAt, order: .forward)]
        )
        guard let tasks = try? context.fetch(descriptor) else { return }
        for task in tasks where !["cancelled", "terminal_failed"].contains(task.status)
            && !(task.status == "completed" && task.lastAckedSeq >= task.lastEventSeq) {
            await process(task, context: context, monitor: monitor)
        }
    }

    @MainActor
    private static func process(
        _ task: LearningTask,
        context: ModelContext,
        monitor: AgentServiceMonitor
    ) async {
        guard monitor.connection == .ready || (task.conversationManaged && monitor.serviceReachable) else {
            if task.status == "accepted" || task.errorCode == "RT.HARNESS.SERVICE_UNAVAILABLE" {
                task.userSummary = monitor.launchStatus
                task.errorCode = "RT.HARNESS.SERVICE_UNAVAILABLE"
                task.updatedAt = .now
                try? context.save()
            }
            return
        }
        guard monitor.keyConfigured else {
            task.userSummary = "输入已保存在本机；配置模型凭证后会继续"
            task.errorCode = "RT.HARNESS.NO_KEY"
            task.updatedAt = .now
            try? context.save()
            return
        }

        if task.status == "accepted" && !task.conversationManaged {
            await submit(task, context: context)
            return
        }

        if let actionID = task.pendingActionID,
           let actionType = task.pendingActionType {
            await submitAction(task, actionID: actionID, type: actionType, context: context)
            return
        }

        await synchronize(task, context: context)
    }

    @MainActor
    private static func submit(_ task: LearningTask, context: ModelContext) async {
        guard let message = fetchMessages(context).first(where: { $0.id == task.inputMessageID }),
              let session = fetchSessions(context).first(where: { $0.id == task.sessionID }) else {
            task.status = "terminal_failed"
            task.errorCode = "RT.HARNESS.LOCAL_CONTEXT_MISSING"
            task.userSummary = "本机上下文不完整，请新建 Session 重试"
            try? context.save()
            return
        }

        task.userSummary = "已保存，正在交给学习教练"
        task.updatedAt = .now
        try? context.save()

        let recent = fetchMessages(context)
            .filter { $0.sessionID == session.id && $0.id != message.id }
            .sorted { $0.createdAt < $1.createdAt }
            .suffix(10)
            .map { (role: $0.role == "assistant" ? "coach" : $0.role, content: $0.content) }
        let knowledge = relevantKnowledgeSummaries(
            for: message.content,
            candidates: fetchKnowledge(context).filter { $0.lifecycle == "active" }
        )

        do {
            let accepted = try await AgentAPI.submitTurn(
                sessionId: session.id,
                messageId: message.clientMessageID ?? message.id,
                content: message.content,
                contentType: message.contentType == "url" ? "url" : "text",
                modePreset: session.modePreset,
                summary: session.summaryText,
                recentMessages: Array(recent),
                knowledgeSummaries: Array(knowledge)
            )
            guard let remoteTaskID = UUID(uuidString: accepted.taskId) else {
                throw HarnessProcessorError.invalidResponse
            }
            let priorID = task.id
            task.id = remoteTaskID
            task.status = accepted.status
            task.stage = "accepted"
            task.userSummary = "学习教练已接收，正在理解你的目标"
            task.errorCode = nil
            task.updatedAt = .now
            if message.taskID == priorID || message.taskID == nil { message.taskID = remoteTaskID }
            try context.save()
            await synchronize(task, context: context)
        } catch {
            handle(error, task: task, fallback: "已保存，服务恢复后自动继续")
            try? context.save()
        }
    }

    @MainActor
    private static func submitAction(
        _ task: LearningTask,
        actionID: UUID,
        type: String,
        context: ModelContext
    ) async {
        do {
            let view = try await AgentAPI.taskAction(
                taskId: task.id,
                actionId: actionID,
                type: type,
                content: task.pendingActionContent ?? ""
            )
            if let rawID = view.runId, let runID = UUID(uuidString: rawID) {
                let runs = (try? context.fetch(FetchDescriptor<AgentRun>())) ?? []
                if !runs.contains(where: { $0.id == runID }) {
                    let run = AgentRun(id: runID, sessionID: task.sessionID)
                    run.taskID = task.id
                    context.insert(run)
                }
                task.conversationManaged = true
            }
            task.pendingActionID = nil
            task.pendingActionType = nil
            task.pendingActionContent = nil
            apply(view, to: task)
            try context.save()
            await synchronize(task, context: context)
        } catch {
            handle(error, task: task, fallback: "操作已保存，连接恢复后继续")
            try? context.save()
        }
    }

    @MainActor
    private static func synchronize(_ task: LearningTask, context: ModelContext) async {
        do {
            let view = try await AgentAPI.getLearningTask(taskId: task.id)
            apply(view, to: task)
            let page = try await AgentAPI.getTaskEvents(taskId: task.id, afterSeq: task.lastEventSeq)
            try persist(page.events, for: task, context: context)
            task.lastEventSeq = max(task.lastEventSeq, page.lastSeq)
            task.updatedAt = .now
            try context.save()

            if view.status == "committing" {
                if task.conversationManaged {
                    let controls = (try? context.fetch(FetchDescriptor<AgentRunControl>())) ?? []
                    let messages = fetchMessages(context)
                    guard !controls.contains(where: { $0.sessionID == task.sessionID && !$0.sent }),
                          !messages.contains(where: { $0.sessionID == task.sessionID && $0.deliveryStatus == "local" }) else { return }
                    let claimed = try await AgentAPI.conversationRequest("/v2/tasks/\(task.id.uuidString.lowercased())/commit-claim", body: [:])
                    let current = try JSONDecoder().decode(AgentAPI.LearningTaskView.self, from: JSONSerialization.data(withJSONObject: claimed))
                    try await commitMemory(current, task: task, context: context)
                } else {
                    try await commitMemory(view, task: task, context: context)
                }
            } else if page.lastSeq > task.lastAckedSeq {
                let acked = try await AgentAPI.ackLearningTask(taskId: task.id, lastEventSeq: page.lastSeq)
                task.lastAckedSeq = page.lastSeq
                apply(acked, to: task)
                try context.save()
            }
        } catch {
            handle(error, task: task, fallback: "进度已保存在本机，稍后继续同步")
            try? context.save()
        }
    }

    @MainActor
    private static func commitMemory(
        _ view: AgentAPI.LearningTaskView,
        task: LearningTask,
        context: ModelContext
    ) async throws {
        guard let payload = view.memoryPackage else { throw HarnessProcessorError.invalidResponse }
        let ids = payload.knowledge.compactMap { UUID(uuidString: $0.id) }
        guard ids.count == payload.knowledge.count, Set(ids).count == ids.count else {
            throw HarnessProcessorError.invalidResponse
        }

        let source: Source
        if let sourceID = task.sourceID,
           let existing = fetchSources(context).first(where: { $0.id == sourceID }) {
            source = existing
            if !view.memorySourceText.isEmpty { source.rawText = view.memorySourceText }
        } else {
            let sourceID = task.sourceID ?? UUID()
            source = Source(id: sourceID, inputType: "text", rawText: view.memorySourceText)
            task.sourceID = sourceID
            context.insert(source)
        }

        try CaptureProcessor.insertKnowledge(payload, into: source, context: context)
        task.memoryCommitted = true
        task.errorCode = nil
        for id in ids where !fetchKnowledgeReferences(context).contains(where: {
            $0.sessionID == task.sessionID && $0.taskID == task.id && $0.knowledgeID == id
        }) {
            context.insert(KnowledgeReference(sessionID: task.sessionID, taskID: task.id, knowledgeID: id))
        }
        try context.save()

        let acked = try await AgentAPI.ackLearningTask(
            taskId: task.id,
            lastEventSeq: task.lastEventSeq,
            knowledgeIds: ids
        )
        task.lastAckedSeq = task.lastEventSeq
        apply(acked, to: task)
        let completionPage = try await AgentAPI.getTaskEvents(taskId: task.id, afterSeq: task.lastEventSeq)
        try persist(completionPage.events, for: task, context: context)
        task.lastEventSeq = max(task.lastEventSeq, completionPage.lastSeq)
        if task.lastEventSeq > task.lastAckedSeq {
            _ = try await AgentAPI.ackLearningTask(
                taskId: task.id,
                lastEventSeq: task.lastEventSeq,
                knowledgeIds: ids
            )
            task.lastAckedSeq = task.lastEventSeq
        }
        try context.save()
    }

    @MainActor
    private static func persist(
        _ events: [AgentAPI.TaskEvent],
        for task: LearningTask,
        context: ModelContext
    ) throws {
        let existingEventIDs = Set(fetchEvents(context).map(\.eventID))
        let existingMessageIDs = Set(fetchMessages(context).map(\.id))
        let existingSources = fetchSourceReferences(context)
        let encoder = JSONEncoder()
        for event in events {
            guard let eventID = UUID(uuidString: event.eventId), !existingEventIDs.contains(eventID),
                  let sessionID = UUID(uuidString: event.sessionId),
                  let taskID = UUID(uuidString: event.taskId) else { continue }
            let actionJSON = event.requiredAction.flatMap { action in
                try? encoder.encode(action)
            }.map { String(decoding: $0, as: UTF8.self) }
            let messageID = event.message.flatMap { UUID(uuidString: $0.messageId) }
            context.insert(TaskEventRecord(
                eventID: eventID,
                sessionID: sessionID,
                taskID: taskID,
                seq: event.seq,
                occurredAt: Self.date(event.occurredAt),
                stage: event.stage,
                state: event.state,
                node: event.node,
                userSummary: event.userSummary,
                detailSummary: event.detailSummary,
                attempt: event.attempt,
                durationMS: event.durationMS,
                errorCode: event.errorCode,
                recoveryAction: event.recoveryAction,
                requiredActionJSON: actionJSON,
                messageID: messageID
            ))
            if let message = event.message,
               let id = messageID,
               !existingMessageIDs.contains(id) {
                context.insert(AgentMessage(
                    id: id,
                    sessionID: sessionID,
                    taskID: taskID,
                    role: message.role == "coach" ? "assistant" : message.role,
                    content: message.content,
                    createdAt: Self.date(message.createdAt),
                    deliveryStatus: "received"
                ))
            }
            for source in event.payload.sourcePack where !existingSources.contains(where: {
                $0.sessionID == sessionID && $0.taskID == taskID && $0.url == source.url
            }) {
                context.insert(SourceReference(
                    sessionID: sessionID,
                    taskID: taskID,
                    url: source.url,
                    title: source.title.isEmpty ? source.url : source.title,
                    evidenceState: "unverified",
                    locator: source.snippet
                ))
            }
        }
    }

    @MainActor
    static func queueAction(_ task: LearningTask, type: String, content: String, context: ModelContext) {
        task.pendingActionID = UUID()
        task.pendingActionType = type
        task.pendingActionContent = content
        task.requiredActionType = nil
        task.requiredActionPrompt = nil
        task.requiredActionOptionsJSON = nil
        task.userSummary = "已收到你的反馈，正在继续"
        task.updatedAt = .now
        try? context.save()
    }

    @MainActor
    static func apply(_ view: AgentAPI.LearningTaskView, to task: LearningTask) {
        task.understanding = view.understanding ?? "unknown"
        task.mode = view.mode
        task.status = view.status
        task.stage = view.stage
        task.userSummary = view.userSummary
        task.retryCount = view.retryCount
        task.errorCode = view.errorCode
        task.resultSummary = view.resultSummary
        task.lastAckedSeq = max(task.lastAckedSeq, view.lastAckedSeq)
        task.requiredActionType = view.requiredAction?.type
        task.requiredActionPrompt = view.requiredAction?.prompt
        if let options = view.requiredAction?.options,
           let data = try? JSONEncoder().encode(options) {
            task.requiredActionOptionsJSON = String(decoding: data, as: UTF8.self)
        } else {
            task.requiredActionOptionsJSON = nil
        }
        task.updatedAt = .now
    }

    @MainActor
    private static func handle(_ error: Error, task: LearningTask, fallback: String) {
        let code: String
        if error is HarnessProcessorError {
            code = "RT.HARNESS.STRUCTURE_INVALID"
            task.status = "retryable_failed"
        } else {
            code = HarnessAPIError.code(for: error)
            if code != "RT.HARNESS.SERVICE_UNAVAILABLE" && code != "RT.HARNESS.NO_KEY" {
                task.status = "retryable_failed"
                task.retryCount += 1
            }
        }
        task.errorCode = code
        task.userSummary = fallback
        task.updatedAt = .now
    }

    private static func date(_ raw: String) -> Date {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: raw) ?? ISO8601DateFormatter().date(from: raw) ?? .now
    }

    static func relevantKnowledgeSummaries(for query: String, candidates: [Knowledge]) -> [String] {
        let queryTerms = searchTerms(query)
        guard !queryTerms.isEmpty else { return [] }
        return candidates.compactMap { knowledge -> (Int, String)? in
            let searchable = [knowledge.title, knowledge.theme, knowledge.learningGoal, knowledge.explanation]
                .joined(separator: " ")
                .lowercased()
            let terms = searchTerms(searchable)
            let overlap = queryTerms.intersection(terms).count
            let exactBoost = [knowledge.title, knowledge.theme]
                .filter { !$0.isEmpty && query.localizedCaseInsensitiveContains($0) }
                .count * 4
            let score = overlap + exactBoost
            guard score > 0 else { return nil }
            return (score, "\(knowledge.title)：\(knowledge.learningGoal)")
        }
        .sorted { lhs, rhs in lhs.0 == rhs.0 ? lhs.1 < rhs.1 : lhs.0 > rhs.0 }
        .prefix(5)
        .map(\.1)
    }

    private static func searchTerms(_ text: String) -> Set<String> {
        let lowered = text.lowercased()
        let words = lowered.split { !$0.isLetter && !$0.isNumber }.map(String.init)
        var terms = Set(words.filter { $0.count >= 2 })
        let compact = lowered.filter { $0.isLetter || $0.isNumber }
        let characters = Array(compact)
        if characters.count >= 2 {
            for index in 0 ..< characters.count - 1 {
                terms.insert(String(characters[index ... index + 1]))
            }
        }
        return terms
    }

    @MainActor private static func fetchMessages(_ context: ModelContext) -> [AgentMessage] {
        (try? context.fetch(FetchDescriptor<AgentMessage>())) ?? []
    }
    @MainActor private static func fetchSessions(_ context: ModelContext) -> [AgentSession] {
        (try? context.fetch(FetchDescriptor<AgentSession>())) ?? []
    }
    @MainActor private static func fetchKnowledge(_ context: ModelContext) -> [Knowledge] {
        (try? context.fetch(FetchDescriptor<Knowledge>())) ?? []
    }
    @MainActor private static func fetchEvents(_ context: ModelContext) -> [TaskEventRecord] {
        (try? context.fetch(FetchDescriptor<TaskEventRecord>())) ?? []
    }
    @MainActor private static func fetchSources(_ context: ModelContext) -> [Source] {
        (try? context.fetch(FetchDescriptor<Source>())) ?? []
    }
    @MainActor private static func fetchKnowledgeReferences(_ context: ModelContext) -> [KnowledgeReference] {
        (try? context.fetch(FetchDescriptor<KnowledgeReference>())) ?? []
    }
    @MainActor private static func fetchSourceReferences(_ context: ModelContext) -> [SourceReference] {
        (try? context.fetch(FetchDescriptor<SourceReference>())) ?? []
    }
}

private enum HarnessProcessorError: Error {
    case invalidResponse
}
