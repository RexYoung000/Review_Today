import AVFoundation
import Foundation
import Observation

struct AgentVoiceSample: Sendable {
    let data: Data
    let level: Double
    var duration: Double { Double(data.count) / 32_000 }
}

/// Hardware and transport are injectable; the production state machine is also
/// exercised by the no-microphone, no-network native contracts.
@MainActor protocol AgentVoiceSocket: AnyObject {
    func resume()
    func receive() async throws -> Data
    func send(_ data: Data) async throws
    func close()
}

@MainActor protocol AgentVoiceDevice: AnyObject {
    func start(input: @escaping @MainActor (AgentVoiceSample) -> Void,
               outputLevel: @escaping @MainActor (Double) -> Void) throws
    func schedule(_ pcm: Data, played: @escaping @MainActor () -> Void) throws
    func setInputEnabled(_ enabled: Bool)
    func interrupt()
    func stop()
}

/// POC thresholds are conservative starting points, not a claim of validated
/// Mandarin turn taking or speaker echo rejection.
struct AgentVoiceActivity {
    enum Action { case began(Data), append(Data), commit }
    private(set) var active = false
    private var preRoll = Data()
    private var candidateVoice = 0.0
    private var candidateGap = 0.0
    private var silence = 0.0
    private var capturedBytes = 0
    static let minimumVoice = 0.18
    static let pause = 1.65
    static let maximumUtterance = 90.0

    mutating func consume(_ sample: AgentVoiceSample) -> [Action] {
        guard !sample.data.isEmpty, sample.data.count % 2 == 0,
              sample.data.count <= 64_000, sample.level.isFinite else { return [] }
        let duration = sample.duration
        if !active {
            preRoll.append(sample.data)
            if preRoll.count > 8_000 { preRoll.removeFirst(preRoll.count - 8_000) }
            if sample.level >= 0.012 { candidateVoice += duration; candidateGap = 0 }
            else {
                candidateGap += duration
                if candidateGap >= 0.08 { candidateVoice = 0 }
            }
            guard candidateVoice >= Self.minimumVoice else { return [] }
            active = true; silence = 0; capturedBytes = preRoll.count
            let opening = preRoll
            preRoll.removeAll(keepingCapacity: true)
            return [.began(opening)]
        }
        let maximumBytes = Int(Self.maximumUtterance * 32_000)
        let acceptedBytes = min(sample.data.count, maximumBytes - capturedBytes)
        capturedBytes += acceptedBytes
        silence = sample.level >= 0.009 ? 0 : silence + Double(acceptedBytes) / 32_000
        var actions: [Action] = acceptedBytes > 0 ? [.append(Data(sample.data.prefix(acceptedBytes)))] : []
        if silence >= Self.pause || capturedBytes >= maximumBytes {
            let remainder = Data(sample.data.dropFirst(acceptedBytes))
            reset(); actions.append(.commit)
            if !remainder.isEmpty {
                actions += consume(AgentVoiceSample(data: remainder, level: sample.level))
            }
        }
        return actions
    }

    mutating func finish() -> Bool {
        let hadSpeech = active
        reset()
        return hadSpeech
    }

    mutating func reset() { self = AgentVoiceActivity() }
}

@MainActor @Observable
final class AgentVoiceAudio {
    private(set) var connected = false
    private(set) var connecting = false
    private(set) var muted = false
    private(set) var inputLevel = 0.0
    private(set) var outputLevel = 0.0
    private(set) var capturingSpeech = false
    private(set) var playingSpeech = false
    private(set) var pendingTranscriptions = 0
    private(set) var status = "语音未连接"
    private(set) var error: String?
    var onTranscript: ((String, UUID, Int) -> Void)?
    var onSpeechStart: (() -> Void)?
    var onSpeechPlayed: ((UUID) -> Void)?
    var onFailure: ((String) -> Void)?

