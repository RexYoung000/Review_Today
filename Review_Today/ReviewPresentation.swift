import SwiftUI

/// Read-only projection of persisted attempts, shared by Today and the review window.
struct ReviewRoundSummary {
    struct Row: Identifiable {
        let entry: ReviewQueueEntry
        let grade: String
        let helped: Bool
        let skipped: Bool
        let completed: Bool
        let dueAt: Date?
        var id: UUID { entry.id }
        var detail: String {
            if skipped { return "本次跳过 · 未评分" }
            if !completed { return "尚未完成 · 未评分" }
            return helped ? "借助帮助完成 · 保留首次回忆表现" : ReviewRecallCopy.label(grade)
        }
        var symbol: String { skipped ? "forward.end" : !completed ? "circle.dashed" : helped || grade == "again" ? "lightbulb" : "checkmark.circle" }
    }
    let rows: [Row]
    let preview: Bool
    let ended: Bool
    var completed: Int { rows.filter(\.completed).count }
    var helped: Int { rows.filter { $0.completed && ($0.helped || $0.grade == "again") }.count }
    var skipped: Int { rows.filter(\.skipped).count }
    var unfinished: Int { rows.count - completed - skipped }
    var full: Bool { ended && !rows.isEmpty && completed == rows.count }
    var title: String { rows.isEmpty ? "现在没有到期内容" : full ? "这一轮，回顾完了" : "这一轮先到这里" }

    init(session: ReviewSession, attempts: [ReviewAttempt]) {
        preview = session.mode == "preview"; ended = session.endedAt != nil
        let matches = attempts.filter { $0.sessionId == session.id }
        rows = ReviewLedger.queue(session).map { entry in
            let attempt = matches.first { $0.attemptId == entry.attemptID }
            let completed = attempt.map { $0.reviewState == "preview_completed" || ($0.reviewState == "completed" && $0.acked) } ?? false
            let schedule = attempt?.schedulerAfterJSON.flatMap { try? JSONDecoder().decode(ReviewScheduleSnapshot.self, from: Data($0.utf8)) }
            return Row(entry: entry, grade: attempt?.effectiveGrade ?? "", helped: attempt?.hintUsed ?? false,
                       skipped: attempt?.reviewState == "skipped", completed: completed, dueAt: completed ? schedule?.dueAt : nil)
        }
    }
}

enum TodayReviewKind { case empty, unenrolled, scheduled, due, paused, finished }

struct TodayReviewProjection {
    let kind: TodayReviewKind
    let due: [Knowledge]
    let resumable: ReviewSession?
    let latest: ReviewSession?
    let nextDue: Date?
    init(knowledge: [Knowledge], sessions: [ReviewSession], developerMode: Bool, now: Date = .now) {
        let active = knowledge.filter { $0.lifecycle == "active" }
        let enrolled = active.filter(\.participatesInReview)
        due = ReviewQueue.ordered(active, developerMode: developerMode, now: now)
        let formal = sessions.filter { $0.protocolVersion == 2 && $0.mode == "formal" }
        resumable = formal.filter { $0.endedAt == nil && !ReviewLedger.queue($0).isEmpty }.max { $0.startedAt < $1.startedAt }
        latest = formal.filter { $0.endedAt != nil && !ReviewLedger.queue($0).isEmpty }.max { ($0.endedAt ?? .distantPast) < ($1.endedAt ?? .distantPast) }
        nextDue = enrolled.map(\.dueAt).min()
        if resumable != nil { kind = .paused }
        else if let date = latest?.endedAt, Calendar.current.isDate(date, inSameDayAs: now) { kind = .finished }
        else if !due.isEmpty { kind = .due }
        else if active.isEmpty { kind = .empty }
        else if enrolled.isEmpty { kind = .unenrolled }
        else { kind = .scheduled }
    }
}

struct ReviewMetricCard: View {
    let title: String
    let value: Int
    var minimumHeight: CGFloat = 76
    @Environment(\.runway) private var palette
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("\(value)").font(.system(size: 30, weight: .semibold)).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity, minHeight: minimumHeight, alignment: .leading).padding(16)
            .background(palette.card, in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
            .shadow(color: palette.liftShadow, radius: 8, y: 2).accessibilityElement(children: .combine)
    }
}

struct ReviewActionButton: View {
    let title: String
    var symbol: String? = nil
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) { if let symbol { Image(systemName: symbol) }; Text(title) }
                .font(.callout.weight(.medium)).padding(.horizontal, 5).padding(.vertical, 3)
        }.buttonStyle(InteractionButtonStyle()).modifier(ReviewKeyboardAction(action: action))
    }
}

struct ReviewKeyboardAction: ViewModifier {
    var radius: CGFloat = 18
    var action: () -> Void
    @FocusState private var focused: Bool
    @Environment(\.isEnabled) private var enabled
    @Environment(\.runway) private var palette
    @ObservedObject private var input = InteractionInputMode.shared
    func body(content: Content) -> some View {
        content.focusable(enabled).focusEffectDisabled().focused($focused)
            .overlay(RoundedRectangle(cornerRadius: radius).strokeBorder(focused && input.keyboardNavigation ? palette.ink : .clear, lineWidth: 1.5).allowsHitTesting(false))
            .onKeyPress(keys: [.return, .space], phases: .down) { _ in
                guard enabled && focused else { return .ignored }; action(); return .handled
            }
    }
}

struct ReviewStartButton: View {
    let title: String
    var enabled = true
    let action: () -> Void
    var body: some View {
        RunwayPrimaryButton(title: title, enabled: enabled, action: action)
            .modifier(ReviewKeyboardAction(radius: 22, action: action))
    }
}

/// Decoration never advances a question or saves a result. Progress survives resizing.
@Observable final class ReviewCompanionState {
    var reaction: String?
    var token = 0
    var time: Double?
    var still = false
    func show(_ reaction: String?, still: Bool = false) {
        token += 1; self.reaction = reaction; self.still = still; time = nil
    }
}

struct ReviewCompanion: View {
    let motion: ReviewCompanionState
    var busy = false
    var listening = false
    var speaking = false
    var count = 1
    @Environment(\.colorScheme) private var scheme
    @Environment(\.brandReduceMotion) private var reduced
    @State private var failed = false
    private var voice: Bool { motion.reaction == nil && !busy && (listening || speaking) }
    var body: some View {
        ZStack {
            MascotWebSurface(configuration: .init(surface: .voice, mode: speaking ? .speaking : .listening,
                level: voice ? 0.28 : 0, reduced: reduced, dark: scheme == .dark, visible: voice,
                material: "graphite", palette: .theme(dark: scheme == .dark)))
                .frame(width: 360, height: 180).scaleEffect(1.6).offset(y: -18)
                .frame(width: 155, height: 155).clipped().opacity(voice ? 1 : 0)
            MrBMotionView(configuration: .init(kind: busy ? "thinking" : motion.reaction ?? "reaction_rest",
                token: motion.token, dark: scheme == .dark, reduced: reduced || motion.still || (motion.reaction == nil && !busy),
                visible: !voice, count: max(1, count), seekTime: motion.time, seekToken: motion.token + 1), onEvent: { event in
                    if event == "failed" { failed = true }
                    if event == "ready" { failed = false }
                }, onTime: { motion.time = $0 })
                .opacity(voice ? 0 : 1)
            if failed { Image(systemName: "book.closed").font(.system(size: 40)).foregroundStyle(.secondary) }
        }.allowsHitTesting(false).accessibilityHidden(true)
    }
}
