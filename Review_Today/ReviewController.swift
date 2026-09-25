import Foundation
import Observation
import SwiftData

@MainActor @Observable
final class ReviewController {
    var session: ReviewSession?
    var resumable: ReviewSession?
    var phase = "setup"
    var answer = ""
    var feedback = ""
    var errorText: String?
    var goal = "due"
    var goalValue = 5
    var showRecords = false
    var voice = ReviewVoice()
    var generation = 0
    var correctionTarget: ReviewQueueEntry?
    var viewingHistory = false
    var savedFeedback = ""
    var savedReaction: String?
    var savedResultToken = 0
    private var context: ModelContext?
    private var coordinator: ReviewCoordinator?
    private var work: Task<Void, Never>?
    @ObservationIgnored var requestTurn = ReviewAPI.turn
    @ObservationIgnored var syncSession = ReviewAPI.sync
    @ObservationIgnored var confirmAttempt = ReviewAPI.confirm

    var entries: [ReviewQueueEntry] { session.map(ReviewLedger.queue) ?? [] }
    var entry: ReviewQueueEntry? {
        if let correctionTarget { return correctionTarget }
        guard let session, session.endedAt == nil, entries.indices.contains(session.currentIndex) else { return nil }
        return entries[session.currentIndex]
    }
    var busy: Bool { ["thinking", "saving", "connecting"].contains(phase) }
    var attempts: [ReviewAttempt] {
        guard let context, let session else { return [] }
        return ((try? context.fetch(FetchDescriptor<ReviewAttempt>())) ?? []).filter { $0.sessionId == session.id }
    }
    var currentAttempt: ReviewAttempt? { attempts.first { $0.attemptId == entry?.attemptID } }
    var completed: [ReviewAttempt] { attempts.filter { ["completed", "preview_completed"].contains($0.reviewState) } }
    var skipped: Int { attempts.filter { $0.reviewState == "skipped" }.count }
    var assisted: Int { completed.filter(\.hintUsed).count }
    var needsHelp: Int { completed.filter { $0.hintUsed || $0.effectiveGrade == "again" }.count }
    var records: [ReviewDialogLine] {
        attempts.flatMap { (try? JSONDecoder().decode([ReviewDialogLine].self, from: Data($0.dialogJSON.utf8))) ?? [] }.sorted { $0.date < $1.date }
    }
    var progress: String {
        guard let session else { return "" }
        if session.endedAt != nil { return "已复习 \(completed.count) · 跳过 \(skipped) · 本轮 \(entries.count) 个知识点" }
        return "\(min(session.currentIndex + 1, entries.count)) / \(entries.count)"
    }

    func configure(_ context: ModelContext, coordinator: ReviewCoordinator) {
        if self.context != nil { pause() }
        self.context = context; self.coordinator = coordinator
        phase = "setup"; session = nil; correctionTarget = nil; errorText = nil
        viewingHistory = false; answer = ""; feedback = ""; savedFeedback = ""; savedReaction = nil
        let settings = try? context.fetch(FetchDescriptor<AppSettings>()).first
        goal = settings?.reviewGoal ?? "due"; goalValue = settings?.reviewGoalValue ?? 5
        resumable = ((try? context.fetch(FetchDescriptor<ReviewSession>())) ?? []).filter {
            $0.protocolVersion == 2 && $0.mode == coordinator.mode && $0.endedAt == nil &&
            (coordinator.mode != "preview" || ReviewLedger.queue($0).contains {
                coordinator.knowledgeIDs.contains($0.knowledgeID) && $0.questionID == coordinator.previewQuestionID
            })
        }.max { $0.startedAt < $1.startedAt }
        voice.onSpeechStart = { [weak self] in self?.interrupt() }
        voice.onTranscript = { [weak self] text, id, generation in
            guard let self, self.entry?.attemptID == id, self.generation == generation, self.session?.paused == false else { return }
            self.answer = text; self.submit(text)
        }
        voice.onFailure = { [weak self] text in self?.errorText = text }
        if let id = coordinator.summarySessionID {
            if let previous = ((try? context.fetch(FetchDescriptor<ReviewSession>())) ?? []).first(where: {
                $0.id == id && $0.protocolVersion == 2 && $0.mode == "formal" && $0.endedAt != nil
            }) {
                session = previous; phase = "summary"; viewingHistory = true
            } else { errorText = "这份小结已不可用，可以返回今天重新选择。" }
        }
    }

