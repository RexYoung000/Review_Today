@testable import ReviewTodayContractSupport
import Foundation
import SwiftData

@main
struct NativeQueueAudit {
    @MainActor static func main() async throws {
        let directory = URL(fileURLWithPath: CommandLine.arguments[1])
        let endpoint = CommandLine.arguments[2]
        let url = URLComponents(string: endpoint)!
        precondition(url.scheme == "http" && url.host == "127.0.0.1" && url.port != nil && url.port != 8742)
        let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: directory.appendingPathComponent("app.store")))
        let context = container.mainContext; context.autosaveEnabled = false
        let original = try SessionDeletion.records(context)
        precondition(original.count == 37 && original.allSatisfy { $0["cleaned"] as? Bool == false })
        let ids = Set(original.compactMap { $0["session_id"] as? String })
        var requests: [[String: Any]] = []
        let request: HarnessProcessor.Request = { route, body in
            guard let body, let sid = body["session_id"] as? String ?? route.split(separator: "/").dropLast().last.map(String.init),
                  ids.contains(sid), route == "/v2/sessions/\(sid)/actions" else {
                throw HarnessAPIError.server(code: "RT.QA.OUT_OF_SCOPE", message: "outside audited queue")
            }
            var req = URLRequest(url: URL(string: endpoint+route)!)
            req.httpMethod = "POST"; req.timeoutInterval = 10
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (data,response) = try await URLSession.shared.data(for: req)
            let status = (response as! HTTPURLResponse).statusCode
            let result = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            let detail = result["detail"] as? [String: Any]
            requests.append(["session_id":sid,"action":body["action"]!,"revision":body["lifecycle_revision"]!,"status":status,
                             "error":detail?["error_code"] ?? NSNull()])
            if status >= 400 { throw HarnessAPIError.server(code: detail?["error_code"] as? String ?? "RT.QA.HTTP", message: "isolated scope audit") }
            return result
        }
        await SessionDeletion.cleanPending(context: context, request: request)
        let persisted = try SessionDeletion.records(ModelContext(container))
        let cleaned = persisted.filter { $0["cleaned"] as? Bool == true }.count
        for (before,after) in zip(original,persisted) {
            var normalized = after; normalized["cleaned"] = false
            let beforeData = try JSONSerialization.data(withJSONObject:before,options:.sortedKeys)
            let afterData = try JSONSerialization.data(withJSONObject:normalized,options:.sortedKeys)
            precondition(beforeData == afterData)
        }
        let result: [String: Any] = ["pending_before":original.count,"pending_after":persisted.count-cleaned,"cleaned_in_copy":cleaned,
                                   "requests":requests,"all_other_marker_fields_retained":true,"model_requests":0,"web_operations":0]
        try JSONSerialization.data(withJSONObject:result, options:[.prettyPrinted,.sortedKeys]).write(to:directory.appendingPathComponent("native-result.json"))
        print("Native audit finished: copied queue \(original.count) -> \(persisted.count-cleaned), HTTP requests \(requests.count)")
        withExtendedLifetime(container) {}
    }
}
