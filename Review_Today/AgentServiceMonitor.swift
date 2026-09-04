import AppKit
import Foundation
import Observation

enum AgentConnectionState: Equatable {
    case unavailable
    case connecting
    case ready
}

struct HealthResponse: Decodable {
    struct ModelRole: Decodable {
        let model: String
        let status: String
        let error: String
        let streaming: String?
    }

    let status: String
    let keyConfigured: Bool
    let modelRoles: [String: ModelRole]
    let conversationProtocol: Int?
    let responseStreamProtocol: Int?

    enum CodingKeys: String, CodingKey {
        case status
        case keyConfigured = "key_configured"
        case modelRoles = "model_roles"
        case conversationProtocol = "conversation_protocol"
        case responseStreamProtocol = "response_stream_protocol"
    }
}

struct AgentCapabilityPresentation: Equatable {
    let connection: AgentConnectionState
    let status: String
    let detail: String
    let notice: String
}

@Observable
final class AgentServiceMonitor {
    private static let healthURL = URL(string: "http://127.0.0.1:8742/healthz")!
    private static let pollInterval: Duration = .seconds(2)
    private static let requestTimeout: TimeInterval = 1.5
    private static let maxLaunchAttempts = 4

    var connection: AgentConnectionState = .connecting
    var keyConfigured = false
    var launchStatus = "正在连接本地学习服务"
    var launchDetail = ""
    private(set) var serviceReachable = false
    private(set) var conversationSupported = false
    private(set) var responseStreamSupported = false
    private(set) var streamNotice = ""
    private(set) var capabilityNotice = ""

    @ObservationIgnored private var pollTask: Task<Void, Never>?
    @ObservationIgnored private var managedProcess: Process?
    @ObservationIgnored private var launchAttempts = 0
    @ObservationIgnored private var nextLaunchAt = Date.distantPast
    @ObservationIgnored private var launchedAt = Date.distantPast
    @ObservationIgnored private var outputTail = ""
    @ObservationIgnored private var terminationObserver: NSObjectProtocol?

