import Foundation
import NaturalLanguage
import SwiftData

/// Local evidence index. It contains small, typed observations and exact links,
/// never drafts or another Session's execution state/consent.
@MainActor
enum LearningMemory {
    static func array(_ raw: String) -> [[String: Any]] {
        (try? JSONSerialization.jsonObject(with: Data(raw.utf8))) as? [[String: Any]] ?? []
    }

    static func valid(_ references: [[String: Any]], sessions: [AgentSession], knowledge: [Knowledge], depth: Int = 0) -> Bool {
        guard depth < 6 else { return false }
        return references.allSatisfy { ref in
            if let kid = (ref["knowledge_id"] as? String).flatMap(UUID.init(uuidString:)) {
                return knowledge.contains { $0.id == kid && $0.lifecycle == "active" && $0.version == ref["content_version"] as? Int }
            }
            guard let sid = (ref["session_id"] as? String).flatMap(UUID.init(uuidString:)),
                  let session = sessions.first(where: { $0.id == sid }), session.memoryUseAllowed,
                  session.memoryPolicyRevision == ref["policy_version"] as? Int,
                  session.memoryContentRevision == ref["content_version"] as? Int,
                  let evidence = array(session.learningEvidenceJSON).first(where: { $0["id"] as? String == ref["id"] as? String }) else { return false }
            return valid(evidence["dependencies"] as? [[String: Any]] ?? [], sessions: sessions, knowledge: knowledge, depth: depth + 1)
        }
    }

    static func candidates(for query: String, excluding sid: UUID, context: ModelContext) throws -> [[String: Any]] {
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        let knowledge = try context.fetch(FetchDescriptor<Knowledge>())
        let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
        var candidates: [[String: Any]] = []
        for session in sessions where session.id != sid && session.memoryUseAllowed {
            for var evidence in array(session.learningEvidenceJSON) where evidence["content_version"] as? Int == session.memoryContentRevision {
                evidence["policy_version"] = session.memoryPolicyRevision
                guard valid([evidence], sessions: sessions, knowledge: knowledge) else { continue }
                candidates.append(evidence)
            }
        }
        for card in knowledge where card.lifecycle == "active" {
            var ref: [String: Any] = ["id": card.id.uuidString.lowercased(), "knowledge_id": card.id.uuidString.lowercased(),
                "concept": card.title.isEmpty ? card.learningGoal : card.title, "concepts": [card.theme, card.learningGoal],
                "excerpt": String((card.explanation.isEmpty ? card.evidenceExcerpt : card.explanation).prefix(1600)),
                "kind": "knowledge_card", "content_version": card.version,
                "due_at": card.dueAt.ISO8601Format(), "occurred_at": card.createdAt.ISO8601Format()]
            if let attempt = attempts.filter({ $0.knowledgeId == card.id && $0.knowledgeVersion == card.version && $0.acked && $0.completedAt != nil && $0.mode != "preview" })
                .max(by: { $0.completedAt! < $1.completedAt! }) {
                ref["review"] = ["grade": attempt.effectiveGrade, "hint_used": attempt.hintUsed,
                                 "at": attempt.completedAt!.ISO8601Format()]
            }
            candidates.append(ref)
        }
        let queryTokens = tokens(query)
        // Native language tokenization + stored concept metadata provide a local
        // shortlist. Luna chooses prerequisite/analogy/contrast/transfer once.
        let ranked: [([String: Any], Int)] = candidates.map { value in
            let names = (value["concept"] as? String ?? "") + " " + (value["concepts"] as? [String] ?? []).joined(separator: " ")
            let explicitlySelected = (value["knowledge_id"] as? String).map { query.lowercased().contains("reviewtoday://knowledge/" + $0) } ?? false
            let conceptScore = tokens(names).intersection(queryTokens).count * 4
            let excerptScore = tokens(value["excerpt"] as? String ?? "").intersection(queryTokens).count
            let overlap: Int = (explicitlySelected ? 10_000 : 0) + conceptScore + excerptScore
            return (value, overlap)
        }.sorted { $0.1 == $1.1 ? ($0.0["occurred_at"] as? String ?? "") > ($1.0["occurred_at"] as? String ?? "") : $0.1 > $1.1 }
        var seen = Set<String>()
        // Include a small recent shortlist when lexical overlap is weak; semantic
        // relationship selection remains Luna's job, never a claim of mastery.
        return ranked.filter { seen.insert(($0.0["session_id"] as? String ?? "card") + ":" + ($0.0["concept"] as? String ?? "")).inserted }
            .prefix(12).map { $0.0 }
    }

    private static func tokens(_ text: String) -> Set<String> {
        let tokenizer = NLTokenizer(unit: .word)
        tokenizer.string = text.lowercased()
        let source = text.lowercased()
        var result = Set<String>()
        tokenizer.enumerateTokens(in: source.startIndex..<source.endIndex) { range, _ in
            let value = String(source[range])
            if value.count > 1 { result.insert(value) }
            return true
        }
        return result
    }

    static func store(_ value: [String: Any], session: AgentSession) {
        guard let id = value["id"] as? String,
              (value["session_id"] as? String).flatMap(UUID.init(uuidString:)) == session.id else { return }
        var records = array(session.learningEvidenceJSON)
        var record = value
        record["content_version"] = session.memoryContentRevision
        record["policy_version"] = session.memoryPolicyRevision
        if let index = records.firstIndex(where: { $0["id"] as? String == id }) { records[index] = record }
        else { records.append(record) }
        session.learningEvidenceJSON = ConversationProcessor.json(records)
    }

    @discardableResult
    static func setAllowed(_ allowed: Bool, session: AgentSession, context: ModelContext) -> Bool {
        guard session.memoryUseAllowed != allowed else { return true }
        session.memoryUseAllowed = allowed
        session.memoryPolicyRevision += 1
        do {
            try fenceInvalidReferences(context: context)
            try context.save()
            ConversationSync.wake()
            return true
        } catch { context.rollback(); return false }
    }

    static func fenceInvalidReferences(context: ModelContext) throws {
        let sessions = try context.fetch(FetchDescriptor<AgentSession>())
        let knowledge = try context.fetch(FetchDescriptor<Knowledge>())
        for run in try context.fetch(FetchDescriptor<AgentRun>()) {
            guard !valid(array(run.memoryReferencesJSON), sessions: sessions, knowledge: knowledge) else { continue }
            // The historical record remains visible, but cannot be recalled into
            // a new answer or grant a pending save after its dependency is revoked.
            if run.memoryInvalidationRevision < 0, let session = sessions.first(where: { $0.id == run.sessionID }) {
                session.summaryText = ""
                session.pendingOperationJSON = nil
                run.memoryInvalidationRevision = run.revision
            }
            if ["running", "accepted", "adjusting", "queued"].contains(run.status) {
                run.status = "stopping"
                if let started = run.startedAt { run.elapsedMS = max(0, Int(Date.now.timeIntervalSince(started) * 1000)) }
                run.startedAt = nil
                run.userSummary = "学习关联已更新，旧回复已停止；可重新提问"
                let rid = run.id
                let pending = try context.fetch(FetchDescriptor<AgentRunControl>(predicate: #Predicate { $0.runID == rid && !$0.sent }))
                if !pending.contains(where: { $0.action == "stop" || $0.action == "cancel_task" }) {
                    context.insert(AgentRunControl(runID: run.id, sessionID: run.sessionID, action: "stop"))
                }
                for message in try context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.runID == rid })) where message.responseState == "streaming" {
                    message.responseState = "interrupted"
                }
            }
        }
    }
}
