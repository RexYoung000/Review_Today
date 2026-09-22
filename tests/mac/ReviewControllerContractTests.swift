import Foundation
import SwiftData

@main struct ReviewControllerContractTests {
    @MainActor static func main() async throws {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let context = container.mainContext
        for index in 0..<12 {
            let item = Knowledge(learningGoal: "合成知识 \(index)", knowledgeType: "concept", theme: "test", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "光合作用利用光能", evidenceLocator: "合成")
            item.reviewEnrollment = "enrolled"; item.dueAt = Date(timeIntervalSince1970: Double(index))
            let spec = AgentAPI.ScoringSpec(learningGoal: item.learningGoal, mustCover: ["光能"], acceptableParaphrases: [], commonMisconceptions: [], evidence: "光能", orderRules: "")
            let question = Question(variantIndex: 0, promptText: "利用什么能量？", scoringSpecJSON: try ReviewLedger.encode(spec))
            context.insert(item); question.knowledge = item; context.insert(question)
        }
        try context.save()
        let coordinator = ReviewCoordinator()
        let controller = ReviewController()
        var syncs: [ReviewAPI.SessionSnapshot] = []
        controller.syncSession = { syncs.append($0) }
        controller.confirmAttempt = { _, _ in }
        var intent = "answer", grade: String? = "good", delay = false, fail = false, reveals = false
        controller.requestTurn = { _, entry, _, _, _, id, _ in
            if delay { try? await Task.sleep(for: .milliseconds(180)) }
            if fail { throw ReviewFlowError.invalidResult }
            return (ReviewJudgment(intent: intent, grade: grade, feedback: "合成反馈", coverage: [], misconceptions: [], clarificationRevealsAnswer: false, eventId: id, attemptId: entry.attemptID, specVersion: entry.rubricVersion, model: "synthetic", ruleVersion: "test", durationMs: 1, actualCalls: 0, answerRevealed: reveals), "{}")
        }
        controller.configure(context, coordinator: coordinator); controller.start(usingVoice: false)
        let originalQueue = controller.entries.map(\.attemptID)
        func answer(_ text: String = "光能") async {
            controller.submit(text)
            for _ in 0..<100 where controller.busy { try? await Task.sleep(for: .milliseconds(10)) }
            precondition(!controller.busy)
        }
        await answer()
        precondition(controller.completed.count == 1 && controller.completed[0].effectiveGrade == "good")
        grade = "again"; await answer("热能")
        precondition(controller.phase == "help" && controller.session?.currentIndex == 1)
        grade = "good"; await answer()
        precondition(controller.session?.currentIndex == 2 && controller.completed.contains { $0.effectiveGrade == "again" })
        intent = "hint"; grade = nil; await answer("给个提示")
        precondition(controller.currentAttempt?.hintUsed == true)
        intent = "answer"; grade = "good"; await answer()
        precondition(controller.completed.last(where: { $0.hintUsed })?.effectiveGrade == "again")
        let completedBefore = controller.completed.count
        controller.skipOrContinue()
        precondition(controller.skipped == 1 && controller.completed.count == completedBefore)
        intent = "forgot"; grade = "again"; await answer("忘了")
        controller.skipOrContinue()
        precondition(controller.skipped == 1 && controller.completed.count == completedBefore + 1)
        intent = "clarify"; grade = nil; await answer("换个问法")
        precondition(controller.currentAttempt?.hintUsed == false && controller.currentAttempt?.independentGrade == "")
        intent = "understood"; await answer("懂了")
        precondition(controller.currentAttempt?.independentGrade == "")
        intent = "answer"; grade = "good"; await answer()
        intent = "explain"; grade = nil; await answer("重新讲解")
        intent = "question"; await answer("能再解释一下吗")
        precondition(controller.phase == "explained", "follow-up after explanation does not force a retest")
        controller.skipOrContinue()
        intent = "question"; reveals = true; await answer("答案里的能量是什么")
        precondition(controller.currentAttempt?.hintUsed == true && controller.currentAttempt?.independentGrade == "again")
        intent = "answer"; grade = "good"; reveals = false; await answer()
        let old = controller.completed.first!, target = controller.entries.first { $0.attemptID == old.attemptId }!
        let state = try context.fetch(FetchDescriptor<FsrsState>()).first { $0.knowledgeId == target.knowledgeID }!
        let reps = state.reps, cursor = controller.session!.currentIndex
        controller.beginCorrection(target); intent = "answer"; grade = "again"; await answer("转写纠正后的原话")
        precondition(state.reps == reps && old.correctionRevision == 1 && old.effectiveGrade == "again")
        precondition(controller.session?.currentIndex == cursor)
        fail = true; await answer()
        precondition(controller.session?.currentIndex == cursor && controller.errorText != nil)
        fail = false; delay = true; grade = "good"
        controller.submit("迟到结果"); try await Task.sleep(for: .milliseconds(20)); controller.pause()
        try await Task.sleep(for: .milliseconds(240))
        precondition(controller.phase == "paused" && controller.session?.currentIndex == cursor)
        controller.configure(context, coordinator: coordinator); controller.start(usingVoice: false, resume: true)
        precondition(controller.entries.map(\.attemptID) == originalQueue && controller.session?.currentIndex == cursor)
        controller.pause()
        let previous = controller.session!
        let pausedRevision = previous.revision
        controller.configure(context, coordinator: coordinator); controller.start(usingVoice: false)
        await Task.yield()
        precondition(syncs.contains { $0.id == previous.id && $0.revision == pausedRevision && $0.paused }, "pause dispatch preserves the original revision even after a new round starts")
        precondition(previous.endedAt != nil && previous.endReason == "replaced")
        controller.pause()
        print("PASS: controller auto-advance, first-recall preservation, hint, clarify, understood, pure skip/error-skip, correction once, failure, late cancellation, frozen resume, replace round")
    }
}
