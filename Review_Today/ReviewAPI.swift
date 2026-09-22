import Foundation

struct ReviewJudgment: Decodable {
    var intent: String
    var grade: String?
    var feedback: String
    var coverage: [String]
    var misconceptions: [String]
    var clarificationRevealsAnswer: Bool
    var eventId: UUID
    var attemptId: UUID
    var specVersion: String
    var model: String
    var ruleVersion: String
    var durationMs: Int
    var actualCalls: Int
    var answerRevealed: Bool? = nil
}

enum ReviewAPI {
    struct SessionSnapshot {
        let id: UUID
        let revision: Int
        let paused: Bool
        let entry: ReviewQueueEntry?
        init(_ session: ReviewSession, entry: ReviewQueueEntry?) {
            id = session.id; revision = session.revision; paused = session.paused; self.entry = entry
        }
    }
    static func binding(_ entry: ReviewQueueEntry) throws -> [String: Any] {
        ["attempt_id": entry.attemptID.uuidString.lowercased(), "knowledge_id": entry.knowledgeID.uuidString.lowercased(),
         "knowledge_version": entry.knowledgeVersion, "question_id": entry.questionID.uuidString.lowercased(),
         "spec_version": entry.rubricVersion, "prompt": entry.prompt, "rubric_json": entry.rubricJSON,
         "scoring_spec": try JSONSerialization.jsonObject(with: Data(entry.rubricJSON.utf8))]
    }
    static func send(_ path: String, body: [String: Any]) async throws -> Data {
        try AppRuntime.current.requireSending()
        var request = URLRequest(url: AppRuntime.current.serviceURL.appendingPathComponent(path))
        request.httpMethod = "POST"; request.timeoutInterval = 45
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw ReviewFlowError.invalidResult
        }
        return data
    }
    static func sync(_ session: SessionSnapshot) async throws {
        var body: [String: Any] = ["session_id": session.id.uuidString.lowercased(), "revision": session.revision, "paused": session.paused]
        if let entry = session.entry { body["binding"] = try binding(entry) }
        _ = try await send("v2/review/sessions", body: body)
    }
    static func turn(session: ReviewSession, entry: ReviewQueueEntry, attempt: ReviewAttempt,
                     text: String, action: String, eventID: UUID, correcting: Bool) async throws -> (ReviewJudgment, String) {
        let snapshot = SessionSnapshot(session, entry: entry)
        try await sync(snapshot)
        try Task.checkCancellation()
        let lines = ((try? JSONDecoder().decode([ReviewDialogLine].self, from: Data(attempt.dialogJSON.utf8))) ?? []).suffix(40)
        let body: [String: Any] = ["event_id": eventID.uuidString.lowercased(), "revision": snapshot.revision,
            "binding": try binding(entry), "text": text, "action": correcting ? "correct" : action,
            "dialogue": lines.map { ["role": $0.role, "text": $0.text, "kind": $0.kind] },
            "assistance_used": attempt.hintUsed, "correcting": correcting]
        let data = try await send("v2/review/sessions/\(snapshot.id.uuidString.lowercased())/turns", body: body)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return (try decoder.decode(ReviewJudgment.self, from: data), String(decoding: data, as: UTF8.self))
    }
    static func confirm(_ session: ReviewSession, attempt: ReviewAttempt) async throws {
        var body: [String: Any] = ["attempt_id": attempt.attemptId.uuidString.lowercased(), "correction_revision": attempt.correctionRevision,
            "state": attempt.reviewState, "effective_grade": attempt.effectiveGrade,
            "knowledge_id": attempt.knowledgeId.uuidString.lowercased(), "knowledge_version": attempt.knowledgeVersion,
            "question_id": attempt.questionId.uuidString.lowercased(), "spec_version": attempt.rubricVersion]
        if let schedule = attempt.schedulerAfterJSON { body["schedule_after"] = schedule }
        _ = try await send("v2/review/sessions/\(session.id.uuidString.lowercased())/commit", body: body)
    }
}
