import Foundation

enum AgentAPI {
    static let base = AppRuntime.current.serviceURL

    struct CaptureView: Decodable {
        var taskId: String
        var status: String
        var userStatus: String
        var errorCode: String?
        var receipt: Receipt?
        var result: ExtractPayload?
        var sourceId: String?
        var intent: String?
        var sourceCandidates: [SourceCandidate]
        var verifyReason: String?
        var events: [AgentEvent]

        enum CodingKeys: String, CodingKey {
            case taskId = "task_id"
            case status
            case userStatus = "user_status"
            case errorCode = "error_code"
            case receipt
            case result
            case sourceId = "source_id"
            case intent
            case sourceCandidates = "source_candidates"
            case verifyReason = "verify_reason"
            case events
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            taskId = try c.decode(String.self, forKey: .taskId)
            status = try c.decode(String.self, forKey: .status)
            userStatus = try c.decode(String.self, forKey: .userStatus)
            errorCode = try c.decodeIfPresent(String.self, forKey: .errorCode)
            receipt = try c.decodeIfPresent(Receipt.self, forKey: .receipt)
            result = try c.decodeIfPresent(ExtractPayload.self, forKey: .result)
            sourceId = try c.decodeIfPresent(String.self, forKey: .sourceId)
            intent = try c.decodeIfPresent(String.self, forKey: .intent)
            sourceCandidates = try c.decodeIfPresent([SourceCandidate].self, forKey: .sourceCandidates) ?? []
            verifyReason = try c.decodeIfPresent(String.self, forKey: .verifyReason)
            events = try c.decodeIfPresent([AgentEvent].self, forKey: .events) ?? []
        }
    }

    struct SourceCandidate: Decodable, Identifiable {
        var url: String
        var title: String
        var snippet: String
        var id: String { url }
    }

    struct AgentEvent: Decodable {
        var seq: Int?
        var eventType: String?
        var node: String?
        enum CodingKeys: String, CodingKey {
            case seq
            case eventType = "event_type"
            case node
        }
    }

    struct Receipt: Decodable {
        var understoodAs: String
        var theme: String
        var knowledgeCount: Int
        var attribution: String

        enum CodingKeys: String, CodingKey {
            case understoodAs = "understood_as"
            case theme
            case knowledgeCount = "knowledge_count"
            case attribution
        }
    }

    struct ExtractPayload: Decodable {
        var understoodAs: String
        var theme: String
        var attribution: String
        var riskFlagged: Bool
        var riskReason: String
        var knowledge: [KnowledgeDraft]

        enum CodingKeys: String, CodingKey {
            case understoodAs = "understood_as"
            case theme
            case attribution
            case riskFlagged = "risk_flagged"
            case riskReason = "risk_reason"
            case knowledge
        }
    }

    struct KnowledgeDraft: Decodable {
        var id: String
        var learningGoal: String
        var knowledgeType: String
        var theme: String
        var contentLanguage: String
        var questionLanguage: String
        var answerLanguage: String
        var evidenceExcerpt: String
        var evidenceLocator: String
        var title: String
        var explanation: String
        var scoringSpec: ScoringSpec
        var questions: [QuestionDraft]

        enum CodingKeys: String, CodingKey {
            case id
            case learningGoal = "learning_goal"
            case knowledgeType = "knowledge_type"
            case theme
            case contentLanguage = "content_language"
            case questionLanguage = "question_language"
            case answerLanguage = "answer_language"
            case evidenceExcerpt = "evidence_excerpt"
            case evidenceLocator = "evidence_locator"
            case title
            case explanation
            case scoringSpec = "scoring_spec"
            case questions
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            id = try container.decode(String.self, forKey: .id)
            learningGoal = try container.decode(String.self, forKey: .learningGoal)
            knowledgeType = try container.decode(String.self, forKey: .knowledgeType)
            theme = try container.decode(String.self, forKey: .theme)
            contentLanguage = try container.decode(String.self, forKey: .contentLanguage)
            questionLanguage = try container.decode(String.self, forKey: .questionLanguage)
            answerLanguage = try container.decode(String.self, forKey: .answerLanguage)
            evidenceExcerpt = try container.decode(String.self, forKey: .evidenceExcerpt)
            evidenceLocator = try container.decodeIfPresent(String.self, forKey: .evidenceLocator) ?? ""
            title = try container.decodeIfPresent(String.self, forKey: .title) ?? ""
            explanation = try container.decodeIfPresent(String.self, forKey: .explanation) ?? ""
            scoringSpec = try container.decode(ScoringSpec.self, forKey: .scoringSpec)
            questions = try container.decode([QuestionDraft].self, forKey: .questions)
        }
    }

