import Foundation
import FSRS

/// The app owns dates and event history; the model only supplies recall evidence.
enum Fsrs {
    static let algorithmVersion = "fsrs-6.0"
    static let parameterVersion = "v6-default-r90-10m-no-fuzz-1"
    static var scheduler: FSRS {
        FSRS(parameters: .init(requestRetention: 0.9, w: FSRSDefaults.defaultWv6,
                              enableFuzz: false, enableShortTerm: true,
                              learningSteps: ["10m"], relearningSteps: ["10m"]))
    }

    static func apply(grade: String, to state: FsrsState, now: Date = .now) throws {
        let rating: Rating
        switch grade {
        case "again": rating = .again
        case "hard": rating = .hard
        case "good": rating = .good
        case "easy": rating = .easy
        default: throw ReviewFlowError.invalidResult
        }
        let card: Card
        if state.algorithmVersion == algorithmVersion, let raw = state.schedulerJSON {
            card = try JSONDecoder().decode(Card.self, from: Data(raw.utf8))
        } else {
            // Demo S/D values are not valid FSRS observations. Preserve them in
            // the before snapshot, and bootstrap only at the next real review.
            card = Card(due: state.dueAt)
        }
        let next = try scheduler.next(card: card, now: now, grade: rating).card
        state.schedulerJSON = String(decoding: try JSONEncoder().encode(next), as: UTF8.self)
        state.dueAt = next.due
        state.stability = next.stability
        state.difficulty = next.difficulty
        state.reps = next.reps
        state.lapses = next.lapses
        state.lastEffectiveGrade = grade
        state.algorithmVersion = algorithmVersion
        state.parameterVersion = parameterVersion
    }
}

extension Knowledge {
    var participatesInReview: Bool { reviewEnrollment == nil || reviewEnrollment == "enrolled" }
    func setReviewParticipation(_ enabled: Bool, now: Date = .now) {
        if enabled && reviewEnrollment == "reference" && studiedAt == nil {
            studiedAt = now
            dueAt = now.addingTimeInterval(2 * 3600)
        }
        if !enabled && reviewEnrollment == "reference" { return }
        reviewEnrollment = enabled ? "enrolled" : "paused"
    }
}

enum ReviewQueue {
    static func isDue(_ item: Knowledge, developerMode: Bool, now: Date = .now) -> Bool {
        guard item.lifecycle == "active", item.participatesInReview else { return false }
        if developerMode && item.forceDue { return true }
        if developerMode && item.skipTwoHourWait { return now >= item.createdAt }
        return now >= item.dueAt
    }
    static func ordered(_ items: [Knowledge], developerMode: Bool = false, now: Date = .now) -> [Knowledge] {
        items.filter { isDue($0, developerMode: developerMode, now: now) }.sorted {
            if $0.dueAt != $1.dueAt { return $0.dueAt < $1.dueAt }
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id.uuidString < $1.id.uuidString
        }
    }
}
