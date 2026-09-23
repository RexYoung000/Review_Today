import Foundation
import Observation

@Observable
final class ReviewCoordinator {
    var mode = "formal"
    var knowledgeIDs: [UUID] = []
    var previewQuestionID: UUID?
    var summarySessionID: UUID?
    var openNonce = 0

    func startPreview(knowledgeID: UUID, questionID: UUID) {
        summarySessionID = nil
        mode = "preview"
        knowledgeIDs = [knowledgeID]
        previewQuestionID = questionID
        openNonce += 1
    }

    func startFormal(knowledgeIDs: [UUID]) {
        summarySessionID = nil
        mode = "formal"
        self.knowledgeIDs = knowledgeIDs
        previewQuestionID = nil
        openNonce += 1
    }

    func showSummary(sessionID: UUID) {
        mode = "formal"; summarySessionID = sessionID
        previewQuestionID = nil; knowledgeIDs = []; openNonce += 1
    }
}
