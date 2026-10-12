import Foundation
import SwiftData

@main
struct SaveRecoveryHTTPTests {
    static func require(_ value: Bool, _ message: String = "") { precondition(value, message) }
    @MainActor static func main() async throws {
        let endpoint = CommandLine.arguments[1]
        precondition(endpoint.hasPrefix("http://127.0.0.1:"))
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("review-today-http-recovery-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        func http(_ path: String, _ body: [String: Any]?) async throws -> [String: Any] {
            var request = URLRequest(url: URL(string: endpoint + path)!)
            request.timeoutInterval = 10
            if let body {
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
            }
            let (data, response) = try await URLSession.shared.data(for: request)
            let object = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            if (response as! HTTPURLResponse).statusCode >= 400 {
                let detail = object["detail"] as? [String: Any] ?? [:]
                throw HarnessAPIError.server(code: detail["error_code"] as? String ?? "RT.HARNESS.REQUEST_FAILED", message: "受控 HTTP 故障")
            }
            return object
        }
        for scenario in ["saved", "unsaved"] {
            let initial = try await http("/fixture/reset", ["scenario": scenario])
            let view = try JSONDecoder().decode(AgentAPI.LearningTaskView.self, from: JSONSerialization.data(withJSONObject: initial))
            let path = directory.appendingPathComponent(scenario + ".store")
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: path))
            let c = container.mainContext; c.autosaveEnabled = false
            let session = AgentSession(id: UUID(uuidString: view.sessionId)!)
            let task = LearningTask(id: UUID(uuidString: view.taskId)!, sessionID: session.id,
                                    inputMessageID: UUID(uuidString: view.clientMessageId)!, status: "committing")
            task.conversationManaged = true
            let run = AgentRun(id: UUID(uuidString: view.commitRunID!)!, sessionID: session.id)
            run.status = "completed"; run.revision = view.commitRevision!
            c.insert(session); c.insert(task); c.insert(run); try c.save()
            var stoppedDuringClaim = false
            let transport: HarnessProcessor.Request = { route, body in
                let value = try await http(route, body)
                if scenario == "unsaved", route.hasSuffix("/commit-claim"), !stoppedDuringClaim {
                    stoppedDuringClaim = true
                    let stop = AgentRunControl(runID: run.id, sessionID: session.id, action: "stop")
                    stop.sent = true; c.insert(stop)
                    run.revision += 1
                    try c.save()
                }
                return value
            }
            await HarnessProcessor.synchronize(task, context: c, request: transport)
            if scenario == "saved" {
                require(try ModelContext(container).fetch(FetchDescriptor<Knowledge>()).count == view.memoryPackage!.knowledge.count)
                precondition(task.memoryCommitted, "actual disk save survives the HTTP ACK failure")
                _ = try await http("/fixture/stop", [:])
                let stop = AgentRunControl(runID: run.id, sessionID: session.id, action: "stop")
                c.insert(stop); try c.save()
                await HarnessProcessor.synchronize(task, context: c, request: transport)
                await HarnessProcessor.synchronize(task, context: c, request: transport)
                precondition(task.status == "completed")
                let stats = try await http("/fixture/stats", nil)
                precondition(stats["claims"] as? Int == 1 && stats["status"] as? String == "completed")
                precondition(stats["paused"] as? Bool == true && !stop.sent)
            } else {
                require(try c.fetch(FetchDescriptor<Knowledge>()).isEmpty)
                await HarnessProcessor.synchronize(task, context: c, request: transport)
                precondition(task.status == "awaiting_user" && !task.memoryCommitted)
                let before = try await http("/fixture/stats", nil)
                precondition(before["acks"] as? Int == 0 && before["releases"] as? Int == 1)
                _ = try await http("/fixture/retry", [:])
                await HarnessProcessor.synchronize(task, context: c, request: transport)
                precondition(task.status == "completed" && task.memoryCommitted)
                require(try c.fetch(FetchDescriptor<Knowledge>()).count == view.memoryPackage!.knowledge.count)
                let after = try await http("/fixture/stats", nil)
                precondition(after["capture_calls"] as? Int == 1, "explicit retry reuses the completed package")
            }
            print("PASS HTTP + SwiftData: \(scenario)")
        }
    }
}
