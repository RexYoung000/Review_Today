import Foundation

// The production resolver only needs this error type for its unrelated send guard.
enum HarnessAPIError: Error { case server(code: String, message: String) }

@main struct RuntimeConfigCheck {
    static func main() throws {
        let environment = ProcessInfo.processInfo.environment
        let runtime = try AppRuntime.resolve(environment, bundleID: "Rex.Review-Today.ManagedTeaching278.NativeQA")
        precondition(runtime.mode == .modelValidation)
        let expected = URL(fileURLWithPath: environment["REVIEW_TODAY_NATIVE_TEST_DIR"]!, isDirectory: true).standardizedFileURL
        precondition(runtime.validationDirectory?.path == expected.path)
        precondition(runtime.port != 8742 && !runtime.isJevTest)
        var rejected = 0
        for (values, identity) in [
            (environment, "Rex.Review-Today"),
            (environment.merging(["REVIEW_TODAY_NATIVE_TEST_DIR": NSHomeDirectory()]) { _, new in new }, "test.NativeQA"),
            (environment.merging(["REVIEW_TODAY_NATIVE_TEST_PORT": "8742"]) { _, new in new }, "test.NativeQA"),
            (environment.merging(["REVIEW_TODAY_M1_UI_FIXTURE": "learning"]) { _, new in new }, "test.NativeQA")
        ] {
            do { _ = try AppRuntime.resolve(values, bundleID: identity) }
            catch AppRuntime.ConfigurationError.invalidIsolation { rejected += 1 }
        }
        precondition(rejected == 4)
        print("PASS: actual production AppRuntime accepts the independent TMPDIR, NativeQA identity and port; four invalid configurations rejected; no App/database/service opened.")
    }
}
