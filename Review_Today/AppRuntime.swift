import Foundation

/// Storage, network and window identity must describe the same runtime.
struct AppRuntime: Equatable {
    enum Mode { case normal, preview, modelValidation }
    let mode: Mode
    var validationDirectory: URL? = nil
    var port = 8742
    var isJevTest = false
    var isPreview: Bool { mode == .preview }
    var isPerformanceQA: Bool {
#if PERFORMANCE_QA
        true
#else
        false
#endif
    }
    var allowsSending: Bool { !isPreview }
    var serviceURL: URL { URL(string: "http://127.0.0.1:\(port)")! }
    var windowSuffix: String {
        if isPerformanceQA { return " · 性能隔离验收" }
        switch mode {
        case .normal: return ""
        case .preview: return " · 界面预览（不可发送）"
        case .modelValidation: return isJevTest ? " · Jev 测试" : " · 真实模型隔离验收"
        }
    }

    static let current: AppRuntime = {
#if PERFORMANCE_QA
        precondition(Bundle.main.bundleIdentifier?.hasSuffix(".PerformanceQA") == true, "Performance QA requires its own app identity")
        return AppRuntime(mode: .preview)
#elseif DEBUG
        do { return try resolve(ProcessInfo.processInfo.environment, bundleID: Bundle.main.bundleIdentifier ?? "") }
        catch { fatalError("Invalid isolated runtime configuration; refusing to open the normal database") }
#else
        return AppRuntime(mode: .normal)
#endif
    }()

    enum ConfigurationError: Error { case invalidIsolation }
    static func resolve(_ environment: [String: String], bundleID: String) throws -> AppRuntime {
        let fixture = environment["REVIEW_TODAY_M1_UI_FIXTURE"]
        let jevFlag = environment["REVIEW_TODAY_JEV_TEST"] ?? "0"
        guard ["0", "1"].contains(jevFlag) else { throw ConfigurationError.invalidIsolation }
        if let directory = environment["REVIEW_TODAY_NATIVE_TEST_DIR"] {
            let url = URL(fileURLWithPath: directory, isDirectory: true).standardizedFileURL
            guard fixture == nil, bundleID.hasSuffix(".NativeQA"),
                  directory.hasPrefix("/"), url.lastPathComponent.hasPrefix("review-today-"),
                  url.path.hasPrefix("/tmp/") || url.path.hasPrefix("/private/tmp/") || url.path.hasPrefix(NSTemporaryDirectory()),
                  let port = Int(environment["REVIEW_TODAY_NATIVE_TEST_PORT"] ?? "18742"),
                  (1024...65535).contains(port), port != 8742 else { throw ConfigurationError.invalidIsolation }
            return AppRuntime(mode: .modelValidation, validationDirectory: url, port: port, isJevTest: jevFlag == "1")
        }
        guard jevFlag == "0" else { throw ConfigurationError.invalidIsolation }
        if let fixture {
            guard ["1", "invalid", "review", "retry", "learning", "today"].contains(fixture) else {
                throw ConfigurationError.invalidIsolation
            }
            return AppRuntime(mode: .preview)
        }
        guard !bundleID.hasSuffix(".NativeQA") else { throw ConfigurationError.invalidIsolation }
        return AppRuntime(mode: .normal)
    }

    func requireSending() throws {
        guard allowsSending else {
            throw HarnessAPIError.server(code: "RT.PREVIEW.SEND_DISABLED", message: "界面预览不发送消息，输入仅用于排版检查。")
        }
    }
}
