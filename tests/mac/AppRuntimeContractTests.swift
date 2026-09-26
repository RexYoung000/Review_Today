import AppKit
import SwiftData

@main
struct AppRuntimeContractTests {
    @MainActor static func main() throws {
        _ = NSApplication.shared
        let preview = AgentServiceMonitor()
        preview.useFixturePresentation()
        precondition(preview.connection != .ready, "UI preview must not advertise a connected service")
        precondition(!preview.keyConfigured && !preview.serviceReachable && !preview.canSubmitMessages)
        let normal = try AppRuntime.resolve([:], bundleID: "Rex.Review-Today")
        let runtime = try AppRuntime.resolve(["REVIEW_TODAY_M1_UI_FIXTURE": "learning"], bundleID: "qa")
        precondition(normal.allowsSending && normal.mode == .normal && normal.port == 8742)
        precondition(runtime.isPreview && !runtime.allowsSending && !runtime.windowSuffix.isEmpty)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("review-today-runtime-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: directory) }
        let environment = ["REVIEW_TODAY_NATIVE_TEST_DIR": directory.path, "REVIEW_TODAY_NATIVE_TEST_PORT": "18742"]
        let validation = try AppRuntime.resolve(environment, bundleID: "com.rexyoung.ReviewToday.NativeQA")
        precondition(validation.mode == .modelValidation && validation.validationDirectory?.path == directory.standardizedFileURL.path)
        precondition(validation.serviceURL.absoluteString == "http://127.0.0.1:18742")
        let jevEnvironment = environment.merging(["REVIEW_TODAY_JEV_TEST": "1"]) { _, new in new }
        let jev = try AppRuntime.resolve(jevEnvironment, bundleID: "Rex.Review-Today.Jev.NativeQA")
        precondition(jev.isJevTest && jev.windowSuffix.contains("Jev 测试") && !normal.isJevTest && !validation.isJevTest)
        let legacyHealth = try JSONDecoder().decode(HealthResponse.self, from: Data(#"{"status":"ok","key_configured":true,"model_roles":{}}"#.utf8))
        precondition(!legacyHealth.supportsJevTest, "old services remain compatible but cannot pretend to enable Jev")
        for (status, model, supported) in [("enabled", "jev-1.13.0", true), ("authentication_disabled", "jev-1.13.0", true),
                                          ("off", "jev-1.13.0", false), ("enabled", "jev-latest", false)] {
            let payload: [String: Any] = ["status": "ok", "key_configured": true, "model_roles": [:],
                "jev": ["status": status, "model": model, "entry_rule": "jev-entry-3"]]
            let health = try JSONDecoder().decode(HealthResponse.self, from: JSONSerialization.data(withJSONObject: payload))
            precondition(health.supportsJevTest == supported, "test identity must match the real service; auth failure remains explicit fallback")
        }
        let wrongRule = try JSONDecoder().decode(HealthResponse.self, from: Data(#"{"status":"ok","key_configured":true,"model_roles":{},"jev":{"status":"enabled","model":"jev-1.13.0","entry_rule":"jev-entry-2"}}"#.utf8))
        precondition(!wrongRule.supportsJevTest, "a stale entry contract must not be labelled ready")
        for (values, bundle) in [
            ([:], "Rex.Review-Today.Image.NativeQA"),
            (environment, "Rex.Review-Today"),
            (["REVIEW_TODAY_JEV_TEST": "1"], "Rex.Review-Today"),
            (["REVIEW_TODAY_JEV_TEST": "1", "REVIEW_TODAY_M1_UI_FIXTURE": "learning"], "Rex.Review-Today.Jev.NativeQA"),
            (environment.merging(["REVIEW_TODAY_JEV_TEST": "yes"]) { _, new in new }, "Rex.Review-Today.Jev.NativeQA"),
            (["REVIEW_TODAY_M1_UI_FIXTURE": "typo"], "com.rexyoung.ReviewToday.NativeQA"),
            (["REVIEW_TODAY_NATIVE_TEST_DIR": "/"], "com.rexyoung.ReviewToday.NativeQA"),
            (environment.merging(["REVIEW_TODAY_NATIVE_TEST_PORT": "8742"]) { _, new in new }, "com.rexyoung.ReviewToday.NativeQA"),
            (environment.merging(["REVIEW_TODAY_M1_UI_FIXTURE": "learning"]) { _, new in new }, "com.rexyoung.ReviewToday.NativeQA")
        ] {
            do { _ = try AppRuntime.resolve(values, bundleID: bundle); preconditionFailure("unsafe isolation must be rejected") }
            catch AppRuntime.ConfigurationError.invalidIsolation {}
        }
        let container = try M1DebugFixture.makeValidationContainer(directory)
        let context = container.mainContext
        let initial = try context.fetch(FetchDescriptor<AgentSession>())
        precondition(initial.isEmpty, "real-model validation starts without seeded samples")
        let draft = try AgentComposerStore.prepare(context)
        draft.agentDraftText = "你好"
        try context.save()
        do { _ = try AgentComposerStore.sendFirst("你好", context: context, runtime: runtime); preconditionFailure("preview submit must fail") }
        catch { precondition(HarnessAPIError.code(for: error) == "RT.PREVIEW.SEND_DISABLED") }
        let rejectedSessions = try context.fetch(FetchDescriptor<AgentSession>())
        let rejectedMessages = try context.fetch(FetchDescriptor<AgentMessage>())
        precondition(rejectedSessions.isEmpty && rejectedMessages.isEmpty && draft.agentDraftText == "你好")
        let (session, message) = try AgentComposerStore.sendFirst("你好", context: context, runtime: normal)
        let messageID = message.clientMessageID
        for response: [String: Any] in [[:], ["run_id": "bad"], ["run_id": NSNull()]] {
            do { try ConversationProcessor.recordAcceptance(response, message: message, context: context); preconditionFailure("invalid run id must fail") }
            catch { precondition(HarnessAPIError.code(for: error) == "RT.RUN.INVALID_ACCEPTANCE") }
            precondition(message.runID == nil && message.deliveryStatus == "local" && message.clientMessageID == messageID)
        }
        message.lastDeliveryError = "RT.RUN.INVALID_ACCEPTANCE"
        precondition(MessageDeliveryPresentation.canRetry(message, session: session, runtime: normal))
        precondition(!MessageDeliveryPresentation.canRetry(message, session: session, runtime: runtime))
        session.status = "archived"
        precondition(!MessageDeliveryPresentation.canRetry(message, session: session, runtime: normal))
        session.status = "active"
        message.deliveryStatus = "held"
        precondition(!MessageDeliveryPresentation.canRetry(message, session: session, runtime: normal))
        message.deliveryStatus = "local"
        precondition(MessageDeliveryPresentation.summary(message, session: session, monitor: preview, runtime: normal).contains("可重试发送"))
        preview.beginDelivery(message.id)
        precondition(MessageDeliveryPresentation.summary(message, session: session, monitor: preview, runtime: normal).contains("正在发送"))
        preview.endDelivery(message.id)
        precondition(MessageDeliveryPresentation.summary(message, session: session, monitor: preview, runtime: runtime).contains("仅在内存"))
        let runID = UUID()
        let accepted: [String: Any] = ["run_id": runID.uuidString, "status": "accepted", "revision": 1]
        enum SaveFailure: Error { case simulated }
        try context.save()
        do {
            try ConversationProcessor.recordAcceptance(accepted, message: message, context: context, save: { throw SaveFailure.simulated })
            preconditionFailure("failed acceptance persistence must roll back")
        } catch SaveFailure.simulated {}
        let rejectedRuns = try context.fetch(FetchDescriptor<AgentRun>())
        precondition(rejectedRuns.isEmpty, "failed save must not leave a Run")
        precondition(message.runID == nil, "failed save must not assign run id")
        precondition(message.deliveryStatus == "local", "failed save must retain local outbox status")
        precondition(message.content == "你好", "failed save must retain input")
        try ConversationProcessor.recordAcceptance(accepted, message: message, context: context)
        try ConversationProcessor.recordAcceptance(accepted, message: message, context: context)
        let runs = try context.fetch(FetchDescriptor<AgentRun>())
        precondition(runs.count == 1 && message.runID == runID && message.clientMessageID == messageID && message.lastDeliveryError == nil)
        let reopened = try M1DebugFixture.makeValidationContainer(directory)
        let persisted = try reopened.mainContext.fetch(FetchDescriptor<AgentMessage>())
        precondition(persisted.count == 1 && persisted.first?.content == "你好", "isolated validation is durable, not a seeded memory fixture")
        let fixture = try M1DebugFixture.makeContainer(mode: "learning")
        let samples = try fixture.mainContext.fetch(FetchDescriptor<AgentRun>())
        precondition(samples.count == 3 && samples.allSatisfy { $0.startedAt == nil && $0.status != "running" }, "static fixtures cannot run an unbounded clock")
        print("PASS: runtime/storage/network identity, preview submit guard, durable isolation, invalid acceptance and stable retry, delivery feedback, bounded static samples")
    }
}
