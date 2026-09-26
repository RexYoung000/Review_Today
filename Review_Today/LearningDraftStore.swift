import SwiftData
import Foundation

/// Keeps only failed writes across page unmounts. A model's in-memory value can
/// equal the editor after a failed save; that is not proof the text is durable.
final class LearningDraftStore {
    enum Owner: Hashable { case landing, session(UUID) }
    private var pending: [Owner: String] = [:]
    private var pendingImages: [Owner: Data] = [:]

    func image(sessionID: UUID?, context: ModelContext) throws -> Data? {
        if let value = pendingImages[owner(sessionID)] { return value.isEmpty ? nil : value }
        if let id = sessionID {
            var query = FetchDescriptor<AgentSession>(predicate: #Predicate { $0.id == id })
            query.fetchLimit = 1
            return try context.fetch(query).first?.composerImage
        }
        return try AgentComposerStore.settings(context).agentDraftImage
    }

    func saveImage(_ image: Data?, sessionID: UUID?, context: ModelContext) throws {
        let key = owner(sessionID)
        if let id = sessionID {
            var query = FetchDescriptor<AgentSession>(predicate: #Predicate { $0.id == id })
            query.fetchLimit = 1
            guard let session = try context.fetch(query).first, session.status == "active" else { throw AgentComposerStore.Failure.inactiveSession }
            session.composerImage = image
        } else { try AgentComposerStore.settings(context).agentDraftImage = image }
        pendingImages[key] = image ?? Data()
        try context.save()
        pendingImages[key] = nil
    }

    func imageSent(sessionID: UUID?) { pendingImages[owner(sessionID)] = nil }

    func unsavedText(sessionID: UUID?) -> String? { pending[owner(sessionID)] }

    @discardableResult
    func save(_ text: String, sessionID: UUID?, context: ModelContext, save: (() throws -> Void)? = nil) throws -> Bool {
        let key = owner(sessionID)
        if let id = sessionID {
            var query = FetchDescriptor<AgentSession>(predicate: #Predicate { $0.id == id })
            query.fetchLimit = 1
            guard let session = try context.fetch(query).first, session.status != "deleted" else { pending[key] = nil; return false }
            guard session.composerDraft != text || pending[key] != nil else { return false }
            pending[key] = text
            session.composerDraft = text
        } else {
            let settings = try AgentComposerStore.settings(context)
            guard settings.agentDraftText != text || pending[key] != nil else { return false }
            pending[key] = text
            settings.agentDraftText = text
        }
        if let save { try save() } else { try context.save() }
        pending[key] = nil
        return true
    }

    func discard(_ ids: Set<UUID>) { for id in ids { pending[.session(id)] = nil; pendingImages[.session(id)] = nil } }
    private func owner(_ id: UUID?) -> Owner { id.map(Owner.session) ?? .landing }
}
