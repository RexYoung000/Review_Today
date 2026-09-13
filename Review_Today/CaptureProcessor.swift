import Foundation
import SwiftData

enum CaptureProcessor {
    @MainActor
    static func tick(context: ModelContext, monitor: AgentServiceMonitor) async {
        let activeStatuses = ["queued", "retryable_failed", "uploading", "processing", "committing"]
        let descriptor = FetchDescriptor<CaptureTask>(
            predicate: #Predicate {
                activeStatuses.contains($0.status) || ($0.status == "completed" && !$0.localCommitDone)
            },
            sortBy: [SortDescriptor(\.createdAt, order: .forward)]
        )
        guard let tasks = try? context.fetch(descriptor) else { return }
        for task in tasks {
            await process(task, context: context, monitor: monitor)
        }
    }

    @MainActor
    private static func process(_ task: CaptureTask, context: ModelContext, monitor: AgentServiceMonitor) async {
        switch task.status {
        case "queued", "retryable_failed":
            guard monitor.connection == .ready, monitor.keyConfigured else {
                let status = monitor.connection == .ready
                    ? String(localized: "已保存，Key 未配置")
                    : String(localized: "已保存，服务恢复后处理")
                guard task.userStatus != status else { return }
                task.userStatus = status
                task.updatedAt = .now
                appendStatus(task.userStatus, to: task)
                try? context.save()
                return
            }
            if task.status == "retryable_failed" {
                let delay = Double(1 << min(task.retryCount, 5))
                if Date.now.timeIntervalSince(task.updatedAt) < delay { return }
            }
            await submit(task, context: context)
        case "uploading", "processing":
            await poll(task, context: context)
        case "committing":
            await commitAndAck(task, context: context)
        case "completed" where !task.localCommitDone:
            await commitAndAck(task, context: context)
        default:
            break
        }
    }

    @MainActor
    private static func submit(_ task: CaptureTask, context: ModelContext) async {
        guard let source = task.source else { return }
        task.status = "uploading"
        task.userStatus = String(localized: "正在提交")
        task.updatedAt = .now
        appendStatus(task.userStatus, to: task)
        try? context.save()
        do {
            let view = try await AgentAPI.submitCapture(
                taskId: task.id,
                sourceId: source.id,
                rawText: source.rawText,
                primaryLanguage: UserLanguage.primaryCode,
                inputType: source.inputType,
                url: source.url,
                audioBase64: audioBase64(from: source),
                audioFormat: "m4a"
            )
            apply(view, to: task)
            try context.save()
            if task.status == "committing" || (task.status == "completed" && !task.localCommitDone) {
                await commitAndAck(task, context: context)
            }
        } catch {
            task.status = "retryable_failed"
            task.retryCount += 1
            task.errorCode = Self.errorCode(for: error)
            task.userStatus = String(localized: "需要重试")
            task.updatedAt = .now
            appendStatus(task.userStatus, to: task)
            try? context.save()
        }
    }

    @MainActor
    private static func poll(_ task: CaptureTask, context: ModelContext) async {
        do {
            let view = try await AgentAPI.getCapture(taskId: task.id)
            apply(view, to: task)
            try context.save()
            if task.status == "committing" || (task.status == "completed" && !task.localCommitDone) {
                await commitAndAck(task, context: context)
            }
        } catch {
            if case CaptureAPIError.http(404) = error {
                task.status = "queued"
                task.userStatus = String(localized: "已保存，等待处理")
                task.updatedAt = .now
                try? context.save()
                return
            }
            if case CaptureAPIError.server(let code, _) = error, code == "RT.CAPTURE.UNKNOWN_TASK" {
                task.status = "queued"
                task.userStatus = String(localized: "已保存，等待处理")
                task.updatedAt = .now
                try? context.save()
                return
            }
            task.status = "retryable_failed"
            task.retryCount += 1
            task.errorCode = Self.errorCode(for: error)
            task.userStatus = String(localized: "需要重试")
            task.updatedAt = .now
            try? context.save()
        }
    }

    @MainActor
    private static func commitAndAck(_ task: CaptureTask, context: ModelContext) async {
        do {
            let view = try await AgentAPI.getCapture(taskId: task.id)
            apply(view, to: task)
            guard let result = view.result, let source = task.source else {
                task.status = "retryable_failed"
                task.errorCode = "RT.CAPTURE.STRUCTURE_INVALID"
                task.userStatus = String(localized: "需要重试")
                task.updatedAt = .now
                appendStatus(task.userStatus, to: task)
                try? context.save()
                return
            }

            let ids = result.knowledge.compactMap { UUID(uuidString: $0.id) }
            guard ids.count == result.knowledge.count, Set(ids).count == ids.count else {
                task.status = "retryable_failed"
                task.errorCode = "RT.CAPTURE.STRUCTURE_INVALID"
                task.userStatus = String(localized: "需要重试")
                task.updatedAt = .now
                appendStatus(task.userStatus, to: task)
                try? context.save()
                return
            }

            do {
                try insertKnowledge(result, into: source, context: context)
                task.localCommitDone = true
                task.errorCode = nil
                task.updatedAt = .now
                try context.save()
            } catch {
                context.rollback()
                task.status = "committing"
                task.errorCode = "RT.CAPTURE.LOCAL_SAVE_FAILED"
                task.userStatus = String(localized: "本机保存失败，稍后重试")
                task.updatedAt = .now
                appendStatus(task.userStatus, to: task)
                try? context.save()
                return
            }

            let localIDs = Set((try? context.fetch(FetchDescriptor<Knowledge>()))?
                .filter { $0.source?.id == source.id }
                .map(\.id) ?? [])
            guard ids.allSatisfy(localIDs.contains) else {
                task.status = "committing"
                task.errorCode = "RT.CAPTURE.LOCAL_SAVE_FAILED"
                task.userStatus = String(localized: "本机保存失败，稍后重试")
                task.updatedAt = .now
                appendStatus(task.userStatus, to: task)
                try? context.save()
                return
            }

            do {
                let acked = try await AgentAPI.ackCapture(taskId: task.id, knowledgeIds: ids)
                apply(acked, to: task)
                if acked.status == "completed", let path = source.audioPath {
                    try? FileManager.default.removeItem(atPath: path)
                    source.audioPath = nil
                }
                try context.save()
            } catch {
                task.status = "committing"
                task.errorCode = Self.errorCode(for: error, fallback: "RT.CAPTURE.ACK_FAILED")
                task.userStatus = String(localized: "已保存，等待确认")
                task.updatedAt = .now
                appendStatus(task.userStatus, to: task)
                try? context.save()
            }
        } catch {
            task.status = "committing"
            task.errorCode = Self.errorCode(for: error, fallback: "RT.CAPTURE.SERVICE_UNAVAILABLE")
            task.userStatus = String(localized: "等待服务确认")
            task.updatedAt = .now
            appendStatus(task.userStatus, to: task)
            try? context.save()
        }
    }

    @MainActor
    static func apply(_ view: AgentAPI.CaptureView, to task: CaptureTask) {
        task.status = view.status
        task.userStatus = view.userStatus
        task.errorCode = view.errorCode
        task.intent = view.intent
        task.updatedAt = .now
        appendStatus(view.userStatus, to: task)
        if !view.events.isEmpty,
           let data = try? JSONSerialization.data(withJSONObject: view.events.map { event in
            [
                "seq": event.seq ?? 0,
                "event_type": event.eventType ?? "",
                "node": event.node ?? "",
            ] as [String: Any]
           }) {
            task.eventsJSON = String(data: data, encoding: .utf8)
        }
        if !view.sourceCandidates.isEmpty {
            let arr = view.sourceCandidates.map { ["url": $0.url, "title": $0.title, "snippet": $0.snippet] }
            if let data = try? JSONSerialization.data(withJSONObject: arr) {
                task.payloadJSON = String(data: data, encoding: .utf8)
            }
        }
        if let receipt = view.receipt,
           let data = try? JSONEncoder().encode(ReceiptStore(receipt: receipt)) {
            task.receiptJSON = String(data: data, encoding: .utf8)
        }
    }

    @MainActor
    static func appendStatus(_ status: String, to task: CaptureTask) {
        let trimmed = status.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        var trail = CaptureProgress.steps(from: task.statusTrailJSON)
        if trail.last != trimmed {
            trail.append(trimmed)
            if let data = try? JSONEncoder().encode(trail) {
                task.statusTrailJSON = String(data: data, encoding: .utf8)
            }
        }
    }

    @MainActor
    static func insertKnowledge(
        _ payload: AgentAPI.ExtractPayload,
        into source: Source,
        context: ModelContext
    ) throws {
        guard !payload.knowledge.isEmpty else { throw CaptureProcessorError.invalidPayload }
        let encoder = JSONEncoder()
        var seenIDs = Set<UUID>()

        for draft in payload.knowledge {
            guard let id = UUID(uuidString: draft.id), seenIDs.insert(id).inserted else {
                throw CaptureProcessorError.invalidPayload
            }
            let specData = try encoder.encode(draft.scoringSpec)
            let specJSON = String(data: specData, encoding: .utf8) ?? "{}"
            let item: Knowledge
            if let existing = source.knowledgeItems.first(where: { $0.id == id }) {
                item = existing
            } else if let existing = try context.fetch(FetchDescriptor<Knowledge>()).first(where: { $0.id == id }) {
                item = existing
            } else {
                item = Knowledge(
                    id: id,
                    learningGoal: draft.learningGoal,
                    knowledgeType: draft.knowledgeType,
                    theme: draft.theme,
                    contentLanguage: draft.contentLanguage,
                    questionLanguage: draft.questionLanguage,
                    answerLanguage: draft.answerLanguage,
                    evidenceExcerpt: draft.evidenceExcerpt,
                    evidenceLocator: draft.evidenceLocator,
                    title: draft.title,
                    explanation: draft.explanation
                )
                context.insert(item)
            }

            item.learningGoal = draft.learningGoal
            item.knowledgeType = draft.knowledgeType
            item.theme = draft.theme
            item.contentLanguage = draft.contentLanguage
            item.questionLanguage = draft.questionLanguage
            item.answerLanguage = draft.answerLanguage
            item.evidenceExcerpt = draft.evidenceExcerpt
            item.evidenceLocator = draft.evidenceLocator
            item.title = draft.title
            item.explanation = draft.explanation
            item.source = source

            if let fsrs = try context.fetch(FetchDescriptor<FsrsState>()).first(where: { $0.knowledgeId == id }) {
                _ = fsrs
            } else {
                context.insert(FsrsState(knowledgeId: id, dueAt: item.dueAt))
            }

            for questionDraft in draft.questions {
                if let question = item.questions.first(where: { $0.variantIndex == questionDraft.variantIndex }) {
                    question.knowledgeVersion = item.version
                    question.promptText = questionDraft.promptText
                    question.scoringSpecJSON = specJSON
                } else {
                    let question = Question(
                        knowledgeVersion: item.version,
                        variantIndex: questionDraft.variantIndex,
                        promptText: questionDraft.promptText,
                        scoringSpecJSON: specJSON
                    )
                    question.knowledge = item
                    context.insert(question)
                }
            }
        }
        source.attribution = payload.attribution
    }

    private static func errorCode(for error: Error, fallback: String = "RT.CAPTURE.MODEL_FAILED") -> String {
        if error is CaptureProcessorError {
            return "RT.CAPTURE.STRUCTURE_INVALID"
        }
        return CaptureAPIError.code(for: error, fallback: fallback)
    }

    private static func audioBase64(from source: Source) -> String? {
        guard let path = source.audioPath else { return nil }
        return try? Data(contentsOf: URL(fileURLWithPath: path)).base64EncodedString()
    }
}

private enum CaptureProcessorError: Error {
    case invalidPayload
}

private struct ReceiptStore: Codable {
    var understoodAs: String
    var theme: String
    var knowledgeCount: Int
    var attribution: String

    init(receipt: AgentAPI.Receipt) {
        understoodAs = receipt.understoodAs
        theme = receipt.theme
        knowledgeCount = receipt.knowledgeCount
        attribution = receipt.attribution
    }
}
