@testable import ReviewTodayContractSupport
import AppKit
import Foundation
import Observation

/// Injected service for the real controller. No URLSession or audio APIs are used.
@MainActor @Observable
final class IntegrationTransport {
    var failNext = false
    var rawFallback = false
    private(set) var calls: [String] = []

    func perform(_ action: String, data: Data) async throws -> DictationResult {
        calls.append(action)
        let shouldFail = action == "transcribe" && failNext
        if shouldFail { failNext = false }
        try await Task.sleep(for: .milliseconds(action == "transcribe" ? 1_300 : 900))
        try Task.checkCancellation()
        if shouldFail { throw DictationFailure(code: "DICTATION_ACCESS") }
        switch action {
        case "transcribe": return .init(text: "嗯，请把今天的学习整理成三个要点。")
        case "clean":
            if rawFallback { throw URLError(.timedOut) }
            return .init(text: "请把今天的学习整理成三个要点。", raw_text: "嗯，请把今天的学习整理成三个要点。", cleaned: true)
        default: throw URLError(.unsupportedURL)
        }
    }
}

@MainActor @Observable
final class DictationIntegrationState {
    let controller: DictationController
    let transport: IntegrationTransport
    let sessionID = UUID()
    var draft = "原有草稿：先复习 RAG。"
    var focusRequest = 0
    var dark = false
    var reduced = false
    var silent = false
    var failSave = false
    private(set) var savedDraft = "原有草稿：先复习 RAG。"
    private(set) var saveCount = 0
    private(set) var lastSent: String?
    private(set) var fixtureError: String?
    var editorAudit = "点击“检查编辑器”记录正式编辑器实例。"
    @ObservationIgnored private var startedAt: Date?
    @ObservationIgnored private var originalDraft = ""

    init() {
        let transport = IntegrationTransport()
        self.transport = transport
        controller = DictationController(permission: { false }, transport: { action, data in
            try await transport.perform(action, data: data)
        })
        controller.bind(sessionID)
    }

    var panelPhase: DictationComposerPhase {
        switch controller.phase {
        case .idle: .failed
        case .permission: .permission
        case .recording: .recording
        case .transcribing: .transcribing
        case .cleaning: .cleaning
        case .applying: .applying
        }
    }

    func start() {
        guard !controller.busy else { return }
        controller.cancel()
        fixtureError = nil
        originalDraft = draft
        do {
            try FileManager.default.createDirectory(at: DictationFiles.root, withIntermediateDirectories: true)
            // A byte fixture for the injected transport, never playable/recorded audio.
            try Data("SYNTHETIC DICTATION INTEGRATION FIXTURE".utf8).write(to: DictationFiles.audio(sessionID), options: .atomic)
            startedAt = .now
            controller.elapsed = 0
            controller.level = 0
            controller.pending = true
            controller.phase = .recording
        } catch {
            fixtureError = "无法创建隔离样本：\(error.localizedDescription)"
        }
    }

    func tick(_ date: Date) {
        guard controller.phase == .recording, let startedAt else { return }
        controller.elapsed = min(300, max(0, date.timeIntervalSince(startedAt)))
        let time = controller.elapsed
        let position = time.truncatingRemainder(dividingBy: 5.8)
        let speaking = (0.15..<1.35).contains(position) || (1.85..<3.55).contains(position) || (4.35..<5.1).contains(position)
        controller.level = silent || !speaking ? 0 : 0.18 + 0.65 * pow(sin(time * 7.1), 2)
        if controller.elapsed >= 300 { finish() }
    }

    func finish() {
        startedAt = nil
        controller.finish()
    }
    func cancel() {
        guard controller.phase != .applying else { return }
        startedAt = nil
        controller.cancel()
        focusRequest += 1
    }
    func retry() {
        originalDraft = draft
        controller.retry()
    }
    func acceptInsertion(_ text: String) {
        guard controller.owner == sessionID, controller.phase == .applying else { return }
        // Deliberately an in-memory save callback. The editor and the controller
        // perform their real insertion/acknowledgement path unchanged.
        if failSave {
            failSave = false
            draft = originalDraft
            controller.applied(saved: false)
        } else {
            draft = text
            savedDraft = text
            saveCount += 1
            controller.applied(saved: true)
        }
    }
    func send() {
        guard !controller.busy, !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        lastSent = draft
        draft = ""
    }
    func resetDraft() {
        guard !controller.busy else { return }
        draft = "原有草稿：先复习 RAG。"
        lastSent = nil
        focusRequest += 1
    }
    func close() {
        controller.cancel()
        DictationFiles.remove(sessionID)
    }
}

enum DictationIntegrationIsolation {
    static func prepare() throws {
        guard Bundle.main.bundleIdentifier == "Rex.Review-Today.DictationIntegration",
              let expected = Bundle.main.object(forInfoDictionaryKey: "DictationIntegrationHome") as? String,
              let configured = ProcessInfo.processInfo.environment["CFFIXED_USER_HOME"] else {
            throw CocoaError(.fileReadNoPermission)
        }
        let home = URL(fileURLWithPath: expected, isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
        let actual = URL(fileURLWithPath: configured, isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
        let root = DictationFiles.root.standardizedFileURL.resolvingSymlinksInPath()
        guard home == actual, home.lastPathComponent == "isolated-home",
              home.deletingLastPathComponent().lastPathComponent == "dictation-integration",
              root.path.hasPrefix(home.path + "/") else { throw CocoaError(.fileReadNoPermission) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }
}