    @ObservationIgnored private let permission: @MainActor () async -> Bool
    @ObservationIgnored private let makeSocket: @MainActor (URL) -> any AgentVoiceSocket
    @ObservationIgnored private let makeDevice: @MainActor () -> any AgentVoiceDevice
    @ObservationIgnored private let serviceURL: @MainActor () -> URL
    @ObservationIgnored private let requireSending: @MainActor () throws -> Void
    @ObservationIgnored private let connectionTimeout: Duration
    @ObservationIgnored private let transcriptionTimeout: Duration
    @ObservationIgnored private let playbackTimeout: Duration
    @ObservationIgnored private var socket: (any AgentVoiceSocket)?
    @ObservationIgnored private var device: (any AgentVoiceDevice)?
    @ObservationIgnored private var reader: Task<Void, Never>?
    @ObservationIgnored private var sender: Task<Void, Never>?
    @ObservationIgnored private var transcriptionDeadlines: [UUID: Task<Void, Never>] = [:]
    @ObservationIgnored private var playbackDeadline: Task<Void, Never>?
    @ObservationIgnored private var lifetime = UUID()
    @ObservationIgnored private var ready = false
    @ObservationIgnored private var queuedBytes = 0
    @ObservationIgnored private var activity = AgentVoiceActivity()
    @ObservationIgnored private var utterance: (id: UUID, generation: Int)?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var pending: [UUID: Int] = [:]
    @ObservationIgnored private var speechID: UUID?
    @ObservationIgnored private var playbackToken = UUID()
    @ObservationIgnored private var pendingBuffers: Set<UUID> = []
    @ObservationIgnored private var pendingPlaybackBytes = 0
    @ObservationIgnored private var speechFinished = false
    @ObservationIgnored private var receivedAudio = false

    init(permission: @escaping @MainActor () async -> Bool = { await AVCaptureDevice.requestAccess(for: .audio) },
         makeSocket: @escaping @MainActor (URL) -> any AgentVoiceSocket = { AgentVoiceURLSocket(url: $0) },
         makeDevice: @escaping @MainActor () -> any AgentVoiceDevice = { AgentVoiceEngine() },
         serviceURL: @escaping @MainActor () -> URL = { AppRuntime.current.serviceURL },
         requireSending: @escaping @MainActor () throws -> Void = { try AppRuntime.current.requireSending() },
         connectionTimeout: Duration = .seconds(10),
         transcriptionTimeout: Duration = .seconds(30),
         playbackTimeout: Duration = .seconds(120)) {
        self.permission = permission; self.makeSocket = makeSocket; self.makeDevice = makeDevice
        self.serviceURL = serviceURL; self.requireSending = requireSending
        self.connectionTimeout = connectionTimeout; self.transcriptionTimeout = transcriptionTimeout
        self.playbackTimeout = playbackTimeout
    }

    isolated deinit { stop() }

