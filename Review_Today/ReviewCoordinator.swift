import Foundation
import Observation

@Observable
final class ReviewCoordinator {
    var mode = "formal"
    var knowledgeIDs: [UUID] = []
    var previewQuestionID: UUID?
    var openNonce = 0

    func startPreview(knowledgeID: UUID, questionID: UUID) {
        mode = "preview"
        knowledgeIDs = [knowledgeID]
        previewQuestionID = questionID
        openNonce += 1
    }

    func startFormal(knowledgeIDs: [UUID]) {
        mode = "formal"
        self.knowledgeIDs = knowledgeIDs
        previewQuestionID = nil
        openNonce += 1
    }
}
