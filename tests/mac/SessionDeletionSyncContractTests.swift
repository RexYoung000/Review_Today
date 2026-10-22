import Foundation
import SwiftData

@main
struct SessionDeletionSyncContractTests {
    static func require(_ value: Bool, _ message: String = "Contract failed") { precondition(value, message) }
    @MainActor static var containers: [ModelContainer] = []

    static func canonical(_ value: [String: Any]) -> Data { try! JSONSerialization.data(withJSONObject: value, options: .sortedKeys) }

    static func marker(_ revision: Int, archive: Bool = true) -> [String: Any] {
        var value: [String: Any] = ["session_id": UUID().uuidString.lowercased(), "action_id": UUID().uuidString.lowercased(),
                                   "action": "delete", "lifecycle_revision": revision, "cleaned": false]
        if archive { value["archive_action_id"] = UUID().uuidString.lowercased() }
        return value
    }

    @MainActor static func fixture(_ markers: [[String: Any]]) throws -> (ModelContainer, ModelContext, AppSettings) {
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        containers.append(container)
        let context = container.mainContext
        context.autosaveEnabled = false
        let settings = AppSettings()
        settings.sessionDeletionsJSON = ConversationProcessor.json(markers)
        context.insert(settings)
        try context.save()
        return (container, context, settings)
    }

    @MainActor static func main() async throws {
        // The failing legacy marker must reach the original delete, never archive revision zero.
        do {
            let original = marker(1)
            let (container, context, _) = try fixture([original])
            var sent: [[String: Any]] = []
            let request: HarnessProcessor.Request = { path, body in
                require(path == "/v2/sessions/\(original["session_id"]!)/actions")
                let body = body!; sent.append(body)
                if body["action"] as? String == "archive" {
                    throw HarnessAPIError.server(code: "RT.SESSION.INVALID_ACTION", message: "invalid archive revision")
                }
                return ["status": "deleted"]
            }
            await SessionDeletion.cleanPending(context: context, request: request)
            require(sent.count == 1 && sent[0]["action"] as? String == "delete")
            require(canonical(sent[0]) == canonical(original), "delete body and identity stay unchanged")
            let persisted = try SessionDeletion.records(ModelContext(container))
            require(persisted[0]["cleaned"] as? Bool == true)
            await SessionDeletion.cleanPending(context: context, request: request)
            require(sent.count == 1, "a successful cleanup is not sent again")
        }
        // A normal offline archive still precedes deletion and keeps both original identities.
        do {
            let original = marker(2)
            let (_, context, _) = try fixture([original])
            var sent: [[String: Any]] = []
            await SessionDeletion.cleanPending(context: context, request: { _, body in
                sent.append(body!)
                return ["status": body!["action"] as? String == "archive" ? "archived" : "deleted"]
            })
            require(sent.count == 2 && sent[0]["action"] as? String == "archive" && sent[0]["lifecycle_revision"] as? Int == 1)
            require(sent[0]["action_id"] as? String == original["archive_action_id"] as? String)
            require(canonical(sent[1]) == canonical(original))
        }
        // Lost delete ACK: retry the same two actions; only the returned delete ACK clears the queue.
        do {
            let original = marker(6)
            let (_, context, settings) = try fixture([original])
            var sent: [[String: Any]] = []
            var firstDelete = true
            let request: HarnessProcessor.Request = { _, body in
                let value = body!; sent.append(value)
                if value["action"] as? String == "archive" {
                    if sent.count > 2 { throw HarnessAPIError.server(code: "RT.SESSION.VERSION_CONFLICT", message: "already advanced") }
                    return ["status": "archived"]
                }
                if firstDelete { firstDelete = false; throw HarnessAPIError.http(503) }
                return ["status": "deleted"]
            }
            await SessionDeletion.cleanPending(context: context, request: request)
            require(SessionDeletion.pendingCount(settings.sessionDeletionsJSON) == 1)
            await SessionDeletion.cleanPending(context: context, request: request)
            require(sent.count == 4 && SessionDeletion.pendingCount(settings.sessionDeletionsJSON) == 0)
            require(canonical(sent[0]) == canonical(sent[2]))
            require(canonical(sent[1]) == canonical(sent[3]))
            require(sent[0]["lifecycle_revision"] as? Int == 5 && sent[1]["lifecycle_revision"] as? Int == 6)
        }
        // Unrelated archive failure blocks deletion and leaves this and following markers untouched.
        do {
            let originals = [marker(2), marker(1)]
            let (_, context, settings) = try fixture(originals)
            let before = settings.sessionDeletionsJSON
            var calls = 0
            await SessionDeletion.cleanPending(context: context, request: { _, _ in
                calls += 1; throw HarnessAPIError.http(503)
            })
            require(calls == 1 && settings.sessionDeletionsJSON == before)
        }
        // Existing already-deleted handling remains accepted before the idempotent delete.
        do {
            let (_, context, settings) = try fixture([marker(3)])
            var calls = 0
            await SessionDeletion.cleanPending(context: context, request: { _, body in
                calls += 1
                if body!["action"] as? String == "archive" {
                    throw HarnessAPIError.server(code: "RT.SESSION.DELETED", message: "already deleted")
                }
                return ["status": "deleted"]
            })
            require(calls == 2 && SessionDeletion.pendingCount(settings.sessionDeletionsJSON) == 0)
        }
        // A different status cannot certify that cleanup finished.
        do {
            let (_, context, settings) = try fixture([marker(1)])
            await SessionDeletion.cleanPending(context: context, request: { _, _ in ["status": "archived"] })
            require(SessionDeletion.pendingCount(settings.sessionDeletionsJSON) == 1)
        }
        // Invalid deletion versions still reach the server guard unchanged and remain pending.
        do {
            let (_, context, settings) = try fixture([marker(0)])
            var calls = 0
            await SessionDeletion.cleanPending(context: context, request: { _, body in
                calls += 1
                require(body!["action"] as? String == "delete" && body!["lifecycle_revision"] as? Int == 0)
                throw HarnessAPIError.server(code: "RT.SESSION.INVALID_ACTION", message: "invalid delete revision")
            })
            require(calls == 1 && SessionDeletion.pendingCount(settings.sessionDeletionsJSON) == 1)
        }
        // Older markers without a preceding archive identity keep their existing path.
        do {
            let (_, context, settings) = try fixture([marker(1, archive: false)])
            var calls = 0
            await SessionDeletion.cleanPending(context: context, request: { _, body in
                calls += 1; require(body!["action"] as? String == "delete")
                return ["status": "deleted"]
            })
            require(calls == 1 && SessionDeletion.pendingCount(settings.sessionDeletionsJSON) == 0)
        }
        print("PASS: 8 deletion-sync scenarios: legacy v1, valid archive order, lost ACK identity, failed archive, deleted/version guards, receipt status, invalid delete and old markers")
    }
}