    func start(usingVoice: Bool, resume: Bool = false) {
        guard let context, let coordinator else { return }
        do {
            if resume, let resumable {
                session = resumable; ReviewLedger.resume(resumable)
            } else {
                let items = try context.fetch(FetchDescriptor<Knowledge>())
                let settings = try context.fetch(FetchDescriptor<AppSettings>()).first
                let selected = coordinator.mode == "preview" ? items.filter { coordinator.knowledgeIDs.contains($0.id) } : ReviewQueue.ordered(items, developerMode: settings?.developerMode == true)
                let allAttempts = try context.fetch(FetchDescriptor<ReviewAttempt>())
                let new = try ReviewLedger.start(items: selected, attempts: allAttempts, goal: goal, value: goalValue,
                                                previewQuestionID: coordinator.previewQuestionID)
                if let resumable, resumable.endedAt == nil {
                    ReviewLedger.pause(resumable)
                    resumable.endedAt = .now; resumable.endReason = "replaced"
                }
                context.insert(new); session = new
                settings?.reviewGoal = goal; settings?.reviewGoalValue = goalValue
            }
            guard let session else { return }
            if entries.isEmpty { session.endedAt = .now; session.endReason = "empty" }
            try context.save()
            generation += 1
            prepareCurrent()
            if usingVoice, entry != nil { connectVoice() }
            else { flushOutbox() }
        } catch { context.rollback(); errorText = error.localizedDescription; phase = "setup" }
    }

    func connectVoice() {
        guard let session, let entry, !session.paused else { return }
        let token = generation
        let snapshot = ReviewAPI.SessionSnapshot(session, entry: entry)
        work = Task {
            do {
                phase = "connecting"
                try await syncSession(snapshot)
                try Task.checkCancellation()
                try await voice.start(sessionID: session.id)
                guard token == generation, !session.paused else { voice.stop(); return }
                prepareCurrent(); voice.say(entry.prompt)
                flushOutbox()
            } catch {
                guard token == generation else { return }
                voice.stop(); prepareCurrent(); errorText = "实时语音尚未连接，你可以用文字开始，或重试连接。"
            }
        }
    }

    /// Explicit text mode owns capture shutdown, including an in-flight connection.
    func useText() {
        if phase == "connecting" {
            work?.cancel(); work = nil; generation += 1
            voice.stop(); prepareCurrent()
        } else { voice.stop() }
    }

    func prepareCurrent(stopVoiceAtEnd: Bool = true) {
        answer = ""; feedback = ""; errorText = nil
        guard let session, let entry else { phase = "summary"; if stopVoiceAtEnd { voice.stop() }; return }
        if session.paused { phase = "paused"; return }
        if let attempt = currentAttempt {
            feedback = attempt.feedbackText
            phase = ["help", "explained"].contains(attempt.reviewState) ? attempt.reviewState : "asking"
            if attempt.reviewState == "judging" { answer = attempt.answerText; errorText = "上次判断未完成，回答已保留，可以继续或重试。" }
        } else { phase = "asking" }
        voice.bind(entry.attemptID, generation: generation)
    }

    func item(for entry: ReviewQueueEntry) throws -> Knowledge {
        guard let context, let item = try context.fetch(FetchDescriptor<Knowledge>()).first(where: { $0.id == entry.knowledgeID }) else { throw ReviewFlowError.stale }
        try entry.validate(item, preview: session?.mode == "preview")
        return item
    }
    private func attempt(for entry: ReviewQueueEntry) throws -> ReviewAttempt {
        if let old = attempts.first(where: { $0.attemptId == entry.attemptID }) { return old }
        guard let context, let session else { throw ReviewFlowError.stale }
        let row = ReviewAttempt(sessionId: session.id, knowledgeId: entry.knowledgeID,
                                knowledgeVersion: entry.knowledgeVersion, questionId: entry.questionID, mode: session.mode)
        row.attemptId = entry.attemptID; row.reviewState = "asking"
        row.rubricJSON = entry.rubricJSON; row.promptSnapshot = entry.prompt; row.rubricVersion = entry.rubricVersion
        context.insert(row)
        try append(row, role: "assistant", text: entry.prompt, kind: "question")
        return row
    }
    private func append(_ attempt: ReviewAttempt, role: String, text: String, kind: String = "dialogue") throws {
        var lines = (try? JSONDecoder().decode([ReviewDialogLine].self, from: Data(attempt.dialogJSON.utf8))) ?? []
        lines.append(ReviewDialogLine(role: role, text: text, kind: kind))
        attempt.dialogJSON = try ReviewLedger.encode(lines)
    }

