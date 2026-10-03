@testable import ReviewTodayContractSupport
import AppKit
import Foundation
import Observation

/// All audio and transport dependencies are synthetic. The app module's actual
/// voice state machines still own VAD, commits, playback receipts and teardown.
@MainActor final class VoiceFixtureSocket: AgentVoiceSocket {
    var nextText = ""
    private var queued: [Data] = []
    private var waiter: CheckedContinuation<Data, Error>?
    private var closed = false
    private var transcriptions: [UUID: Task<Void, Never>] = [:]
    private var speech: Task<Void, Never>?
    func resume() { push(["type": "ready", "model": "synthetic-native-fixture"]) }
    func receive() async throws -> Data {
        if !queued.isEmpty { return queued.removeFirst() }
        if closed { throw CancellationError() }
        return try await withCheckedThrowingContinuation { waiter = $0 }
    }
    func send(_ data: Data) async throws {
        guard !closed else { throw CancellationError() }
        let event = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        switch event["type"] as? String {
        case "commit_audio":
            let id = UUID(uuidString: event["utterance_id"] as! String)!
            let generation = event["generation"] as! Int, text = nextText
            transcriptions[id] = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(650))
                guard !Task.isCancelled, let self, !self.closed else { return }
                self.push(["type": "transcript", "text": text, "utterance_id": id.uuidString, "generation": generation])
                self.transcriptions[id] = nil
            }
        case "speak":
            let id = event["speech_id"] as! String
            speech?.cancel()
            speech = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(500))
                guard !Task.isCancelled, let self, !self.closed else { return }
                self.push(["type": "audio", "speech_id": id, "audio": Data(repeating: 0, count: 480).base64EncodedString()])
                self.push(["type": "speech_done", "speech_id": id])
            }
        case "interrupt": speech?.cancel(); speech = nil
        case "clear":
            if event["cancel_transcripts"] as? Bool != false {
                transcriptions.values.forEach { $0.cancel() }; transcriptions.removeAll()
            }
        default: break
        }
    }
    func close() {
        closed = true; speech?.cancel(); speech = nil
        transcriptions.values.forEach { $0.cancel() }; transcriptions.removeAll()
        waiter?.resume(throwing: CancellationError()); waiter = nil
    }
    func push(_ event: [String: Any]) {
        guard !closed else { return }
        let data = try! JSONSerialization.data(withJSONObject: event)
        if let waiter { self.waiter = nil; waiter.resume(returning: data) }
        else { queued.append(data) }
    }
}

@MainActor final class VoiceFixtureDevice: AgentVoiceDevice {
    var input: (@MainActor (AgentVoiceSample) -> Void)?
    var output: (@MainActor (Double) -> Void)?
    private var enabled = true
    private var playback: Task<Void, Never>?
    func start(input: @escaping @MainActor (AgentVoiceSample) -> Void,
               outputLevel: @escaping @MainActor (Double) -> Void) throws {
        self.input = input; output = outputLevel; enabled = true
    }
    func schedule(_ pcm: Data, played: @escaping @MainActor () -> Void) throws {
        playback = Task { [weak self] in
            for index in 0..<42 {
                guard !Task.isCancelled, let self else { return }
                self.output?(index % 13 < 2 ? 0 : 0.025 + 0.065 * pow(sin(Double(index) * 0.71), 2))
                try? await Task.sleep(for: .milliseconds(50))
            }
            guard !Task.isCancelled else { return }
            self?.output?(0); played()
        }
    }
    func setInputEnabled(_ enabled: Bool) { self.enabled = enabled }
    func interrupt() { playback?.cancel(); playback = nil; output?(0) }
    func stop() { interrupt(); input = nil; output = nil }
    func feed(level: Double) {
        if enabled { input?(AgentVoiceSample(data: Data(repeating: 0, count: 1920), level: level)) }
    }
}

@MainActor private final class VoiceFixtureDependencies {
    var socket: VoiceFixtureSocket?
    var device: VoiceFixtureDevice?
    func makeSocket() -> VoiceFixtureSocket { let value = VoiceFixtureSocket(); socket = value; return value }
    func makeDevice() -> VoiceFixtureDevice { let value = VoiceFixtureDevice(); device = value; return value }
}

