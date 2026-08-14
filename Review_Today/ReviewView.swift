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

    @State private var session: ReviewSession?
    @State private var index = 0
    @State private var answer = ""
    @State private var feedback = ""
    @State private var agentGrade = ""
    @State private var hintUsed = false
    @State private var attempt: ReviewAttempt?
    @State private var windowStarted = Date.now
    @State private var phase: Phase = .asking
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
        current?.questions.sorted(by: { $0.variantIndex < $1.variantIndex }).first
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
            resetCard()
            startSession()
        }
        .onDisappear { speaker.stop() }
    }

    private var header: some View {
        HStack(spacing: 12) {
            CoachMark(pose: reviewPose, size: 44)
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
            if phase != .summary {
                Button(String(localized: "暂停")) { pause() }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 16)
        .background(.clear)
    }

    private var reviewPose: CoachPose {
        switch phase {
        case .asking, .answering: .whistle
        case .grading: .working
        case .feedback: .idle
        case .failed, .summary: .waitYou
        }
    }

    private func questionBody(_ item: Knowledge, _ question: Question) -> some View {
        RunwayCard(padding: 28) {
            VStack(alignment: .leading, spacing: 20) {
            Text(phaseCaption)
                .font(.subheadline)
                .foregroundStyle(phase == .failed ? Color.orange : runway.agent)

            Text(question.promptText)
                .font(.system(size: 26, weight: .semibold, design: .rounded))
                .textSelection(.enabled)

            Text(item.learningGoal)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if phase == .answering || phase == .asking {
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
                HStack {
                    if !hintUsed {
                        Button(String(localized: "给我提示")) { giveHint() }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    RunwayPrimaryButton(
                        title: String(localized: "我答完了"),
                        enabled: !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && phase != .grading,
                        action: { Task { await submit(item, question) } }
                    )
                    .keyboardShortcut(.return, modifiers: [.command])
                }
            }

            if phase == .grading {
                Text(String(localized: "正在判断"))
                    .foregroundStyle(.secondary)
                ProgressView()
                    .controlSize(.small)
            }

            if phase == .failed {
                Text(feedback)
                    .foregroundStyle(.orange)
                Button(String(localized: "再试一次")) {
                    Task { await submit(item, question) }
                }
                .buttonStyle(.plain)
                .foregroundStyle(runway.action)
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
                        action: { finish(grade: agentGrade, item: item) }
                    )
                    HStack {
                        Text(String(localized: "改判"))
                            .foregroundStyle(.secondary)
                        ForEach(["again", "hard", "good"], id: \.self) { grade in
                            if grade != agentGrade {
                                GradeChip(title: MasteryCopy.label(grade)) {
                                    finish(grade: grade, item: item)
                                }
                            }
                        }
                    }
                    Button(String(localized: "太简单了")) { finish(grade: "easy", item: item) }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                        .font(.caption)
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
                            .foregroundStyle(runway.agent)
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
        case .feedback: String(localized: "判断结果")
        case .failed: String(localized: "本题尚未计入复习")
        case .summary: ""
        }
    }

    private func startSession() {
        windowStarted = .now
        phase = .answering
        let snapshot = coordinator.knowledgeIDs.map(\.uuidString).joined(separator: ",")
        let model = ReviewSession(mode: coordinator.mode, snapshotJSON: snapshot)
        session = model
        modelContext.insert(model)
        try? modelContext.save()
        if let question {
            speaker.speak(question.promptText) {
                if phase == .asking { phase = .answering }
            }
        } else {
            phase = .summary
        }
    }

    private func resetCard() {
        answer = ""
        feedback = ""
        agentGrade = ""
        hintUsed = false
        attempt = nil
        phase = .answering
    }

    private func giveHint() {
        hintUsed = true
    }

    private func submit(_ item: Knowledge, _ question: Question) async {
        guard let session else { return }
        speaker.stop()
        phase = .grading
        let spec = (try? JSONDecoder().decode(AgentAPI.ScoringSpec.self, from: Data(question.scoringSpecJSON.utf8)))
            ?? AgentAPI.ScoringSpec(
                learningGoal: item.learningGoal,
                mustCover: [item.learningGoal],
                acceptableParaphrases: [],
                commonMisconceptions: [],
                evidence: item.evidenceExcerpt,
                orderRules: ""
            )
        let row = ReviewAttempt(
            sessionId: session.id,
            knowledgeId: item.id,
            knowledgeVersion: item.version,
            questionId: question.id,
            mode: coordinator.mode
        )
        row.hintUsed = hintUsed
        row.answerText = answer
        row.degradedPath = "text"
        attempt = row
        modelContext.insert(row)
        do {
            let graded = try await AgentAPI.grade(
                attemptId: row.attemptId,
                promptText: question.promptText,
                scoringSpec: spec,
                answerText: answer,
                hintUsed: hintUsed,
                primaryLanguage: UserLanguage.primaryCode
            )
            agentGrade = graded.agentGrade
            feedback = graded.briefFeedback
            row.agentGrade = graded.agentGrade
            try modelContext.save()
            phase = .feedback
        } catch {
            feedback = String(localized: "本题尚未计入复习。可以再试一次，不要把这次当作已掌握。")
            agentGrade = ""
            phase = .failed
        }
    }

    private func finish(grade: String, item: Knowledge) {
        guard let attempt, let session else { return }
        if isPreview {
            attempt.effectiveGrade = grade
            attempt.acked = true
            finished.append(FinishedItem(goal: item.learningGoal, grade: grade, dueAt: nil))
            try? modelContext.save()
            endNote = String(localized: "预览结束，排期没有变化。")
            phase = .summary
            session.endedAt = .now
            session.endReason = "preview_done"
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
        attempt.effectiveGrade = grade
        var due = item.dueAt
        if let state = fsrsRows.first(where: { $0.knowledgeId == item.id }) {
            Fsrs.apply(grade: grade, to: state)
            item.dueAt = state.dueAt
            item.forceDue = false
            due = state.dueAt
        }
        finished.append(FinishedItem(goal: item.learningGoal, grade: grade, dueAt: due))
        Task {
            try? await AgentAPI.ackAttempt(attemptId: attempt.attemptId)
            attempt.acked = true
            try? modelContext.save()
        }
        advance(session: session)
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
    case asking, answering, grading, feedback, failed, summary
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