    func start() {
        guard pollTask == nil else { return }
        connection = .connecting
        launchStatus = "正在连接本地学习服务"
        if terminationObserver == nil {
            terminationObserver = NotificationCenter.default.addObserver(
                forName: NSApplication.willTerminateNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                self?.managedProcess?.terminate()
            }
        }
        pollTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.ping()
                try? await Task.sleep(for: Self.pollInterval)
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    func retryLaunch() {
        launchAttempts = 0
        nextLaunchAt = .distantPast
        connection = .connecting
        if serviceReachable {
            launchStatus = "正在重新检查学习模型"
            Task { await requestCapabilityProbe() }
        } else {
            launchStatus = "正在重新启动本地学习服务"
            ensureServiceRunning()
        }
    }

    private func requestCapabilityProbe() async {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8742/v2/capabilities/probe")!)
        request.httpMethod = "POST"
        request.timeoutInterval = Self.requestTimeout
        do {
            _ = try await URLSession.shared.data(for: request)
        } catch {
            launchDetail = "模型检查请求失败，服务恢复后会重试"
        }
    }

    private func ping() async {
        var request = URLRequest(url: Self.healthURL)
        request.timeoutInterval = Self.requestTimeout
        request.cachePolicy = .reloadIgnoringLocalCacheData

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                markUnavailable()
                return
            }
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            guard health.status == "ok" else {
                markUnavailable()
                return
            }
            serviceReachable = true
            conversationSupported = health.conversationProtocol == 1
            responseStreamSupported = health.responseStreamProtocol == 1
            if !responseStreamSupported {
                streamNotice = "当前服务不支持实时输出，请重启开发 App 与本地服务。"
            } else if let coach = health.modelRoles["coach"], coach.streaming == "buffered" {
                streamNotice = "当前模型服务只能整段返回；仍可使用，但尚未通过流式验收。"
            } else if health.modelRoles["coach"]?.streaming == "unavailable" {
                streamNotice = "实时输出能力检查未通过；可重试检查，不会静默更换模型。"
            } else if health.modelRoles["coach"]?.streaming == "checking" {
                streamNotice = ""
            } else { streamNotice = "" }
            keyConfigured = health.keyConfigured
            if !conversationSupported {
                connection = .unavailable
                launchStatus = "本地学习服务版本较旧，需要重启服务"
                launchDetail = "输入已保存在本机；请重启开发 App 与本地 Agent 服务"
                return
            }
            let checking = health.modelRoles.values.filter { $0.status == "checking" }
            let unavailable = health.modelRoles.values.filter { $0.status == "unavailable" }
            let presentation = Self.capabilityPresentation(
                checking: checking,
                unavailable: unavailable,
                totalRoleCount: health.modelRoles.count,
                readyDetail: managedProcess == nil ? "已连接现有本地服务" : "由 App 托管本地服务"
            )
            connection = presentation.connection
            capabilityNotice = presentation.notice
            launchStatus = health.keyConfigured ? presentation.status : "学习服务已启动，等待配置模型凭证"
            launchDetail = presentation.detail
            launchAttempts = 0
        } catch {
            markUnavailable()
        }
    }

    static func capabilityPresentation(
        checking: [HealthResponse.ModelRole],
        unavailable: [HealthResponse.ModelRole],
        totalRoleCount: Int,
        readyDetail: String
    ) -> AgentCapabilityPresentation {
        if !checking.isEmpty {
            // Capability probes run in the background. Once health and the
            // conversation protocol are available, they are not the current
            // message's state and must not block the learning workspace.
            return AgentCapabilityPresentation(
                connection: .ready,
                status: "学习服务已连接，正在后台检查能力",
                detail: "",
                notice: ""
            )
        }
        if !unavailable.isEmpty {
            let allUnavailable = unavailable.count == totalRoleCount
            return AgentCapabilityPresentation(
                connection: allUnavailable ? .unavailable : .ready,
                status: allUnavailable ? "学习模型暂不可用；你的输入仍保存在本机" : "学习服务可用，部分能力受限",
                detail: unavailable.map { "\($0.model)：\($0.error)" }.joined(separator: "；"),
                notice: allUnavailable ? "" : "部分学习能力暂不可用；受影响的任务会显示具体原因。"
            )
        }
        return AgentCapabilityPresentation(connection: .ready, status: "学习服务已就绪", detail: readyDetail, notice: "")
    }

    private func markUnavailable() {
        serviceReachable = false
        conversationSupported = false
        capabilityNotice = ""
        if managedProcess?.isRunning == true && Date.now.timeIntervalSince(launchedAt) > 30 {
            launchDetail = "服务启动超时，正在重试；输入仍保存在本机"
            managedProcess?.terminate()
        }
        keyConfigured = false
        ensureServiceRunning()
        if managedProcess?.isRunning == true {
            connection = .connecting
            launchStatus = "本地学习服务启动中；你的输入仍会先保存"
        } else if launchAttempts >= Self.maxLaunchAttempts {
            connection = .unavailable
            launchStatus = "本地学习服务未能启动；你的输入仍保存在本机"
            launchDetail = outputTail.isEmpty
                ? "请检查系统的文件夹访问提示及 agent-service/.venv；允许访问项目目录后重试"
                : outputTail
        } else {
            connection = .connecting
            launchStatus = "正在启动本地学习服务；你的输入仍会先保存"
        }
    }

    private func ensureServiceRunning() {
#if DEBUG
        guard managedProcess?.isRunning != true,
              launchAttempts < Self.maxLaunchAttempts,
              Date.now >= nextLaunchAt else { return }

        let projectRoot: URL
        if let override = ProcessInfo.processInfo.environment["REVIEW_TODAY_PROJECT_ROOT"], !override.isEmpty {
            projectRoot = URL(fileURLWithPath: override, isDirectory: true)
        } else {
            projectRoot = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
        }
        let serviceRoot = projectRoot.appending(path: "agent-service", directoryHint: .isDirectory)
        let python = serviceRoot.appending(path: ".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            launchAttempts = Self.maxLaunchAttempts
            launchDetail = "未找到 agent-service/.venv/bin/python"
            return
        }

        launchAttempts += 1
        let process = Process()
        let pipe = Pipe()
        process.executableURL = python
        process.currentDirectoryURL = serviceRoot
        process.arguments = ["-m", "agent_service.main"]
        let inherited = ProcessInfo.processInfo.environment
        var environment: [String: String] = [
            "PATH": inherited["PATH"] ?? "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": inherited["HOME"] ?? NSHomeDirectory(),
            "TMPDIR": inherited["TMPDIR"] ?? NSTemporaryDirectory(),
            "LANG": inherited["LANG"] ?? "zh_CN.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": serviceRoot.path,
        ]
        for key in ["USER", "LOGNAME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"] {
            if let value = inherited[key] { environment[key] = value }
        }
        process.environment = environment
        process.standardOutput = pipe
        process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let value = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.outputTail = String((self.outputTail + value).suffix(1200))
            }
        }
        process.terminationHandler = { [weak self] finished in
            pipe.fileHandleForReading.readabilityHandler = nil
            Task { @MainActor [weak self] in
                guard let self else { return }
                if self.managedProcess === finished { self.managedProcess = nil }
                self.nextLaunchAt = .now.addingTimeInterval(Double(1 << min(self.launchAttempts, 3)))
                self.launchDetail = self.outputTail.isEmpty
                    ? "服务已退出（\(finished.terminationStatus)），准备重试"
                    : self.outputTail
            }
        }
        do {
            try process.run()
            launchedAt = .now
            managedProcess = process
            launchDetail = "第 \(launchAttempts) 次启动"
        } catch {
            managedProcess = nil
            nextLaunchAt = .now.addingTimeInterval(Double(1 << min(launchAttempts, 3)))
            launchDetail = "启动失败：\(error.localizedDescription)"
        }
#else
        launchAttempts = Self.maxLaunchAttempts
        launchDetail = "发布版尚未内置服务运行时"
#endif
    }
}
