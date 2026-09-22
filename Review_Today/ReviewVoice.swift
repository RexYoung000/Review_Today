import AVFoundation
import Foundation
import Observation

@MainActor @Observable
final class ReviewVoice {
    var status = "语音未连接"
    var connected = false
    var muted = false
    var onTranscript: ((String, UUID, Int) -> Void)?
    var onSpeechStart: (() -> Void)?
    var onFailure: ((String) -> Void)?
    private var socket: URLSessionWebSocketTask?
    private var reader: Task<Void, Never>?
    private var sender: Task<Void, Never>?
    private var engine: AVAudioEngine?
    private let player = AVAudioPlayerNode()
    private var converter: ReviewPCMConverter?
    private var frame: (UUID, Int)?
    private var capturedFrame: (UUID, Int)?
    private var speechID: UUID?
    private var speaking = false
    private var silence = 0.0
    private var speechDuration = 0.0
    private var preRoll = Data()
    private var lifetime = UUID()
    private var queuedBytes = 0
    private var ending = false
    private var speechFinished = false
    private var pendingBuffers = 0
    private var endingDeadline: Task<Void, Never>?
    private var capturing = false

    func bind(_ attemptID: UUID, generation: Int) { frame = (attemptID, generation) }

    func start(sessionID: UUID) async throws {
        stop()
        guard await AVCaptureDevice.requestAccess(for: .audio) else {
            status = "麦克风未授权，可用文字回答"
            throw ReviewFlowError.invalidResult
        }
        try Task.checkCancellation()
        try AppRuntime.current.requireSending()
        let token = UUID(); lifetime = token
        status = "正在连接语音"
        var parts = URLComponents(url: AppRuntime.current.serviceURL, resolvingAgainstBaseURL: false)!
        parts.scheme = "ws"; parts.path = "/v2/review/sessions/\(sessionID.uuidString.lowercased())/audio"
        let task = URLSession.shared.webSocketTask(with: parts.url!)
        socket = task; task.resume()
        reader = Task { [weak self] in
            do {
                while !Task.isCancelled {
                    let message = try await task.receive()
                    guard let self, self.lifetime == token else { return }
                    let data: Data
                    switch message { case .data(let value): data = value; case .string(let value): data = Data(value.utf8); @unknown default: continue }
                    guard let event = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                    self.receive(event)
                }
            } catch {
                guard let self, self.lifetime == token else { return }
                self.fail("语音连接已断开，进度保留，可用文字继续。")
            }
        }
        for _ in 0..<100 {
            if connected { break }
            guard lifetime == token, !Task.isCancelled else { throw CancellationError() }
            try await Task.sleep(for: .milliseconds(100))
        }
        guard connected else { stop(); throw ReviewFlowError.invalidResult }
        let engine = AVAudioEngine()
        try engine.inputNode.setVoiceProcessingEnabled(true)
        let input = engine.inputNode.inputFormat(forBus: 0)
        let converter = try ReviewPCMConverter(input: input)
        self.converter = converter
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1))
        engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: input) { [weak self, converter] buffer, _ in
            guard let sample = converter.convert(buffer) else { return }
            Task { @MainActor [weak self] in
                guard let self, self.lifetime == token else { return }
                self.capture(sample.data, level: sample.level, duration: sample.duration)
            }
        }
        capturing = true
        self.engine = engine
        try engine.start(); player.play()
        status = "正在聆听"
    }

    func say(_ text: String) {
        guard connected else { return }
        player.stop(); player.play()
        pendingBuffers = 0; speechFinished = false
        let id = UUID(); speechID = id
        status = "正在播报 · 可以打断"
        enqueue(["type": "speak", "text": String(text.prefix(5000)), "speech_id": id.uuidString.lowercased()])
    }
    func finish(with text: String) {
        guard connected else { stop(); return }
        ending = true; frame = nil; capturedFrame = nil; speaking = false; preRoll.removeAll()
        if capturing { engine?.inputNode.removeTap(onBus: 0); capturing = false }
        enqueue(["type": "clear"])
        say(text)
        let token = lifetime
        endingDeadline = Task { [weak self] in
            try? await Task.sleep(for: .seconds(20))
            guard !Task.isCancelled, self?.lifetime == token else { return }
            self?.stop()
        }
    }
    func interrupt() {
        speechID = nil; player.stop()
        if engine?.isRunning == true { player.play() }
        if connected { enqueue(["type": "interrupt"]); status = muted ? "已静音" : "正在聆听" }
    }
    func toggleMute() {
        muted.toggle(); speaking = false; preRoll.removeAll(); capturedFrame = nil
        enqueue(["type": "clear"])
        status = muted ? "已静音" : "正在聆听"
    }
    func finishUtterance() {
        guard speaking, let binding = capturedFrame else { return }
        enqueue(["type": "commit_audio", "attempt_id": binding.0.uuidString.lowercased(), "generation": binding.1])
        speaking = false; silence = 0; speechDuration = 0; capturedFrame = nil
        status = "正在转写"
    }
    func stop() {
        lifetime = UUID()
        endingDeadline?.cancel(); endingDeadline = nil
        reader?.cancel(); sender?.cancel(); reader = nil; sender = nil
        socket?.cancel(with: .normalClosure, reason: nil); socket = nil
        if capturing { engine?.inputNode.removeTap(onBus: 0); capturing = false }
        engine?.stop(); player.stop(); engine?.detach(player); engine = nil
        converter = nil; connected = false; speaking = false; ending = false; pendingBuffers = 0; speechFinished = false
        speechID = nil; frame = nil; capturedFrame = nil; preRoll.removeAll(); silence = 0; speechDuration = 0; queuedBytes = 0
        status = "语音未连接"
    }
    private func capture(_ data: Data, level: Double, duration: Double) {
        guard connected, !muted, !ending, frame != nil else { return }
        if !speaking {
            preRoll.append(data)
            if preRoll.count > 8000 { preRoll.removeFirst(preRoll.count - 8000) }
            guard level > 0.012 else { return }
            interrupt(); onSpeechStart?(); capturedFrame = frame
            speaking = true; silence = 0; speechDuration = 0
            enqueue(["type": "audio", "audio": preRoll.base64EncodedString()]); preRoll.removeAll()
        } else { enqueue(["type": "audio", "audio": data.base64EncodedString()]) }
        speechDuration += duration
        silence = level > 0.009 ? 0 : silence + duration
        // A thought can continue across transcribed utterances; the dialogue node
        // distinguishes waiting/clarification from a completed factual answer.
        if silence >= 1.2 && speechDuration >= 0.25 { finishUtterance() }
        else if speechDuration >= 90 { finishUtterance() }
    }
    private func enqueue(_ event: [String: Any]) {
        guard let socket, let data = try? JSONSerialization.data(withJSONObject: event) else { return }
        guard queuedBytes + data.count <= 256_000 else { fail("语音网络较慢，已停止采音；可用文字继续或重新连接。"); return }
        queuedBytes += data.count
        let previous = sender, token = lifetime
        sender = Task { [weak self] in
            defer { if self?.lifetime == token { self?.queuedBytes -= data.count } }
            await previous?.value
            guard !Task.isCancelled, self?.lifetime == token else { return }
            do { try await socket.send(.string(String(decoding: data, as: UTF8.self))) }
            catch { if self?.lifetime == token { self?.fail("语音发送未完成，可用文字继续。") } }
        }
    }
    private func receive(_ event: [String: Any]) {
        switch event["type"] as? String {
        case "ready": connected = true
        case "transcript":
            guard let text = event["text"] as? String, let raw = event["attempt_id"] as? String,
                  let id = UUID(uuidString: raw), let generation = event["generation"] as? Int else { return }
            onTranscript?(text, id, generation)
        case "audio":
            guard let rawID = event["speech_id"] as? String, UUID(uuidString: rawID) == speechID,
                  let raw = event["audio"] as? String, let data = Data(base64Encoded: raw), data.count % 2 == 0,
                  let format = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1),
                  let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(data.count/2)),
                  let output = buffer.floatChannelData?[0] else { return }
            buffer.frameLength = buffer.frameCapacity
            data.withUnsafeBytes { bytes in
                for i in 0..<Int(buffer.frameLength) { output[i] = Float(Int16(littleEndian: bytes.loadUnaligned(fromByteOffset: i*2, as: Int16.self))) / 32768 }
            }
            pendingBuffers += 1
            let token = lifetime, playback = speechID
            player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self, self.lifetime == token, self.speechID == playback else { return }
                    self.pendingBuffers = max(0, self.pendingBuffers - 1)
                    if self.speechFinished && self.pendingBuffers == 0 {
                        if self.ending { self.stop() }
                        else if !self.speaking { self.status = self.muted ? "已静音" : "正在聆听" }
                    }
                }
            }
        case "speech_done":
            guard let raw = event["speech_id"] as? String, UUID(uuidString: raw) == speechID else { return }
            speechFinished = true
            if ending && pendingBuffers == 0 { stop() }
            else if !speaking && pendingBuffers == 0 { status = muted ? "已静音" : "正在聆听" }
        case "speech_blocked":
            if ending { stop() } else { interrupt() }
            onFailure?("本次播报与题目文字不一致，已停止播放。请看文字继续回答。")
        case "error": fail("实时语音暂不可用，已保留进度。你可以用文字继续或重新连接。")
        default: break
        }
    }
    private func fail(_ text: String) { stop(); status = text; onFailure?(text) }
}

/// Conversion stays on the audio callback, without touching main-actor app state.
private nonisolated final class ReviewPCMConverter: @unchecked Sendable {
    let converter: AVAudioConverter
    let output: AVAudioFormat
    init(input: AVAudioFormat) throws {
        guard let output = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: input, to: output) else { throw NSError(domain: "ReviewAudio", code: 1) }
        self.converter = converter; self.output = output
    }
    func convert(_ input: AVAudioPCMBuffer) -> (data: Data, level: Double, duration: Double)? {
        guard let result = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: AVAudioFrameCount(Double(input.frameLength) * 16000 / input.format.sampleRate + 32)) else { return nil }
        var used = false
        var error: NSError?
        converter.convert(to: result, error: &error) { _, status in
            if used { status.pointee = .noDataNow; return nil }
            used = true; status.pointee = .haveData; return input
        }
        guard error == nil, result.frameLength > 0, let pointer = result.int16ChannelData?[0] else { return nil }
        let count = Int(result.frameLength)
        var squares = 0.0
        for i in 0..<count { let value = Double(pointer[i]) / 32768; squares += value * value }
        return (Data(bytes: pointer, count: count*2), sqrt(squares/Double(count)), Double(count)/16000)
    }
}