    /// Called only by an explicit entry action. A cancellation while the system
    /// permission sheet is open cannot connect or start the microphone later.
    func start(ownerID: UUID) async throws {
        stop()
        let token = lifetime
        connecting = true; status = "正在请求麦克风"
        do {
            let allowed = await permission()
            try checkLifetime(token)
            guard allowed else { throw AudioFailure("麦克风未授权，可以用文字继续。") }
            try requireSending()
            var parts = URLComponents(url: serviceURL(), resolvingAgainstBaseURL: false)
            let secure = parts?.scheme == "https"
            parts?.scheme = secure ? "wss" : "ws"
            parts?.path = "/v2/agent/voice/\(ownerID.uuidString.lowercased())/audio"
            guard let url = parts?.url else { throw AudioFailure("语音服务地址不可用。") }
            let transport = makeSocket(url)
            socket = transport; transport.resume()
            status = "正在连接语音"
            reader = Task { [weak self] in
                do {
                    while !Task.isCancelled {
                        let data = try await transport.receive()
                        guard let self, self.lifetime == token else { return }
                        guard let event = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                            throw AudioFailure("语音服务返回了无法读取的数据。")
                        }
                        self.receive(event)
                    }
                } catch {
                    guard let self, self.lifetime == token else { return }
                    self.fail("语音连接已断开，聊天保留，可以用文字继续。")
                }
            }
            let deadline = ContinuousClock.now.advanced(by: connectionTimeout)
            while !ready {
                try checkLifetime(token)
                guard ContinuousClock.now < deadline else { throw AudioFailure("语音连接超时，请重试或用文字继续。") }
                try await Task.sleep(for: .milliseconds(20))
            }
            try checkLifetime(token)
            let hardware = makeDevice()
            device = hardware
            try hardware.start(input: { [weak self] sample in
                guard let self, self.lifetime == token else { return }
                self.capture(sample)
            }, outputLevel: { [weak self] level in
                guard let self, self.lifetime == token, self.speechID != nil else { return }
                self.outputLevel = Self.displayLevel(level)
            })
            try checkLifetime(token)
            connected = true; connecting = false
            refreshStatus()
        } catch {
            guard lifetime == token else { throw CancellationError() }
            if error is CancellationError { stop(); throw error }
            fail((error as? AudioFailure)?.message ?? "音频设备暂不可用，可以用文字继续。")
            throw error
        }
    }

    func stop() {
        lifetime = UUID()
        reader?.cancel(); sender?.cancel(); reader = nil; sender = nil
        socket?.close(); socket = nil
        device?.stop(); device = nil
        transcriptionDeadlines.values.forEach { $0.cancel() }; transcriptionDeadlines.removeAll()
        playbackDeadline?.cancel(); playbackDeadline = nil
        pending.removeAll(); pendingTranscriptions = 0
        resetPlayback()
        activity.reset(); utterance = nil; ready = false; queuedBytes = 0
        connected = false; connecting = false; muted = false; capturingSpeech = false
        inputLevel = 0; outputLevel = 0; status = "语音未连接"; error = nil
    }

    func toggleMute() {
        guard connected else { return }
        muted.toggle(); activity.reset(); utterance = nil; capturingSpeech = false; inputLevel = 0
        device?.setInputEnabled(!muted)
        // A committed answer and current playback survive the input mute.
        enqueue(["type": "clear", "cancel_transcripts": false])
        refreshStatus()
    }

    func finishUtterance() {
        guard connected, !muted, activity.finish() else { return }
        commitUtterance()
    }

    /// Stops playback, including late buffered audio, without throwing away ASR.
    func interrupt() {
        device?.interrupt(); resetPlayback(); outputLevel = 0
        if connected { enqueue(["type": "interrupt"]); refreshStatus() }
    }

    /// The coordinator supplies one approved sentence and waits for playback
    /// completion before scheduling the next. Never silently truncate the text.
    func speak(text: String, id: UUID) {
        guard connected else { return }
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.unicodeScalars.count <= 500 else {
            fail("本句播报文字为空或过长，请看聊天文字继续。")
            return
        }
        interrupt()
        speechID = id; playbackToken = UUID()
        let token = lifetime, playback = playbackToken
        playbackDeadline = Task { [weak self, playbackTimeout] in
            try? await Task.sleep(for: playbackTimeout)
            guard !Task.isCancelled, let self, self.lifetime == token, self.playbackToken == playback else { return }
            self.fail("语音播报等待超时，聊天文字已保留。")
        }
        enqueue(["type": "speak", "text": text, "speech_id": id.uuidString.lowercased()])
        refreshStatus()
    }

    private func checkLifetime(_ token: UUID) throws {
        try Task.checkCancellation()
        guard lifetime == token else { throw CancellationError() }
    }

    private func capture(_ sample: AgentVoiceSample) {
        guard connected, !muted else { return }
        inputLevel = Self.displayLevel(sample.level)
        for action in activity.consume(sample) {
            switch action {
            case .began(let data):
                interrupt()
                generation += 1; utterance = (UUID(), generation); capturingSpeech = true
                onSpeechStart?()
                guard connected, !muted, utterance != nil else { return }
                enqueue(["type": "audio", "audio": data.base64EncodedString()])
            case .append(let data): enqueue(["type": "audio", "audio": data.base64EncodedString()])
            case .commit: commitUtterance()
            }
        }
        refreshStatus()
    }

    private func commitUtterance() {
        guard connected, let binding = utterance else { return }
        utterance = nil; capturingSpeech = false
        guard pending.count < 8 else { fail("待转写的语音过多，已停止采音，请用文字继续。"); return }
        pending[binding.id] = binding.generation; pendingTranscriptions = pending.count
        let token = lifetime
        transcriptionDeadlines[binding.id] = Task { [weak self, transcriptionTimeout] in
            try? await Task.sleep(for: transcriptionTimeout)
            guard !Task.isCancelled, let self, self.lifetime == token,
                  self.pending[binding.id] == binding.generation else { return }
            self.fail("语音转写等待超时，已停止采音，请重试或用文字继续。")
        }
        enqueue(["type": "commit_audio", "utterance_id": binding.id.uuidString.lowercased(), "generation": binding.generation])
        refreshStatus()
    }

    private func enqueue(_ event: [String: Any]) {
        guard let transport = socket, let data = try? JSONSerialization.data(withJSONObject: event) else { return }
        guard queuedBytes + data.count <= 256_000 else {
            fail("语音网络较慢，已停止采音，请重试或用文字继续。")
            return
        }
        queuedBytes += data.count
        let previous = sender, token = lifetime
        sender = Task { [weak self] in
            defer { if self?.lifetime == token { self?.queuedBytes -= data.count } }
            await previous?.value
            guard !Task.isCancelled, self?.lifetime == token else { return }
            do { try await transport.send(data) }
            catch { if self?.lifetime == token { self?.fail("语音发送失败，聊天保留，可以用文字继续。") } }
        }
    }

    private func receive(_ event: [String: Any]) {
        switch event["type"] as? String {
        case "ready": if connecting { ready = true }
        case "transcript":
            guard connected, let raw = event["utterance_id"] as? String, let id = UUID(uuidString: raw),
                  let generation = event["generation"] as? Int, pending[id] == generation,
                  let text = event["text"] as? String else { return }
            pending.removeValue(forKey: id); pendingTranscriptions = pending.count
            transcriptionDeadlines.removeValue(forKey: id)?.cancel()
            refreshStatus()
            let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !clean.isEmpty { onTranscript?(clean, id, generation) }
            else { status = "没有听清，请再说一次" }
        case "audio":
            guard connected, let rawID = event["speech_id"] as? String, UUID(uuidString: rawID) == speechID,
                  let raw = event["audio"] as? String, let data = Data(base64Encoded: raw),
                  !data.isEmpty, data.count % 2 == 0, data.count <= 3_000_000 else { return }
            guard pendingPlaybackBytes + data.count <= 3_000_000 else { fail("播报音频过长，请看聊天文字继续。"); return }
            let bufferID = UUID()
            receivedAudio = true; pendingBuffers.insert(bufferID); pendingPlaybackBytes += data.count
            let token = lifetime, playback = playbackToken
            do {
                try device?.schedule(data, played: { [weak self] in
                    guard let self, self.lifetime == token, self.playbackToken == playback,
                          self.pendingBuffers.remove(bufferID) != nil else { return }
                    self.pendingPlaybackBytes = max(0, self.pendingPlaybackBytes - data.count)
                    self.completePlaybackIfReady()
                })
                if lifetime == token && playbackToken == playback { playingSpeech = true }
            } catch { fail("音频播放失败，聊天文字已保留。") }
        case "speech_done":
            guard let raw = event["speech_id"] as? String, UUID(uuidString: raw) == speechID else { return }
            speechFinished = true
            guard receivedAudio else { fail("本次播报没有返回声音，请看聊天文字继续。"); return }
            completePlaybackIfReady()
        case "speech_blocked":
            guard let raw = event["speech_id"] as? String, UUID(uuidString: raw) == speechID else { return }
            fail("播报与聊天文字不一致，已停止语音，请看文字继续。")
        case "error": fail("实时语音暂不可用，聊天保留，可以用文字继续。")
        default: break
        }
    }

    private func completePlaybackIfReady() {
        guard speechFinished, pendingBuffers.isEmpty, receivedAudio, let completed = speechID else { return }
        resetPlayback(); outputLevel = 0; refreshStatus()
        onSpeechPlayed?(completed)
    }

    private func resetPlayback() {
        playbackToken = UUID(); speechID = nil; pendingBuffers.removeAll(); pendingPlaybackBytes = 0
        playingSpeech = false
        speechFinished = false; receivedAudio = false
        playbackDeadline?.cancel(); playbackDeadline = nil
    }

    private func refreshStatus() {
        guard connected else { return }
        if capturingSpeech { status = "正在听你说" }
        else if speechID != nil { status = muted ? "正在讲话 · 麦克风已静音" : "正在讲话 · 可以打断" }
        else if pendingTranscriptions > 0 { status = muted ? "正在转写 · 麦克风已静音" : "正在转写" }
        else { status = muted ? "麦克风已静音" : "正在聆听" }
    }

    private func fail(_ text: String) { stop(); error = text; status = text; onFailure?(text) }
    private static func displayLevel(_ rms: Double) -> Double { rms.isFinite ? min(1, max(0, rms * 8)) : 0 }
    private struct AudioFailure: Error { let message: String; init(_ message: String) { self.message = message } }
}

