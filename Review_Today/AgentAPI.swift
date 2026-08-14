import Foundation

enum AgentAPI {
    static let base = URL(string: "http://127.0.0.1:8742")!

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
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ... 299).contains(code) else {
            throw CaptureAPIError.http(code)
        }
        return try JSONDecoder().decode(GradeResult.self, from: data)
    }

    static func ackAttempt(attemptId: UUID) async throws {
        var request = URLRequest(url: base.appending(path: "/v1/review/attempts/\(attemptId.uuidString.lowercased())/ack"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 10
        request.httpBody = try JSONEncoder().encode(["attempt_id": attemptId.uuidString.lowercased()])
        _ = try await URLSession.shared.data(for: request)
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

    private static func send(_ request: URLRequest) async throws -> CaptureView {
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

enum CaptureAPIError: Error {
    case server(code: String, message: String)
    case http(Int)
}