@MainActor @Observable final class AgentVoiceIntegrationState {
    let voice: AgentVoiceConversation
    let owner = UUID()
    var draft = "原有文字草稿：明天再整理 RAG 的例子。"
    let originalDraft = "原有文字草稿：明天再整理 RAG 的例子。"
    var dark = false
    var reduced = false
    var focusRequest = 0
    private(set) var injecting = false
    private(set) var turn = 0
    private(set) var automaticTesting = false
    private(set) var automaticStatus = ""
    private(set) var messages: [AgentVoiceConversation.Message] = []
    private(set) var playback: [UUID: AgentVoicePlayback] = [:]
    var editorAudit = "可用“检查编辑器”核对原生实例。"
    var exportStatus = ""
    @ObservationIgnored private let dependencies: VoiceFixtureDependencies
    @ObservationIgnored private var running: Set<UUID> = []
    @ObservationIgnored private var responseTasks: [UUID: Task<Void, Never>] = [:]
    @ObservationIgnored private var inputTask: Task<Void, Never>?
    @ObservationIgnored private var automaticTask: Task<Void, Never>?
    @ObservationIgnored private var trace: [String] = []
    private let utterances = ["先解释一下 RAG 的作用。", "那检索这一步具体做什么？", "帮我用一句话记住它。"]
    private let answers = [
        "RAG 会先检索相关资料，再让模型根据资料回答。\n这能让回答更容易核对来源。",
        "检索会从资料中找到与问题相关的片段。\n上一轮说的生成阶段，随后就会使用这些片段。",
        "先找资料，再结合资料作答，就是 RAG 的基本流程。\n这句话保留在同一段聊天里。"
    ]
    init() {
        let dependencies = VoiceFixtureDependencies()
        self.dependencies = dependencies
        let audio = AgentVoiceAudio(permission: { true }, makeSocket: { _ in dependencies.makeSocket() },
            makeDevice: { dependencies.makeDevice() },
            serviceURL: { URL(string: "http://127.0.0.1:18742")! }, requireSending: {})
        voice = AgentVoiceConversation(audio: audio)
    }
    var nextTitle: String { "模拟第 \(min(turn + 1, 3)) 轮发言" }
    var canSpeak: Bool { voice.active && voice.audio.connected && !voice.audio.muted && !injecting }
    func start() {
        guard !voice.active else { return }
        trace.append("start")
        voice.start(ownerID: owner, read: { [weak self] in
            guard let self else { return .init(active: false) }
            return .init(messages: self.messages, active: true, runningIDs: self.running)
        }, submit: { [weak self] in self?.submit($0) }, stopReply: { [weak self] in
            guard let self else { return false }
            self.trace.append("stop-reply")
            for id in self.running {
                self.responseTasks.removeValue(forKey: id)?.cancel()
                for index in self.messages.indices where self.messages[index].runID == id && self.messages[index].role != "user" {
                    self.messages[index].state = "interrupted"
                }
            }
            self.running.removeAll()
            return true
        }, persist: { [weak self] id, record in
            self?.playback[id] = record
            self?.trace.append("playback:\(record.state):\(record.played.count)")
            return true
        })
    }
    func speak(interrupt: Bool = false) {
        guard canSpeak else { return }
        let text = interrupt ? "先停一下，换个例子。" : utterances[min(turn, 2)]
        dependencies.socket?.nextText = text
        trace.append(interrupt ? "synthetic-barge-in" : "synthetic-input")
        injecting = true
        inputTask = Task { [weak self] in
            for index in 0..<24 {
                guard !Task.isCancelled, let self, self.voice.active else { return }
                self.dependencies.device?.feed(level: 0.02 + 0.075 * pow(sin(Double(index) * 0.8), 2))
                try? await Task.sleep(for: .milliseconds(60))
            }
            for _ in 0..<29 {
                guard !Task.isCancelled, let self, self.voice.active else { return }
                self.dependencies.device?.feed(level: 0)
                try? await Task.sleep(for: .milliseconds(60))
            }
            self?.injecting = false
        }
    }
    private func submit(_ text: String) -> UUID {
        turn += 1
        let run = UUID(), input = UUID(), response = UUID()
        let answer = text.contains("先停一下") ? "好的，我们换一个例子。\n先查资料，再组织回答，就像开卷作答。" : answers[min(turn - 1, 2)]
        messages.append(.init(id: input, runID: run, role: "user", content: text))
        messages.append(.init(id: response, runID: run, role: "coach", content: "", state: "streaming"))
        running.insert(run); trace.append("submitted:\(turn)")
        responseTasks[run] = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(950))
            guard !Task.isCancelled, let self,
                  let index = self.messages.firstIndex(where: { $0.id == response }) else { return }
            self.messages[index].content = String(answer.split(separator: "\n")[0]) + "\n"
            self.voice.refresh()
            try? await Task.sleep(for: .milliseconds(900))
            guard !Task.isCancelled else { return }
            self.messages[index].content = answer; self.messages[index].state = "complete"
            self.running.remove(run); self.responseTasks[run] = nil; self.voice.refresh()
        }
        return input
    }
    func toggleMute() { trace.append("toggle-mute"); voice.audio.toggleMute() }
    func verifyDuringPlayback(mute: Bool) {
        guard canSpeak, !automaticTesting else { return }
        let startingTurn = turn
        automaticTesting = true
        automaticStatus = "正在模拟发言；等正式音频层进入播报后执行\(mute ? "静音" : "打断")…"
        speak()
        automaticTask = Task { [weak self] in
            let deadline = ContinuousClock.now.advanced(by: .seconds(25))
            while !Task.isCancelled, ContinuousClock.now < deadline {
                guard let self, self.voice.active, self.voice.audio.connected else { break }
                if self.turn > startingTurn, !self.injecting, self.voice.audio.playingSpeech {
                    try? await Task.sleep(for: .milliseconds(400))
                    guard !Task.isCancelled, self.canSpeak, self.voice.audio.playingSpeech else { continue }
                    if mute {
                        self.trace.append("automatic_mute_while_playing=true")
                        self.toggleMute()
                        self.trace.append("automatic_mute_kept_playing=\(self.voice.audio.playingSpeech)")
                        self.automaticStatus = "已在播报中静音；保留静音状态，播报继续。"
                    } else {
                        self.trace.append("automatic_barge_in_while_playing=true")
                        self.speak(interrupt: true)
                        try? await Task.sleep(for: .milliseconds(300))
                        guard !Task.isCancelled else { break }
                        let stopped = !self.voice.audio.playingSpeech && self.voice.audio.capturingSpeech
                        self.trace.append("automatic_barge_in_completed=\(stopped)")
                        self.automaticStatus = stopped ? "已在播报中开口，正式状态已切换为听你说。" : "已触发开口；请查看状态与运行记录。"
                    }
                    self.automaticTesting = false; self.automaticTask = nil
                    return
                }
                try? await Task.sleep(for: .milliseconds(40))
            }
            guard let self, !Task.isCancelled else { return }
            self.automaticTesting = false; self.automaticTask = nil
            self.automaticStatus = "本次自动检查未等到播报，请重新开始。"
            self.trace.append("automatic_playback_check_timed_out_or_ended")
        }
    }
    func fail() { dependencies.socket?.push(["type": "error", "code": "SYNTHETIC_FAILURE"]) }
    func end() {
        automaticTask?.cancel(); automaticTask = nil; automaticTesting = false
        inputTask?.cancel(); inputTask = nil; injecting = false
        voice.end(); focusRequest += 1; trace.append("end:draft-preserved=\(draft == originalDraft)")
    }
    func close() {
        end(); responseTasks.values.forEach { $0.cancel() }; responseTasks.removeAll()
    }
    func export() {
        let root = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent("docs/evidence/2026-10-03-agent-voice-poc")
        let result: [String: Any] = [
            "mode": "Actual production audio/coordinator/panel; synthetic input, fake socket and device; no microphone, network, model or speaker playback.",
            "submitted_turns": turn, "active": voice.active, "draft_preserved": draft == originalDraft,
            "pending_transcriptions": voice.audio.pendingTranscriptions, "trace": trace,
            "messages": messages.map { ["role": $0.role, "content": $0.content, "state": $0.state] },
            "playback": playback.map { ["message_id": $0.key.uuidString, "record": $0.value.json] }
        ]
        do {
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            let original = root.appendingPathComponent("native-controlled-run.json")
            let target = FileManager.default.fileExists(atPath: original.path)
                ? root.appendingPathComponent("native-controlled-run-\(Int(Date.now.timeIntervalSince1970 * 1000)).json") : original
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
                .write(to: target, options: .atomic)
            exportStatus = "运行记录已保存：\(target.lastPathComponent)"
        } catch { exportStatus = "导出失败：\(error.localizedDescription)" }
    }
}

enum AgentVoiceIntegrationIsolation {
    static func prepare() throws {
        guard Bundle.main.bundleIdentifier == "Rex.Review-Today.AgentVoiceIntegration",
              let expected = Bundle.main.object(forInfoDictionaryKey: "AgentVoiceIntegrationHome") as? String,
              let configured = ProcessInfo.processInfo.environment["CFFIXED_USER_HOME"] else { throw CocoaError(.fileReadNoPermission) }
        let home = URL(fileURLWithPath: expected, isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
        let actual = URL(fileURLWithPath: configured, isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!.standardizedFileURL.resolvingSymlinksInPath()
        guard home == actual, home.lastPathComponent == "isolated-home",
              home.deletingLastPathComponent().lastPathComponent == "agent-voice-integration",
              support.path.hasPrefix(home.path + "/") else { throw CocoaError(.fileReadNoPermission) }
    }
}
