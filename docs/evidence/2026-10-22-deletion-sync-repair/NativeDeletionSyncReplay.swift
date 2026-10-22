@testable import ReviewTodayContractSupport
import Foundation
import SwiftData

@main
struct NativeDeletionSyncReplay {
    @MainActor static func main() async throws {
        let directory = URL(fileURLWithPath: CommandLine.arguments[1])
        let endpoint = CommandLine.arguments[2]
        let components = URLComponents(string: endpoint)!
        precondition(components.scheme == "http" && components.host == "127.0.0.1" && components.port != nil && components.port != 8742)
        let config = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("config.json"))) as! [String: Any]
        let scenario = config["scenario"] as! String
        let marker = config["marker"] as! [String: Any]
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: directory.appendingPathComponent("app.store")))
        let context = container.mainContext; context.autosaveEnabled = false
        if scenario != "real" {
            let settings = AppSettings(); context.insert(settings)
            settings.sessionDeletionsJSON = ConversationProcessor.json([marker]); try context.save()
        }
        let original = try SessionDeletion.records(context)
        let pendingBefore = original.filter { $0["cleaned"] as? Bool != true }.count
        precondition(scenario == "real" ? pendingBefore == 37 : pendingBefore == 1)
        var sent: [[String: Any]] = []
        var scopeBlocked = 0
        let request: HarnessProcessor.Request = { route, body in
            guard route == "/v2/sessions/\(marker["session_id"]!)/actions" else {
                scopeBlocked += 1
                throw HarnessAPIError.server(code: "RT.QA.OUT_OF_SCOPE", message: "other retained markers are outside this replay")
            }
            sent.append(body!)
            var request = URLRequest(url: URL(string: endpoint+route)!)
            request.httpMethod = "POST"; request.timeoutInterval = 10
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body!)
            let (data,response) = try await URLSession.shared.data(for: request)
            let value = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            if (response as! HTTPURLResponse).statusCode >= 400 {
                let detail = value["detail"] as! [String: Any]
                throw HarnessAPIError.server(code: detail["error_code"] as! String, message: "isolated route result")
            }
            return value
        }
        await SessionDeletion.cleanPending(context: context, request: request)
        if scenario == "lost_ack_v2" {
            let pending = try SessionDeletion.records(ModelContext(container))
            precondition(pending[0]["cleaned"] as? Bool == false)
            await SessionDeletion.cleanPending(context: context, request: request)
        }
        let shouldClear = ["real","active_v2","lost_ack_v2"].contains(scenario)
        let persisted = try SessionDeletion.records(ModelContext(container))
        precondition((persisted[0]["cleaned"] as? Bool == true) == shouldClear)
        let pendingAfter = persisted.filter { $0["cleaned"] as? Bool != true }.count
        precondition(pendingAfter == pendingBefore - (shouldClear ? 1 : 0))
        if scenario == "real" {
            let retained = try JSONSerialization.data(withJSONObject: Array(persisted.dropFirst()), options: .sortedKeys)
            let originalRetained = try JSONSerialization.data(withJSONObject: Array(original.dropFirst()), options: .sortedKeys)
            precondition(retained == originalRetained)
        }
        if shouldClear {
            let before = sent.count
            await SessionDeletion.cleanPending(context: context, request: request)
            precondition(sent.count == before)
        }
        let result: [String: Any] = ["scenario":scenario,"cleared":shouldClear,"requests":sent,"pending_before":pendingBefore,
                                   "pending_after":pendingAfter,"unrelated_marker_requests_blocked":scopeBlocked,"new_model_requests":0,"new_web_operations":0]
        try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted,.sortedKeys]).write(to: directory.appendingPathComponent("native-result.json"))
        print("PASS native + isolated production HTTP: \(scenario), requests=\(sent.count), cleared=\(shouldClear)")
    }
}