@MainActor private final class AgentVoiceURLSocket: AgentVoiceSocket {
    private let task: URLSessionWebSocketTask
    init(url: URL) { task = URLSession.shared.webSocketTask(with: url) }
    func resume() { task.resume() }
    func receive() async throws -> Data {
        switch try await task.receive() {
        case .data(let data): return data
        case .string(let text): return Data(text.utf8)
        @unknown default: throw URLError(.cannotParseResponse)
        }
    }
    func send(_ data: Data) async throws { try await task.send(.string(String(decoding: data, as: UTF8.self))) }
    func close() { task.cancel(with: .normalClosure, reason: nil) }
}

@MainActor private final class AgentVoiceEngine: AgentVoiceDevice {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var hasInputTap = false
    private var hasOutputTap = false
    private var attached = false
    private var converter: AgentVoicePCMConverter?
    private let inputGate = AgentVoiceCallbackGate()
    private let outputGate = AgentVoiceCallbackGate()

    func start(input: @escaping @MainActor (AgentVoiceSample) -> Void,
               outputLevel: @escaping @MainActor (Double) -> Void) throws {
        stop()
        try engine.inputNode.setVoiceProcessingEnabled(true)
        let inputFormat = engine.inputNode.outputFormat(forBus: 0)
        let converter = try AgentVoicePCMConverter(input: inputFormat)
        self.converter = converter
        guard let outputFormat = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1) else {
            throw URLError(.cannotDecodeContentData)
        }
        engine.attach(player); attached = true
        engine.connect(player, to: engine.mainMixerNode, format: outputFormat)
        inputGate.update(enabled: true); outputGate.update(enabled: true)
        let inputGate = inputGate, outputGate = outputGate
        engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { buffer, _ in
            guard let ticket = inputGate.ticket(), let sample = converter.convert(buffer) else { return }
            Task { @MainActor in if inputGate.accepts(ticket) { input(sample) } }
        }
        hasInputTap = true
        player.installTap(onBus: 0, bufferSize: 1024, format: outputFormat) { buffer, _ in
            guard let ticket = outputGate.ticket() else { return }
            let level = AgentVoicePCMConverter.level(buffer)
            Task { @MainActor in if outputGate.accepts(ticket) { outputLevel(level) } }
        }
        hasOutputTap = true
        try engine.start(); player.play()
    }

    func schedule(_ pcm: Data, played: @escaping @MainActor () -> Void) throws {
        guard engine.isRunning, pcm.count % 2 == 0,
              let format = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(pcm.count / 2)),
              let output = buffer.floatChannelData?[0] else { throw URLError(.cannotDecodeContentData) }
        buffer.frameLength = buffer.frameCapacity
        pcm.withUnsafeBytes { bytes in
            for index in 0..<Int(buffer.frameLength) {
                output[index] = Float(Int16(littleEndian: bytes.loadUnaligned(fromByteOffset: index * 2, as: Int16.self))) / 32_768
            }
        }
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { _ in
            Task { @MainActor in played() }
        }
    }

    func setInputEnabled(_ enabled: Bool) { inputGate.update(enabled: enabled) }

    func interrupt() {
        outputGate.update(enabled: true)
        player.stop(); if engine.isRunning { player.play() }
    }

    func stop() {
        inputGate.update(enabled: false); outputGate.update(enabled: false)
        if hasInputTap { engine.inputNode.removeTap(onBus: 0); hasInputTap = false }
        if hasOutputTap { player.removeTap(onBus: 0); hasOutputTap = false }
        player.stop(); engine.stop()
        if attached { engine.detach(player); attached = false }
        converter = nil
    }
}

