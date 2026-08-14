import Foundation

enum Fsrs {
    static let algorithmVersion = "fsrs-4.5-demo"
    static let parameterVersion = "1"

    static func apply(grade: String, to state: FsrsState, now: Date = .now) {
        let g = grade.lowercased()
        state.reps += 1
        state.lastEffectiveGrade = g
        switch g {
        case "again":
            state.lapses += 1
            state.stability = max(0.3, state.stability * 0.5)
            state.difficulty = min(10, state.difficulty + 0.8)
            state.dueAt = now.addingTimeInterval(10 * 60)
        case "hard":
            state.stability = max(0.5, state.stability * 1.2)
            state.difficulty = min(10, state.difficulty + 0.15)
            state.dueAt = now.addingTimeInterval(max(state.stability, 0.5) * 24 * 60 * 60)
        case "easy":
            state.stability = max(2, state.stability * 3)
            state.difficulty = max(1, state.difficulty - 0.3)
            state.dueAt = now.addingTimeInterval(state.stability * 24 * 60 * 60)
        default:
            state.stability = max(1, state.stability * 2.5)
            state.difficulty = max(1, state.difficulty - 0.15)
            state.dueAt = now.addingTimeInterval(state.stability * 24 * 60 * 60)
        }
        state.algorithmVersion = algorithmVersion
        state.parameterVersion = parameterVersion
    }
}

enum ReviewQueue {
    static func isDue(_ item: Knowledge, developerMode: Bool, now: Date = .now) -> Bool {
        guard item.lifecycle == "active" else { return false }
        if developerMode && item.forceDue { return true }
        if developerMode && item.skipTwoHourWait { return now >= item.createdAt }
        return now >= item.dueAt
    }
}