    struct ScoringSpec: Codable {
        var learningGoal: String
        var mustCover: [String]
        var acceptableParaphrases: [String]
        var commonMisconceptions: [String]
        var evidence: String
        var orderRules: String

        enum CodingKeys: String, CodingKey {
            case learningGoal = "learning_goal"
            case mustCover = "must_cover"
            case acceptableParaphrases = "acceptable_paraphrases"
            case commonMisconceptions = "common_misconceptions"
            case evidence
            case orderRules = "order_rules"
        }
    }

    struct QuestionDraft: Decodable {
        var variantIndex: Int
        var promptText: String

        enum CodingKeys: String, CodingKey {
            case variantIndex = "variant_index"
            case promptText = "prompt_text"
        }
    }

    struct APIError: Decodable {
        var errorCode: String
        var message: String

        enum CodingKeys: String, CodingKey {
            case errorCode = "error_code"
            case message
        }
    }

    // MARK: Harness V2

    struct SessionTurnAccepted: Decodable {
        var messageId: String
        var taskId: String
        var status: String
        var nextEventSeq: Int

        enum CodingKeys: String, CodingKey {
            case messageId = "message_id"
            case taskId = "task_id"
            case status
            case nextEventSeq = "next_event_seq"
        }
    }

    struct RequiredAction: Codable {
        var type: String
        var prompt: String
        var options: [String]
    }

    struct HarnessMessage: Decodable {
        var messageId: String
        var role: String
        var content: String
        var createdAt: String

        enum CodingKeys: String, CodingKey {
            case messageId = "message_id"
            case role, content
            case createdAt = "created_at"
        }
    }

    struct TaskEvent: Decodable {
        var eventId: String
        var sessionId: String
        var taskId: String
        var seq: Int
        var occurredAt: String
        var stage: String
        var state: String
        var node: String
        var userSummary: String
        var detailSummary: String
        var attempt: Int
        var durationMS: Int?
        var errorCode: String?
        var recoveryAction: String?
        var requiredAction: RequiredAction?
        var message: HarnessMessage?
        var payload: EventPayload

        enum CodingKeys: String, CodingKey {
            case eventId = "event_id"
            case sessionId = "session_id"
            case taskId = "task_id"
            case seq
            case occurredAt = "occurred_at"
            case stage, state, node
            case userSummary = "user_summary"
            case detailSummary = "detail_summary"
            case attempt
            case durationMS = "duration_ms"
            case errorCode = "error_code"
            case recoveryAction = "recovery_action"
            case requiredAction = "required_action"
            case message, payload
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            eventId = try container.decode(String.self, forKey: .eventId)
            sessionId = try container.decode(String.self, forKey: .sessionId)
            taskId = try container.decode(String.self, forKey: .taskId)
            seq = try container.decode(Int.self, forKey: .seq)
            occurredAt = try container.decode(String.self, forKey: .occurredAt)
            stage = try container.decode(String.self, forKey: .stage)
            state = try container.decode(String.self, forKey: .state)
            node = try container.decode(String.self, forKey: .node)
            userSummary = try container.decode(String.self, forKey: .userSummary)
            detailSummary = try container.decodeIfPresent(String.self, forKey: .detailSummary) ?? ""
            attempt = try container.decodeIfPresent(Int.self, forKey: .attempt) ?? 1
            durationMS = try container.decodeIfPresent(Int.self, forKey: .durationMS)
            errorCode = try container.decodeIfPresent(String.self, forKey: .errorCode)
            recoveryAction = try container.decodeIfPresent(String.self, forKey: .recoveryAction)
            requiredAction = try container.decodeIfPresent(RequiredAction.self, forKey: .requiredAction)
            message = try container.decodeIfPresent(HarnessMessage.self, forKey: .message)
            payload = try container.decodeIfPresent(EventPayload.self, forKey: .payload) ?? EventPayload()
        }
    }

    struct EventPayload: Decodable {
        var sourcePack: [SourcePackItem] = []