/// Tap callbacks cross from the audio thread to MainActor. A mute/unmute or
/// playback interruption must invalidate already-queued samples as well.
nonisolated final class AgentVoiceCallbackGate: @unchecked Sendable {
    private let lock = NSLock()
    private var enabled = false
    private var revision = UUID()
    func update(enabled: Bool) {
        lock.lock(); defer { lock.unlock() }
        self.enabled = enabled; revision = UUID()
    }
    func ticket() -> UUID? {
        lock.lock(); defer { lock.unlock() }
        return enabled ? revision : nil
    }
    func accepts(_ ticket: UUID) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return enabled && revision == ticket
    }
}

private nonisolated final class AgentVoicePCMConverter: @unchecked Sendable {
    private let converter: AVAudioConverter
    private let output: AVAudioFormat
    init(input: AVAudioFormat) throws {
        guard input.sampleRate > 0, input.channelCount > 0,
              let output = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: input, to: output) else { throw URLError(.cannotDecodeContentData) }
        self.converter = converter; self.output = output
    }
    func convert(_ input: AVAudioPCMBuffer) -> AgentVoiceSample? {
        guard let result = AVAudioPCMBuffer(pcmFormat: output,
            frameCapacity: AVAudioFrameCount(Double(input.frameLength) * 16_000 / input.format.sampleRate + 32)) else { return nil }
        var used = false
        var error: NSError?
        converter.convert(to: result, error: &error) { _, status in
            if used { status.pointee = .noDataNow; return nil }
            used = true; status.pointee = .haveData; return input
        }
        guard error == nil, result.frameLength > 0, let samples = result.int16ChannelData?[0] else { return nil }
        let count = Int(result.frameLength)
        var squares = 0.0
        for index in 0..<count { let sample = Double(samples[index]) / 32_768; squares += sample * sample }
        return AgentVoiceSample(data: Data(bytes: samples, count: count * 2), level: sqrt(squares / Double(count)))
    }
    static func level(_ buffer: AVAudioPCMBuffer) -> Double {
        guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return 0 }
        var squares = 0.0
        for index in 0..<Int(buffer.frameLength) { let sample = Double(samples[index]); squares += sample * sample }
        return sqrt(squares / Double(buffer.frameLength))
    }
}
