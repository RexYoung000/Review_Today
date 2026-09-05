import Foundation

/// The state checkpoint and its event cursor are committed together. Applying
/// replication data cannot call a model, resume a run, or grant write authority.
enum ConversationCheckpoint {
    static func version(_ raw: String?) -> Int {
        ConversationProcessor.object(raw)?["recovery_version"] as? Int ?? 0
    }

    static func merge(_ recovery: [String: Any], into raw: String?, sessionID: UUID, cursor: Int) throws -> String {
        let saved = ConversationProcessor.object(raw) ?? [:]
        var version = saved["recovery_version"] as? Int ?? 0
        var state = saved["checkpoint"] as? [String: Any] ?? [:]
        if let full = recovery["checkpoint"] as? [String: Any] {
            state = full
            version = recovery["version"] as? Int ?? 0
        } else {
            for delta in recovery["deltas"] as? [[String: Any]] ?? [] {
                guard let next = delta["version"] as? Int else { throw invalid() }
                if next <= version { continue }
                guard delta["base_version"] as? Int == version, next == version + 1,
                      let operations = delta["changes"] as? [[String: Any]] else { throw invalid() }
                for operation in operations {
                    guard let path = operation["path"] as? [String], let op = operation["op"] as? String else { throw invalid() }
                    try apply(op, path: path[...], value: operation["value"], to: &state)
                }
                version = next
            }
        }
        guard version == recovery["version"] as? Int,
              let sid = state["session_id"] as? String, UUID(uuidString: sid) == sessionID,
              (state["event_base_seq"] as? Int ?? 0) + (state["events"] as? [Any] ?? []).count == cursor else { throw invalid() }
        return ConversationProcessor.json(["schema_version": 1, "session_id": sessionID.uuidString.lowercased(),
                                            "recovery_version": version, "checkpoint": state])
    }

    private static func apply(_ op: String, path: ArraySlice<String>, value: Any?, to object: inout [String: Any]) throws {
        guard let key = path.first else {
            guard op == "set", let full = value as? [String: Any] else { throw invalid() }
            object = full
            return
        }
        if path.count > 1 {
            guard var child = object[key] as? [String: Any] else { throw invalid() }
            try apply(op, path: path.dropFirst(), value: value, to: &child)
            object[key] = child
            return
        }
        switch op {
        case "set":
            guard let value else { throw invalid() }
            object[key] = value
        case "remove":
            guard object.removeValue(forKey: key) != nil else { throw invalid() }
        case "append":
            if let current = object[key] as? String, let suffix = value as? String { object[key] = current + suffix }
            else if let current = object[key] as? [Any], let suffix = value as? [Any] { object[key] = current + suffix }
            else { throw invalid() }
        default: throw invalid()
        }
    }

    private static func invalid() -> HarnessAPIError {
        .server(code: "RT.SESSION.INVALID_RECOVERY_DELTA", message: "恢复记录未连续保存，正在重新同步")
    }
}