        enum CodingKeys: String, CodingKey { case sourcePack = "source_pack" }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            sourcePack = try container.decodeIfPresent([SourcePackItem].self, forKey: .sourcePack) ?? []
        }

        init() {}
    }

    struct SourcePackItem: Decodable {
        var url: String
        var title: String
        var snippet: String
    }

    struct TaskEventPage: Decodable {
        var taskId: String
        var events: [TaskEvent]
        var lastSeq: Int

        enum CodingKeys: String, CodingKey {
            case taskId = "task_id"
            case events
            case lastSeq = "last_seq"
        }
    }

    struct LearningTaskView: Decodable {
        var goalOwnershipJSON: String?
        var lifecycleRevision: Int?
        var learningPlanJSON: String?
        var learningOutcomeJSON: String?
        var sourcesJSON: String?
        var memoryReferencesJSON: String?
        var draftTargetID: String?
        var runId: String?
        var understanding: String?
        var taskId: String
        var sessionId: String
        var clientMessageId: String
        var mode: String
        var status: String
        var stage: String
        var userSummary: String
        var retryCount: Int
        var errorCode: String?
        var requiredAction: RequiredAction?
        var resultSummary: String
        var lastEventSeq: Int
        var lastAckedSeq: Int
        var memoryPackage: ExtractPayload?
        var memorySourceText: String

        enum CodingKeys: String, CodingKey {
            case goalOwnershipJSON = "goal_ownership_json"
            case lifecycleRevision = "lifecycle_revision"
            case learningPlanJSON = "learning_plan_json"
            case learningOutcomeJSON = "learning_outcome_json"
            case sourcesJSON = "sources_json"
            case memoryReferencesJSON = "memory_references_json"
            case draftTargetID = "draft_target_id"
            case runId = "run_id"
            case understanding
            case taskId = "task_id"
            case sessionId = "session_id"
            case clientMessageId = "client_message_id"
            case mode, status, stage
            case userSummary = "user_summary"
            case retryCount = "retry_count"
            case errorCode = "error_code"
            case requiredAction = "required_action"
            case resultSummary = "result_summary"
            case lastEventSeq = "last_event_seq"
            case lastAckedSeq = "last_acked_seq"
            case memoryPackage = "memory_package"
            case memorySourceText = "memory_source_text"
        }
    }

    static func submitCapture(
        taskId: UUID,
        sourceId: UUID,
        rawText: String,
        primaryLanguage: String,
        inputType: String = "text",
        url: String? = nil,
        audioBase64: String? = nil,
        audioFormat: String = "m4a"
    ) async throws -> CaptureView {
        var request = URLRequest(url: base.appending(path: "/v1/capture/tasks"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60
        var body: [String: String] = [
            "task_id": taskId.uuidString.lowercased(),
            "source_id": sourceId.uuidString.lowercased(),
            "input_type": inputType,
            "raw_text": rawText,
            "primary_language": primaryLanguage,
        ]
        if let url, !url.isEmpty { body["url"] = url }
        if let audioBase64, !audioBase64.isEmpty {
            body["audio_base64"] = audioBase64
            body["audio_format"] = audioFormat
        }
        request.httpBody = try JSONEncoder().encode(body)
        return try await send(request)
    }

    static func captureAction(
        taskId: UUID,
        action: String,
        rawText: String = "",
        url: String = "",
        urls: [String] = [],
        transcript: String = ""
    ) async throws -> CaptureView {
        var request = URLRequest(url: base.appending(path: "/v1/capture/tasks/\(taskId.uuidString.lowercased())/actions"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 45
        let body: [String: Any] = [
            "action": action,
            "raw_text": rawText,
            "url": url,
            "urls": urls,
            "transcript": transcript,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request)
    }

    struct GradeResult: Decodable {
        var attemptId: String
        var agentGrade: String
        var briefFeedback: String
        enum CodingKeys: String, CodingKey {
            case attemptId = "attempt_id"
            case agentGrade = "agent_grade"
            case briefFeedback = "brief_feedback"
        }
    }

    static func grade(
        attemptId: UUID,
        promptText: String,
        scoringSpec: ScoringSpec,
        answerText: String,
        hintUsed: Bool,
        primaryLanguage: String
    ) async throws -> GradeResult {
        var request = URLRequest(url: base.appending(path: "/v1/review/grade"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60
        let spec: [String: Any] = [
            "learning_goal": scoringSpec.learningGoal,
            "must_cover": scoringSpec.mustCover,
            "acceptable_paraphrases": scoringSpec.acceptableParaphrases,
            "common_misconceptions": scoringSpec.commonMisconceptions,
            "evidence": scoringSpec.evidence,
            "order_rules": scoringSpec.orderRules,
        ]
        let body: [String: Any] = [
            "attempt_id": attemptId.uuidString.lowercased(),
            "prompt_text": promptText,
            "scoring_spec": spec,
            "answer_text": answerText,
            "hint_used": hintUsed,
            "primary_language": primaryLanguage,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        try AppRuntime.current.requireSending()
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ... 299).contains(code) else {
            if let fastapi = try? JSONDecoder().decode(FastAPIError.self, from: data) {
                throw ReviewAPIError.server(
                    code: fastapi.detail.errorCode,
                    message: fastapi.detail.message
                )
            }
            throw ReviewAPIError.http(code)
        }
        return try JSONDecoder().decode(GradeResult.self, from: data)
    }

    static func ackAttempt(attemptId: UUID) async throws {
        var request = URLRequest(url: base.appending(path: "/v1/review/attempts/\(attemptId.uuidString.lowercased())/ack"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 10
        request.httpBody = try JSONEncoder().encode(["attempt_id": attemptId.uuidString.lowercased()])
        try AppRuntime.current.requireSending()
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ... 299).contains(code) else {
            if let fastapi = try? JSONDecoder().decode(FastAPIError.self, from: data) {
                throw ReviewAPIError.server(
                    code: fastapi.detail.errorCode,
                    message: fastapi.detail.message
                )
            }
            throw ReviewAPIError.http(code)
        }
    }

    static func reviewErrorCode(
        for error: Error,
        fallback: String = "RT.REVIEW.GRADE_FAILED"
    ) -> String {
        if let reviewError = error as? ReviewAPIError {
            return reviewError.errorCode
        }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .timedOut, .cannotConnectToHost, .networkConnectionLost,
                 .notConnectedToInternet, .dnsLookupFailed, .cannotFindHost:
                return "RT.REVIEW.SERVICE_UNAVAILABLE"
            default:
                break
            }
        }
        return fallback
    }

    static func getCapture(taskId: UUID) async throws -> CaptureView {
        var request = URLRequest(url: base.appending(path: "/v1/capture/tasks/\(taskId.uuidString.lowercased())"))
        request.timeoutInterval = 10
        return try await send(request)
    }

    static func ackCapture(taskId: UUID, knowledgeIds: [UUID]) async throws -> CaptureView {
        var request = URLRequest(url: base.appending(path: "/v1/capture/tasks/\(taskId.uuidString.lowercased())/ack"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 10
        let body = ["knowledge_ids": knowledgeIds.map { $0.uuidString.lowercased() }]
        request.httpBody = try JSONEncoder().encode(body)
        return try await send(request)
    }

    static func submitTurn(
        sessionId: UUID,
        messageId: UUID,
        content: String,
        contentType: String,
        modePreset: String,
        summary: String,
        recentMessages: [(role: String, content: String)],
        knowledgeSummaries: [String]
    ) async throws -> SessionTurnAccepted {
        var request = URLRequest(url: base.appending(path: "/v2/sessions/\(sessionId.uuidString.lowercased())/turns"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 15
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "client_message_id": messageId.uuidString.lowercased(),
            "content": content,
            "content_type": contentType,
            "mode_preset": modePreset,
            "primary_language": UserLanguage.primaryCode,
            "context": [
                "summary": summary,
                "recent_messages": recentMessages.map { ["role": $0.role, "content": $0.content] },
                "knowledge_summaries": knowledgeSummaries,
            ],
        ])
        return try await sendHarness(request, as: SessionTurnAccepted.self)
    }

    static func getLearningTask(taskId: UUID) async throws -> LearningTaskView {
        var request = URLRequest(url: base.appending(path: "/v2/tasks/\(taskId.uuidString.lowercased())"))
        request.timeoutInterval = 10
        return try await sendHarness(request, as: LearningTaskView.self)
    }

    static func getTaskEvents(taskId: UUID, afterSeq: Int) async throws -> TaskEventPage {
        var components = URLComponents(
            url: base.appending(path: "/v2/tasks/\(taskId.uuidString.lowercased())/events"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "after_seq", value: String(afterSeq))]
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 10
        return try await sendHarness(request, as: TaskEventPage.self)
    }

    static func taskAction(taskId: UUID, actionId: UUID, type: String, content: String) async throws -> LearningTaskView {
        var request = URLRequest(url: base.appending(path: "/v2/tasks/\(taskId.uuidString.lowercased())/actions"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "action_id": actionId.uuidString.lowercased(),
            "action_type": type,
            "content": content,
            "selection": content,
            "payload": [:],
        ])
        return try await sendHarness(request, as: LearningTaskView.self)
    }

    static func ackLearningTask(taskId: UUID, lastEventSeq: Int, knowledgeIds: [UUID] = []) async throws -> LearningTaskView {
        var request = URLRequest(url: base.appending(path: "/v2/tasks/\(taskId.uuidString.lowercased())/ack"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 15
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "last_event_seq": lastEventSeq,
            "knowledge_ids": knowledgeIds.map { $0.uuidString.lowercased() },
        ])
        return try await sendHarness(request, as: LearningTaskView.self)
    }

    private static func sendHarness<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        try AppRuntime.current.requireSending()
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ... 299).contains(code) else {
            if let fastapi = try? JSONDecoder().decode(FastAPIError.self, from: data) {
                throw HarnessAPIError.server(code: fastapi.detail.errorCode, message: fastapi.detail.message)
            }
            throw HarnessAPIError.http(code)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private static func send(_ request: URLRequest) async throws -> CaptureView {
        try AppRuntime.current.requireSending()
        let (data, response) = try await URLSession.shared.data(for: request)
        let http = response as? HTTPURLResponse
        let code = http?.statusCode ?? 0
        if (200 ... 299).contains(code) {
            return try JSONDecoder().decode(CaptureView.self, from: data)
        }
        if let fastapi = try? JSONDecoder().decode(FastAPIError.self, from: data) {
            throw CaptureAPIError.server(code: fastapi.detail.errorCode, message: fastapi.detail.message)
        }
        throw CaptureAPIError.http(code)
    }
}

private struct FastAPIError: Decodable {
    var detail: AgentAPI.APIError
}

enum ReviewAPIError: Error {
    case server(code: String, message: String)
    case http(Int)

    var errorCode: String {
        switch self {
        case .server(let code, _): return code
        case .http(let status) where status == 408 || status == 429 || status >= 500:
            return "RT.REVIEW.SERVICE_UNAVAILABLE"
        case .http:
            return "RT.REVIEW.REQUEST_FAILED"
        }
    }
}

enum CaptureAPIError: Error {
    case server(code: String, message: String)
    case http(Int)

    var errorCode: String {
        switch self {
        case .server(let code, _): return code
        case .http(let status) where status == 408 || status == 429 || status >= 500:
            return "RT.CAPTURE.SERVICE_UNAVAILABLE"
        case .http:
            return "RT.CAPTURE.REQUEST_FAILED"
        }
    }

    static func code(for error: Error, fallback: String = "RT.CAPTURE.MODEL_FAILED") -> String {
        if let captureError = error as? CaptureAPIError {
            return captureError.errorCode
        }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .timedOut, .cannotConnectToHost, .networkConnectionLost,
                 .notConnectedToInternet, .dnsLookupFailed, .cannotFindHost:
                return "RT.CAPTURE.SERVICE_UNAVAILABLE"
            default:
                break
            }
        }
        return fallback
    }
}

enum HarnessAPIError: Error {
    case server(code: String, message: String)
    case http(Int)

    var errorCode: String {
        switch self {
        case .server(let code, _): return code
        case .http(let status) where status == 408 || status == 429 || status >= 500:
            return "RT.HARNESS.SERVICE_UNAVAILABLE"
        case .http:
            return "RT.HARNESS.REQUEST_FAILED"
        }
    }

    static func code(for error: Error) -> String {
        if let harnessError = error as? HarnessAPIError { return harnessError.errorCode }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .timedOut, .cannotConnectToHost, .networkConnectionLost,
                 .notConnectedToInternet, .dnsLookupFailed, .cannotFindHost:
                return "RT.HARNESS.SERVICE_UNAVAILABLE"
            default:
                break
            }
        }
        return "RT.HARNESS.REQUEST_FAILED"
    }
}
