import AppKit
import SwiftData
import SwiftUI

struct ReviewView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss
    @Environment(\.runway) private var runway
    var coordinator: ReviewCoordinator

    @Query private var knowledge: [Knowledge]
    @Query private var settingsRows: [AppSettings]
    @Query private var fsrsRows: [FsrsState]
    @Query private var attempts: [ReviewAttempt]
    @Query private var sessions: [ReviewSession]

    @State private var session: ReviewSession?
    @State private var index = 0
    @State private var answer = ""
    @State private var feedback = ""
    @State private var agentGrade = ""
    @State private var hintUsed = false
    @State private var attempt: ReviewAttempt?
    @State private var windowStarted = Date.now
    @State private var phase: Phase = .asking
    @State private var failureKind: FailureKind = .grading
    @State private var pendingGrade = ""
    @State private var finished: [FinishedItem] = []
    @State private var endNote = ""
    @State private var speaker = SpeechSpeaker()

    private var isPreview: Bool { coordinator.mode == "preview" }
    private var developerMode: Bool { settingsRows.first?.developerMode == true }

    private var items: [Knowledge] {
        coordinator.knowledgeIDs.compactMap { id in knowledge.first(where: { $0.id == id && $0.lifecycle == "active" }) }
    }

    private var current: Knowledge? {
        guard items.indices.contains(index) else { return nil }
        return items[index]
    }

    private var question: Question? {
        guard let current else { return nil }
        if isPreview, let questionID = coordinator.previewQuestionID {
            return current.questions.first(where: { $0.id == questionID })
        }
        return current.questions.first(where: { $0.variantIndex == 0 })
            ?? current.questions.sorted(by: { $0.variantIndex < $1.variantIndex }).first
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            ScrollView {
                Group {
                    if phase == .summary {
                        summaryBody
                    } else if let current, let question {
                        questionBody(current, question)
                    } else {
                        emptyBody
                    }
                }
                .frame(maxWidth: 720)
                .frame(maxWidth: .infinity)
                .padding(32)
            }
        }
        .background(PaperSurface())
        .frame(minWidth: 720, minHeight: 520)
        .onAppear { startSession() }
        .onChange(of: coordinator.openNonce) { _, _ in
            index = 0
            finished = []
            endNote = ""
            session = nil
            resetCard()
            startSession()
        }
        .onDisappear { speaker.stop() }
    }

    private var header: some View {
        HStack(spacing: 12) {
            MascotMotion(phase: phase == .grading ? .thinking : .idle).frame(width: 62, height: 52)
            VStack(alignment: .leading, spacing: 2) {
                Text(isPreview ? String(localized: "试一题 · 不计入排期") : String(localized: "今日复习"))
                    .font(.headline)
                if phase != .summary, items.count > 1 {
                    Text("\(index + 1) / \(items.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            if phase != .summary && phase != .grading && phase != .committing {
                Button(String(localized: "暂停")) { pause() }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 16)
        .background(.clear)
    }

    private func questionBody(_ item: Knowledge, _ question: Question) -> some View {
        RunwayCard(padding: 28) {
            VStack(alignment: .leading, spacing: 20) {
            Text(phaseCaption)
                .font(.subheadline)
                .foregroundStyle(phase == .failed ? Color.orange : runway.secondaryInformation)

            Text(question.promptText)
                .font(.system(size: 26, weight: .semibold, design: .rounded))
                .textSelection(.enabled)

            Text(item.learningGoal)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if phase == .answering || phase == .asking || (phase == .failed && failureKind == .grading) {
                if hintUsed {
                    Text(String(localized: "提示：先覆盖学习目标中的关键限定，再说出核心含义。"))
                        .foregroundStyle(.secondary)
                }
                PaperWell {
                    TextField(String(localized: "用自己的话回答"), text: $answer, axis: .vertical)
                        .textFieldStyle(.plain)
                        .font(.title3)
                        .lineLimit(4 ... 10)
                }
            }

            if phase == .answering || phase == .asking {
                HStack {
                    if !hintUsed {
                        Button(String(localized: "给我提示")) { giveHint() }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    RunwayPrimaryButton(
                        title: String(localized: "我答完了"),
                        enabled: !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                        action: { Task { await submit(item, question) } }
                    )
                    .keyboardShortcut(.return, modifiers: [.command])
                }
            }

            if phase == .grading {
                Text(String(localized: "正在判断"))
                    .foregroundStyle(.secondary)
            }

            if phase == .committing {
                Text(String(localized: "正在计入复习"))
                    .foregroundStyle(.secondary)
                ProgressView()
                    .controlSize(.small)
            }

            if phase == .failed {
                Text(feedback)
                    .foregroundStyle(.orange)
                if failureKind == .grading {
                    Button(String(localized: "再试一次")) {
                        Task { await submit(item, question) }
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(runway.action)
                    .disabled(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                } else {
                    if !agentGrade.isEmpty {
                        HStack(spacing: 8) {
                            Text(String(localized: "Agent 判断"))
                                .foregroundStyle(.secondary)
                            Text(MasteryCopy.label(agentGrade))
                        }
                        .font(.subheadline)
                    }
                    Button(String(localized: "重试计入复习")) {
                        let grade = pendingGrade.isEmpty ? agentGrade : pendingGrade
                        Task { await finish(grade: grade, item: item) }
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(runway.action)
                    .disabled(pendingGrade.isEmpty && agentGrade.isEmpty)
                    HStack {
                        Text(String(localized: "改判后重试"))
                            .foregroundStyle(.secondary)
                        ForEach(["again", "hard", "good"], id: \.self) { grade in
                            GradeChip(title: MasteryCopy.label(grade)) {
                                Task { await finish(grade: grade, item: item) }
                            }
                        }
                    }
                    .font(.subheadline)
                }
            }

            if phase == .feedback {
                VStack(alignment: .leading, spacing: 12) {
                    Text(feedback)
                    HStack(spacing: 8) {
                        Text(String(localized: "Agent 判断"))
                            .foregroundStyle(.secondary)
                        Text(MasteryCopy.label(agentGrade))
                    }
                    .font(.subheadline)
                    RunwayPrimaryButton(
                        title: String(localized: "采用这个判断"),
                        enabled: !agentGrade.isEmpty,
                        action: { Task { await finish(grade: agentGrade, item: item) } }
                    )
                    HStack {
                        Text(String(localized: "改判"))
                            .foregroundStyle(.secondary)
                        ForEach(["again", "hard", "good"], id: \.self) { grade in
                            if grade != agentGrade {
                                GradeChip(title: MasteryCopy.label(grade)) {
                                    Task { await finish(grade: grade, item: item) }
                                }
                            }
                        }
                    }
                }
            }
        }
        }
        .animation(Runway.softSpring, value: phase)
    }

    private var summaryBody: some View {
        RunwayCard(padding: 28) {
            VStack(alignment: .leading, spacing: 16) {
            Text(isPreview ? String(localized: "这题不计入排期") : String(localized: "今天这一轮"))
                .font(.title2.weight(.semibold))
            if !endNote.isEmpty {
                Text(endNote)
                    .foregroundStyle(.secondary)
            }
            if finished.isEmpty {
                Text(String(localized: "这一轮还没有计入的题目。"))
                    .foregroundStyle(.secondary)
            } else {
                ForEach(finished) { row in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(row.goal)
                        Text(MasteryCopy.label(row.grade))
                            .font(.subheadline)
                            .foregroundStyle(runway.information)
                        if !isPreview, let due = row.dueAt {
                            Text("下次 \(due.formatted(date: .abbreviated, time: .shortened))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
            RunwayPrimaryButton(title: String(localized: "关闭"), action: { dismiss() })
            }
        }
    }

    private var emptyBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(String(localized: "没有可复习的题目"))
            Button(String(localized: "关闭")) { dismiss() }
        }
    }

    private var phaseCaption: String {
        switch phase {
        case .asking: String(localized: "正在提问")
        case .answering: String(localized: "请回答")
        case .grading: String(localized: "正在判断")
        case .committing: String(localized: "正在计入复习")
        case .feedback: String(localized: "判断结果")
        case .failed: String(localized: "本题尚未计入复习")
        case .summary: ""
        }
    }

    private func startSession() {
        guard session == nil else { return }
        windowStarted = .now
        phase = .answering
        let snapshot = coordinator.knowledgeIDs.map(\.uuidString).joined(separator: ",")
        let model = ReviewSession(mode: coordinator.mode, snapshotJSON: snapshot)
        session = model
        modelContext.insert(model)
        try? modelContext.save()
        if let question {
            let restored = current.map { restorePendingAttempt(for: $0, question: question, session: model) } ?? false
            speaker.speak(question.promptText) {
                if !restored, phase == .asking { phase = .answering }
            }
        } else {
            phase = .summary
        }
    }

    private func restorePendingAttempt(
        for item: Knowledge,
        question: Question,
        session: ReviewSession
    ) -> Bool {
        let candidates = attempts.filter { row in
            row.knowledgeId == item.id &&
            row.questionId == question.id &&
            row.mode == coordinator.mode &&
            row.effectiveGrade.isEmpty &&
            ["grading", "graded", "ack_pending", "preview_pending", "retryable_failed"].contains(row.reviewState)
        }
        guard let row = candidates.max(by: { left, right in
            let leftDate = sessions.first(where: { $0.id == left.sessionId })?.startedAt ?? .distantPast
            let rightDate = sessions.first(where: { $0.id == right.sessionId })?.startedAt ?? .distantPast
            return leftDate < rightDate
        }) else { return false }

        attempt = row
        row.sessionId = session.id
        answer = row.answerText
        hintUsed = row.hintUsed
        agentGrade = row.agentGrade
        pendingGrade = row.pendingGrade

        if row.reviewState == "graded", !row.agentGrade.isEmpty {
            feedback = String(localized: "上次判断已完成，请确认是否计入复习。")
            phase = .feedback
        } else if !row.pendingGrade.isEmpty || (!row.agentGrade.isEmpty && row.reviewState != "grading") {
            failureKind = .commit
            feedback = String(localized: "上次判断已完成，但还没有计入复习。可以重试，不会重复记账。")
            phase = .failed
        } else {
            failureKind = .grading
            row.reviewState = "retryable_failed"
            row.reviewErrorCode = "RT.REVIEW.RETRY_AFTER_RESTART"
            row.reviewUserStatus = "上次判断未完成，可以重试"
            feedback = String(localized: "上次判断没有完成，原回答仍在这里，可以修改后重试。")
            phase = .failed
        }
        try? modelContext.save()
        return true
    }

    private func resetCard() {
        answer = ""
        feedback = ""
        agentGrade = ""
        hintUsed = false
        attempt = nil
        pendingGrade = ""
        failureKind = .grading
        phase = .answering
    }

    private func giveHint() {
        hintUsed = true
    }

    private func submit(_ item: Knowledge, _ question: Question) async {
        guard let session,
              phase == .answering || (phase == .failed && failureKind == .grading),
              !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        speaker.stop()
        phase = .grading
        let answerSnapshot = answer
        let hintSnapshot = hintUsed
        guard let spec = try? JSONDecoder().decode(
            AgentAPI.ScoringSpec.self,
            from: Data(question.scoringSpecJSON.utf8)
        ) else {
            feedback = String(localized: "本题评分规格不可用，暂时无法判断。请回到知识卡检查后再试。")
            agentGrade = ""
            failureKind = .grading
            phase = .failed
            return
        }
        let isNewAttempt = attempt == nil
        let row: ReviewAttempt
        if let existing = attempt {
            row = existing
        } else {
            row = ReviewAttempt(
                sessionId: session.id,
                knowledgeId: item.id,
                knowledgeVersion: item.version,
                questionId: question.id,
                mode: coordinator.mode
            )
            attempt = row
            modelContext.insert(row)
        }
        row.hintUsed = hintSnapshot
        row.answerText = answerSnapshot
        row.agentGrade = ""
        row.effectiveGrade = ""
        row.completedAt = nil
        row.pendingGrade = ""
        row.reviewState = "grading"
        row.reviewErrorCode = nil
        row.reviewUserStatus = "正在判断"
        do {
            try modelContext.save()
        } catch {
            modelContext.rollback()
            if isNewAttempt {
                attempt = nil
            }
            feedback = String(localized: "本题回答暂未保存。可以重试，不能把这次当作已掌握。")
            failureKind = .grading
            phase = .failed
            return
        }
        do {
            let graded = try await AgentAPI.grade(
                attemptId: row.attemptId,
                promptText: question.promptText,
                scoringSpec: spec,
                answerText: answerSnapshot,
                hintUsed: hintSnapshot,
                primaryLanguage: UserLanguage.primaryCode
            )
            guard graded.attemptId.lowercased() == row.attemptId.uuidString.lowercased(),
                  ["again", "hard", "good"].contains(graded.agentGrade),
                  !graded.briefFeedback.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw ReviewAnswerError.invalidResult
            }
            agentGrade = graded.agentGrade
            feedback = graded.briefFeedback
            row.agentGrade = graded.agentGrade
            row.reviewState = "graded"
            row.reviewErrorCode = nil
            row.reviewUserStatus = "判断完成，等待采用"
            try modelContext.save()
            phase = .feedback
        } catch {
            modelContext.rollback()
            row.agentGrade = ""
            row.reviewState = "retryable_failed"
            row.reviewErrorCode = AgentAPI.reviewErrorCode(for: error)
            row.reviewUserStatus = "判断失败，可以修改回答后重试"
            try? modelContext.save()
            failureKind = .grading
            agentGrade = ""
            feedback = String(localized: "本题尚未计入复习。可以修改回答后重试，不要把这次当作已掌握。")
            phase = .failed
        }
    }

    private func finish(grade: String, item: Knowledge) async {
        guard (phase == .feedback || (phase == .failed && failureKind == .commit)),
              ["again", "hard", "good"].contains(grade),
              let attempt,
              let session else { return }

        pendingGrade = grade
        phase = .committing
        attempt.pendingGrade = grade
        attempt.reviewState = isPreview ? "preview_pending" : "ack_pending"
        attempt.reviewErrorCode = nil
        attempt.reviewUserStatus = isPreview ? "正在保存预览结果" : "正在计入复习"

        if isPreview {
            do {
                attempt.effectiveGrade = grade
                attempt.pendingGrade = ""
                attempt.acked = false
                attempt.reviewState = "preview_completed"
                attempt.reviewUserStatus = "预览完成，不计入正式复习"
                try modelContext.save()
                finished.append(FinishedItem(goal: item.learningGoal, grade: grade, dueAt: nil))
                endNote = String(localized: "预览结束，排期没有变化。")
                session.endedAt = .now
                session.endReason = "preview_done"
                phase = .summary
            } catch {
                modelContext.rollback()
                attempt.reviewState = "retryable_failed"
                attempt.reviewErrorCode = "RT.REVIEW.LOCAL_SAVE_FAILED"
                attempt.reviewUserStatus = "预览结果暂未保存，可以重试"
                failureKind = .commit
                feedback = String(localized: "预览结果暂未保存，可以重试；正式排期没有变化。")
                phase = .failed
            }
            return
        }

        if Date.now.timeIntervalSince(windowStarted) > 5 * 60, !finished.isEmpty {
            session.endedAt = .now
            session.endReason = "window"
            endNote = String(localized: "五分钟窗口到了，已完成的题目已保存。")
            try? modelContext.save()
            phase = .summary
            return
        }

        do {
            try modelContext.save()
        } catch {
            modelContext.rollback()
            attempt.pendingGrade = grade
            attempt.reviewState = "retryable_failed"
            attempt.reviewErrorCode = "RT.REVIEW.LOCAL_SAVE_FAILED"
            attempt.reviewUserStatus = "还没有计入复习，可以重试"
            try? modelContext.save()
            failureKind = .commit
            feedback = String(localized: "本题判断已完成，但还没有计入复习。可以重试，不会重复记账。")
            phase = .failed
            return
        }

        do {
            try await AgentAPI.ackAttempt(attemptId: attempt.attemptId)
        } catch {
            attempt.reviewState = "retryable_failed"
            attempt.reviewErrorCode = AgentAPI.reviewErrorCode(
                for: error,
                fallback: "RT.REVIEW.ACK_FAILED"
            )
            attempt.reviewUserStatus = "还没有计入复习，可以重试"
            try? modelContext.save()
            failureKind = .commit
            feedback = String(localized: "判断已完成，但还没有计入复习。请重试“计入复习”，不要把这次当作回答错误。")
            phase = .failed
            return
        }

        do {
            var due = item.dueAt
            if let state = fsrsRows.first(where: { $0.knowledgeId == item.id }) {
                Fsrs.apply(grade: grade, to: state)
                item.dueAt = state.dueAt
                item.forceDue = false
                due = state.dueAt
            }
            attempt.effectiveGrade = grade
            attempt.pendingGrade = ""
            attempt.acked = true
            attempt.reviewState = "completed"
            attempt.completedAt = .now
            attempt.reviewErrorCode = nil
            attempt.reviewUserStatus = "已计入复习"
            try modelContext.save()
            finished.append(FinishedItem(goal: item.learningGoal, grade: grade, dueAt: due))
            advance(session: session)
        } catch {
            modelContext.rollback()
            attempt.pendingGrade = grade
            attempt.effectiveGrade = ""
            attempt.acked = false
            attempt.completedAt = nil
            attempt.reviewState = "retryable_failed"
            attempt.reviewErrorCode = "RT.REVIEW.LOCAL_SAVE_FAILED"
            attempt.reviewUserStatus = "判断已确认，但本机暂未保存，可以重试"
            try? modelContext.save()
            failureKind = .commit
            feedback = String(localized: "判断已确认，但本机暂未保存复习结果。可以重试，不会重复记账。")
            phase = .failed
        }
    }

    private func advance(session: ReviewSession) {
        resetCard()
        if index + 1 < items.count {
            index += 1
            if let question {
                speaker.speak(question.promptText) {
                    if phase == .asking { phase = .answering }
                }
            }
        } else {
            session.endedAt = .now
            session.endReason = "complete"
            try? modelContext.save()
            phase = .summary
        }
    }

    private func pause() {
        speaker.stop()
        session?.paused = true
        session?.endReason = "paused"
        session?.endedAt = .now
        try? modelContext.save()
        if finished.isEmpty {
            dismiss()
        } else {
            endNote = String(localized: "已暂停。完成的题目已保存，可以稍后再继续。")
            phase = .summary
        }
    }
}

private struct FinishedItem: Identifiable {
    var id = UUID()
    var goal: String
    var grade: String
    var dueAt: Date?
}

private enum Phase {
    case asking, answering, grading, committing, feedback, failed, summary
}

private enum FailureKind: Equatable {
    case grading
    case commit
}

private enum ReviewAnswerError: Error {
    case invalidResult
}

private final class SpeechSpeaker: NSObject, NSSpeechSynthesizerDelegate {
    private var synth = NSSpeechSynthesizer()
    private var onFinish: (() -> Void)?

    override init() {
        super.init()
        synth.delegate = self
    }

    func speak(_ text: String, onFinish: @escaping () -> Void) {
        stop()
        self.onFinish = onFinish
        synth.startSpeaking(text)
    }

    func stop() {
        synth.stopSpeaking()
        onFinish = nil
    }

    func speechSynthesizer(_ sender: NSSpeechSynthesizer, didFinishSpeaking finishedSpeaking: Bool) {
        let done = onFinish
        onFinish = nil
        DispatchQueue.main.async { done?() }
    }
}
