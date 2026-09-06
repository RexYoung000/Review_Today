// Used by import-legacy-library.py after ID/content preflight on backed-up stores.
import Foundation
import SwiftData

@main
struct LegacyLibraryImport {
    @MainActor static func main() throws {
        if CommandLine.arguments[1] == "--seed-deletion" {
            let target = CommandLine.arguments[2]
            precondition(target.hasPrefix("/tmp/review-today-") && target.hasSuffix("/app.store"))
            let schema = M1DebugFixture.schema
            let container = try ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema, url: URL(fileURLWithPath: target)))
            let c = container.mainContext
            let owner = AgentSession(title: "删除验收 · 独有与共享", status: "archived")
            owner.lifecycleRevision = 1
            let other = AgentSession(title: "删除验收 · 共享使用方", status: "archived")
            other.lifecycleRevision = 1
            c.insert(owner); c.insert(other)
            for (title, shared) in [("独有测试卡", false), ("共享测试卡", true)] {
                let value = Knowledge(learningGoal: title, knowledgeType: "concept", theme: "RAG", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "检索后生成", evidenceLocator: "测试来源")
                value.originSessionID = owner.id
                c.insert(value); c.insert(KnowledgeReference(sessionID: owner.id, knowledgeID: value.id))
                if shared { c.insert(KnowledgeReference(sessionID: other.id, knowledgeID: value.id)) }
                c.insert(ReviewAttempt(sessionId: UUID(), knowledgeId: value.id, knowledgeVersion: 1, questionId: UUID(), mode: "preview"))
            }
            try c.save()
            print("Seeded two archived QA sessions with exclusive/shared cards and preview records.")
            return
        }
        let input = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: [[String: Any]]]
        let schema = M1DebugFixture.schema
        let destination = URL(fileURLWithPath: CommandLine.arguments[2])
        let container = try ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema, url: destination))
        let context = container.mainContext
        context.autosaveEnabled = false
        func rows(_ name: String) -> [[String: Any]] { input[name] ?? [] }
        func str(_ r: [String: Any], _ k: String, _ fallback: String = "") -> String { r[k] as? String ?? fallback }
        func num(_ r: [String: Any], _ k: String) -> Double { (r[k] as? NSNumber)?.doubleValue ?? 0 }
        func int(_ r: [String: Any], _ k: String) -> Int { (r[k] as? NSNumber)?.intValue ?? 0 }
        func flag(_ r: [String: Any], _ k: String) -> Bool { int(r, k) != 0 }
        func date(_ r: [String: Any], _ k: String) -> Date { Date(timeIntervalSinceReferenceDate: num(r, k)) }
        func id(_ r: [String: Any], _ k: String = "ZID") -> UUID { UUID(uuidString: str(r, k))! }
        var sources = Dictionary(uniqueKeysWithValues: try context.fetch(FetchDescriptor<Source>()).map { ($0.id, $0) })
        var cards = Dictionary(uniqueKeysWithValues: try context.fetch(FetchDescriptor<Knowledge>()).map { ($0.id, $0) })
        let questions = Set(try context.fetch(FetchDescriptor<Question>()).map(\.id))
        let states = Set(try context.fetch(FetchDescriptor<FsrsState>()).map(\.knowledgeId))
        let reviews = Set(try context.fetch(FetchDescriptor<ReviewSession>()).map(\.id))
        let attempts = Set(try context.fetch(FetchDescriptor<ReviewAttempt>()).map(\.attemptId))
        do {
            for r in rows("ZSOURCE") where sources[id(r)] == nil {
                let value = Source(id: id(r), createdAt: date(r,"ZCREATEDAT"), inputType: str(r,"ZINPUTTYPE"), rawText: str(r,"ZRAWTEXT"), url: r["ZURL"] as? String, audioPath: r["ZAUDIOPATH"] as? String, attribution: str(r,"ZATTRIBUTION"))
                context.insert(value); sources[value.id] = value
            }
            for r in rows("ZKNOWLEDGE") where cards[id(r)] == nil {
                let value = Knowledge(id: id(r), version: int(r,"ZVERSION"), learningGoal: str(r,"ZLEARNINGGOAL"), knowledgeType: str(r,"ZKNOWLEDGETYPE"), theme: str(r,"ZTHEME"), contentLanguage: str(r,"ZCONTENTLANGUAGE"), questionLanguage: str(r,"ZQUESTIONLANGUAGE"), answerLanguage: str(r,"ZANSWERLANGUAGE"), evidenceExcerpt: str(r,"ZEVIDENCEEXCERPT"), evidenceLocator: str(r,"ZEVIDENCELOCATOR"), title: str(r,"ZTITLE"), explanation: str(r,"ZEXPLANATION"), lifecycle: str(r,"ZLIFECYCLE"), createdAt: date(r,"ZCREATEDAT"), dueAt: date(r,"ZDUEAT"))
                value.forceDue = flag(r,"ZFORCEDUE"); value.skipTwoHourWait = flag(r,"ZSKIPTWOHOURWAIT")
                if let sourceID = (r["source_id"] as? String).flatMap(UUID.init(uuidString:)) { value.source = sources[sourceID] }
                context.insert(value); cards[value.id] = value
            }
            for r in rows("ZQUESTION") where !questions.contains(id(r)) {
                let value = Question(id: id(r), knowledgeVersion: int(r,"ZKNOWLEDGEVERSION"), variantIndex: int(r,"ZVARIANTINDEX"), promptText: str(r,"ZPROMPTTEXT"), scoringSpecJSON: str(r,"ZSCORINGSPECJSON"))
                value.knowledge = cards[id(r,"knowledge_id")]; context.insert(value)
            }
            for r in rows("ZFSRSSTATE") where !states.contains(id(r,"ZKNOWLEDGEID")) {
                let value = FsrsState(knowledgeId: id(r,"ZKNOWLEDGEID"), dueAt: date(r,"ZDUEAT"))
                value.stability = num(r,"ZSTABILITY"); value.difficulty = num(r,"ZDIFFICULTY")
                value.reps = int(r,"ZREPS"); value.lapses = int(r,"ZLAPSES")
                value.algorithmVersion = str(r,"ZALGORITHMVERSION"); value.parameterVersion = str(r,"ZPARAMETERVERSION")
                value.lastEffectiveGrade = str(r,"ZLASTEFFECTIVEGRADE"); context.insert(value)
            }
            for r in rows("ZREVIEWSESSION") where !reviews.contains(id(r)) {
                let value = ReviewSession(mode: str(r,"ZMODE"), snapshotJSON: str(r,"ZSNAPSHOTJSON"))
                value.id = id(r); value.startedAt = date(r,"ZSTARTEDAT"); value.windowStartedAt = date(r,"ZWINDOWSTARTEDAT")
                value.endedAt = r["ZENDEDAT"] is NSNumber ? date(r,"ZENDEDAT") : nil
                value.endReason = str(r,"ZENDREASON"); value.paused = flag(r,"ZPAUSED")
                context.insert(value)
            }
            for r in rows("ZREVIEWATTEMPT") where !attempts.contains(id(r,"ZATTEMPTID")) {
                let value = ReviewAttempt(sessionId: id(r,"ZSESSIONID"), knowledgeId: id(r,"ZKNOWLEDGEID"), knowledgeVersion: int(r,"ZKNOWLEDGEVERSION"), questionId: id(r,"ZQUESTIONID"), mode: str(r,"ZMODE"))
                value.attemptId = id(r,"ZATTEMPTID"); value.agentGrade = str(r,"ZAGENTGRADE"); value.effectiveGrade = str(r,"ZEFFECTIVEGRADE")
                value.pendingGrade = str(r,"ZPENDINGGRADE"); value.reviewState = str(r,"ZREVIEWSTATE")
                value.reviewErrorCode = r["ZREVIEWERRORCODE"] as? String; value.reviewUserStatus = str(r,"ZREVIEWUSERSTATUS")
                value.hintUsed = flag(r,"ZHINTUSED"); value.transcriptRetryCount = int(r,"ZTRANSCRIPTRETRYCOUNT")
                value.earlyReview = flag(r,"ZEARLYREVIEW"); value.degradedPath = str(r,"ZDEGRADEDPATH")
                value.answerText = str(r,"ZANSWERTEXT"); value.acked = flag(r,"ZACKED")
                // This old schema has no completion timestamp. Keep it unknown;
                // use its owning review's recorded start for the required creation date.
                value.createdAt = rows("ZREVIEWSESSION").first(where: { id($0) == value.sessionId }).map { date($0,"ZSTARTEDAT") } ?? Date(timeIntervalSinceReferenceDate: 0)
                value.completedAt = nil
                context.insert(value)
            }
            if CommandLine.arguments.contains("--fail-before-save") {
                precondition(destination.path.hasPrefix("/tmp/review-today-"), "Failure injection is limited to isolated rehearsal stores")
                throw CocoaError(.fileWriteUnknown)
            }
            try context.save()
        } catch { context.rollback(); throw error }
        print("Imported library transaction committed; previews retain mode and unknown completion time.")
    }
}
