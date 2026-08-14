import Foundation
import Observation

@Observable
final class ReviewCoordinator {
    var mode = "formal"
    var knowledgeIDs: [UUID] = []
    var openNonce = 0

    func startPreview(knowledgeID: UUID) {
        mode = "preview"
        knowledgeIDs = [knowledgeID]
        openNonce += 1
    }

    func startFormal(knowledgeIDs: [UUID]) {
        mode = "formal"
        self.knowledgeIDs = knowledgeIDs
        openNonce += 1
    }
}