    func submit(_ text: String, action: String = "utterance") {
        guard let context, let session, let entry, !session.paused, !busy,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        voice.interrupt()
        savedFeedback = ""; savedReaction = nil
        let token = generation, revision = session.revision, correcting = correctionTarget != nil, eventID = UUID()
        phase = "thinking"; errorText = nil
        work = Task {
            do {
                _ = try item(for: entry)
                let row = try attempt(for: entry)
                let correctingSaved = correcting && ["completed", "preview_completed"].contains(row.reviewState)
                try append(row, role: "user", text: text, kind: correcting ? "correction" : action)
                if !row.acked { row.answerText = text; row.reviewState = "judging" }
                try context.save()
                ReviewLedger.checkpoint(session)
                try context.save()
                let (result, raw) = try await requestTurn(session, entry, row, text, action, eventID, correcting)
                guard !Task.isCancelled, token == generation, session.revision == revision, !session.paused,
                      result.eventId == eventID, result.attemptId == entry.attemptID, result.specVersion == entry.rubricVersion else { return }
                _ = try item(for: entry)
                row.evaluationJSON = raw; row.feedbackText = result.feedback
                try append(row, role: "assistant", text: result.feedback, kind: result.intent)
                feedback = result.feedback; answer = ""
                if correcting && !["answer", "forgot"].contains(result.intent) {
                    phase = "asking"; try context.save(); voice.say(feedback); return
                }
                if ["answer", "forgot"].contains(result.intent), let grade = result.grade {
                    guard ["again", "hard", "good"].contains(grade) else { throw ReviewFlowError.invalidResult }
                    row.agentGrade = grade
                    if correcting { row.correctedAnswer = text; row.independentGrade = grade }
                    else if row.independentGrade.isEmpty {
                        row.independentGrade = row.hintUsed ? "again" : grade
                        row.originalAnswer = text; row.judgedAt = .now
                    }
                }
                switch result.intent {
                case "answer":
                    if result.grade == nil { phase = "asking"; if !row.acked { row.reviewState = "asking" }; try context.save(); voice.say(feedback) }
                    else if correcting || result.grade != "again" || row.hintUsed {
                        try finish(row, entry: entry, grade: row.independentGrade, correcting: correctingSaved, spoken: feedback)
                    } else { row.reviewState = "help"; phase = "help"; try context.save(); voice.say(feedback) }
                case "forgot":
                    if correcting { try finish(row, entry: entry, grade: "again", correcting: correctingSaved, spoken: feedback) }
                    else { row.reviewState = "help"; phase = "help"; try context.save(); voice.say(feedback) }
                case "hint", "explain":
                    markAssistance(row, kind: result.intent)
                    phase = result.intent == "explain" ? "explained" : "asking"; row.reviewState = phase
                    try context.save(); voice.say(feedback)
                case "clarify":
                    if result.clarificationRevealsAnswer || result.answerRevealed == true { markAssistance(row, kind: "hint") }
                    row.reviewState = "asking"; phase = "asking"; try context.save(); voice.say(feedback)
                case "skip", "next":
                    try finish(row, entry: entry, grade: row.independentGrade.isEmpty ? nil : row.independentGrade, spoken: feedback)
                case "understood":
                    if row.hintUsed { try finish(row, entry: entry, grade: row.independentGrade.isEmpty ? "again" : row.independentGrade, spoken: feedback) }
                    else { row.reviewState = "asking"; phase = "asking"; try context.save(); voice.say(feedback) }
                case "pause": pause()
                case "correction":
                    try context.save(); phase = "asking"; beginCorrection()
                case "question":
                    guard let revealed = result.answerRevealed else { throw ReviewFlowError.invalidResult }
                    if revealed { markAssistance(row, kind: "explain") }
                    fallthrough
                default:
                    let help = (try? JSONDecoder().decode([ReviewDialogLine].self, from: Data(row.assistanceJSON.utf8))) ?? []
                    phase = help.contains { $0.kind == "explain" } ? "explained" : "asking"
                    if !row.acked { row.reviewState = phase }; try context.save(); voice.say(feedback)
                }
            } catch {
                guard token == generation, !session.paused else { return }
                phase = "asking"; errorText = error.localizedDescription
                if let row = currentAttempt, !row.acked { row.reviewState = "asking"; try? context.save() }
            }
        }
    }
    private func markAssistance(_ row: ReviewAttempt, kind: String) {
        row.hintUsed = true
        if row.independentGrade.isEmpty { row.independentGrade = "again"; row.judgedAt = .now }
        var events = (try? JSONDecoder().decode([ReviewDialogLine].self, from: Data(row.assistanceJSON.utf8))) ?? []
        events.append(ReviewDialogLine(role: "assistant", text: feedback, kind: kind))
        row.assistanceJSON = (try? ReviewLedger.encode(events)) ?? row.assistanceJSON
    }
    private func finish(_ row: ReviewAttempt, entry: ReviewQueueEntry, grade: String?, correcting: Bool = false, spoken: String = "") throws {
        guard let context, let session else { return }
        phase = "saving"
        try ReviewLedger.commit(entry: entry, item: item(for: entry), attempt: row, session: session,
                                grade: grade, context: context, correcting: correcting)
        correctionTarget = nil; generation += 1
        prepareCurrent(stopVoiceAtEnd: false); flushOutbox()
        savedFeedback = spoken.isEmpty ? (grade == nil ? "这题先放一放，后面还可以再来。" : "这次的回忆已经记下。") : spoken
        savedReaction = grade == nil ? "reaction_guide" : grade == "again" || row.hintUsed ? "reaction_encourage" : "reaction_approve"
        savedResultToken += 1
        let text = spoken + (self.entry.map { "\n" + $0.prompt } ?? "\n这一轮已结束，结果已保存在本机。")
        if phase == "summary" { voice.finish(with: text) } else { voice.say(text) }
    }
    func skipOrContinue() {
        guard !busy, let entry else { return }
        do {
            let row = try attempt(for: entry)
            try append(row, role: "user", text: phase == "explained" ? "继续其他题" : "跳过", kind: "skip")
            try finish(row, entry: entry, grade: row.independentGrade.isEmpty ? nil : row.independentGrade)
        } catch { phase = "asking"; errorText = error.localizedDescription }
    }
    func beginCorrection(_ selected: ReviewQueueEntry? = nil) {
        guard !busy, context != nil else { return }
        let target = selected ?? (currentAttempt?.independentGrade.isEmpty == false ? entry : entries.last(where: { entry in completed.contains { $0.attemptId == entry.attemptID } }))
        guard let target else { errorText = "可以直接重新说出完整回答，当前还没有计入的结果。"; return }
        interrupt(); correctionTarget = target
        if let row = attempts.first(where: { $0.attemptId == target.attemptID }) {
            answer = row.correctedAnswer ?? (row.originalAnswer.isEmpty ? row.answerText : row.originalAnswer)
        }
        phase = "asking"; feedback = "请修正刚才的原话，再提交判断。原记录会保留。"
        voice.bind(target.attemptID, generation: generation); voice.say(feedback)
    }
    func cancelCorrection() {
        interrupt(); correctionTarget = nil; prepareCurrent()
    }
    func overrideGrade(_ grade: String, entry: ReviewQueueEntry) {
        guard !busy, let row = attempts.first(where: { $0.attemptId == entry.attemptID }) else { return }
        do { try finish(row, entry: entry, grade: grade, correcting: ["completed", "preview_completed"].contains(row.reviewState), spoken: "已修正本次结果。") }
        catch { phase = "asking"; errorText = error.localizedDescription }
    }
    func interrupt() {
        work?.cancel(); work = nil; generation += 1
        voice.interrupt()
        if let session, !session.paused {
            session.revision += 1; try? context?.save()
            if busy { phase = "asking" }
            if let entry { voice.bind(entry.attemptID, generation: generation) }
        }
    }
    func discardForDataReset() {
        work?.cancel(); work = nil; generation += 1; voice.stop()
        session = nil; resumable = nil; correctionTarget = nil
        answer = ""; feedback = ""; savedFeedback = ""; savedReaction = nil
        phase = "setup"; errorText = nil
    }
    func pause() {
        work?.cancel(); work = nil; generation += 1; voice.stop()
        guard let context, let session, session.endedAt == nil, !session.paused else { return }
        ReviewLedger.pause(session)
        do { try context.save(); phase = "paused"; resumable = session }
        catch { errorText = "暂停进度尚未保存，请保留窗口并重试。" }
        let snapshot = ReviewAPI.SessionSnapshot(session, entry: entry)
        Task { try? await syncSession(snapshot) }
    }
    private func flushOutbox() {
        guard let context, let session else { return }
        let pending = attempts.filter(\.serviceCommitPending)
        guard !pending.isEmpty else { return }
        let snapshot = ReviewAPI.SessionSnapshot(session, entry: entry)
        let resetGeneration = LocalDataReset.generation
        Task {
            do {
                try await syncSession(snapshot)
                guard resetGeneration == LocalDataReset.generation else { return }
                for row in pending {
                    let revision = row.correctionRevision
                    try await confirmAttempt(session, row)
                    guard resetGeneration == LocalDataReset.generation else { return }
                    guard revision == row.correctionRevision else { continue }
                    row.serviceCommitPending = false
                    try context.save()
                }
            } catch { /* Local result is committed. Retry the outbox on resume/reconnect. */ }
        }
    }
}
