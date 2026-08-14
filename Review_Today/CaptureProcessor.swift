import Foundation
import SwiftData

enum CaptureProcessor {
    @MainActor
    static func tick(context: ModelContext, monitor: AgentServiceMonitor) async {
        let descriptor = FetchDescriptor<CaptureTask>(
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
                task.userStatus = monitor.connection == .ready
                    ? String(localized: "已保存，Key 未配置")
                    : String(localized: "已保存，服务恢复后处理")
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
        } catch {
            task.status = "retryable_failed"
            task.retryCount += 1
            task.errorCode = "RT.CAPTURE.MODEL_FAILED"
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
            if task.status == "committing" {
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
            guard let result = view.result, let source = task.source else { return }
            if !task.localCommitDone {
                source.attribution = result.attribution
                try insertKnowledge(result, into: source, context: context)
                task.localCommitDone = true
                try context.save()
            }
            let ids = source.knowledgeItems.map(\.id)
            let acked = try await AgentAPI.ackCapture(taskId: task.id, knowledgeIds: ids)
            apply(acked, to: task)
            if acked.status == "completed", let path = source.audioPath {
                try? FileManager.default.removeItem(atPath: path)
                source.audioPath = nil
            }
            try context.save()
        } catch {
            task.userStatus = String(localized: "正在写入")
            task.updatedAt = .now
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
    private static func insertKnowledge(
        _ payload: AgentAPI.ExtractPayload,
        into source: Source,
        context: ModelContext
    ) throws {
        let encoder = JSONEncoder()
        for draft in payload.knowledge {
            guard let id = UUID(uuidString: draft.id) else { continue }
            let item = Knowledge(
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
            item.source = source
            context.insert(FsrsState(knowledgeId: item.id, dueAt: item.dueAt))
            let specData = try encoder.encode(draft.scoringSpec)
            let specJSON = String(data: specData, encoding: .utf8) ?? "{}"
            for question in draft.questions {
                let model = Question(
                    variantIndex: question.variantIndex,
                    promptText: question.promptText,
                    scoringSpecJSON: specJSON
                )
                model.knowledge = item
                context.insert(model)
            }
            context.insert(item)
        }
    }

    private static func audioBase64(from source: Source) -> String? {
        guard let path = source.audioPath else { return nil }
        return try? Data(contentsOf: URL(fileURLWithPath: path)).base64EncodedString()
    }
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
