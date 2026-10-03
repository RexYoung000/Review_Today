import Foundation

@MainActor private final class AudioSocketProbe: AgentVoiceSocket {
    var sends: [[String: Any]] = []
    var resumed = false
    var closed = false
    var automaticallyReady = true
    var failSend = false
    var holdSends = false
    private var events: [Data] = []
    private var receiving: CheckedContinuation<Data, Error>?
    private var sending: [CheckedContinuation<Void, Error>] = []

    func resume() { resumed = true; if automaticallyReady { push(["type": "ready"]) } }
    func receive() async throws -> Data {
        if !events.isEmpty { return events.removeFirst() }
        if closed { throw CancellationError() }
        return try await withCheckedThrowingContinuation { receiving = $0 }
    }
    func send(_ data: Data) async throws {
        if failSend || closed { throw URLError(.networkConnectionLost) }
        sends.append(try JSONSerialization.jsonObject(with: data) as! [String: Any])
        if holdSends { try await withCheckedThrowingContinuation { sending.append($0) } }
    }
    func close() {
        closed = true
        receiving?.resume(throwing: CancellationError()); receiving = nil
        sending.forEach { $0.resume(throwing: CancellationError()) }; sending.removeAll()
    }
    func push(_ event: [String: Any]) {
        let data = try! JSONSerialization.data(withJSONObject: event)
        if let receiver = receiving { receiving = nil; receiver.resume(returning: data) }
        else { events.append(data) }
    }
    var commits: [[String: Any]] { sends.filter { $0["type"] as? String == "commit_audio" } }
}

@MainActor private final class AudioDeviceProbe: AgentVoiceDevice {
    var starts = 0
    var stops = 0
    var interrupts = 0
    var failStart = false
    var failSchedule = false
    var inputEnabled = true
    var input: (@MainActor (AgentVoiceSample) -> Void)?
    var output: (@MainActor (Double) -> Void)?
    var completions: [@MainActor () -> Void] = []
    var pcm: [Data] = []
    func start(input: @escaping @MainActor (AgentVoiceSample) -> Void,
               outputLevel: @escaping @MainActor (Double) -> Void) throws {
        starts += 1
        self.input = input; output = outputLevel
        if failStart { throw URLError(.cannotDecodeContentData) }
    }
    func schedule(_ pcm: Data, played: @escaping @MainActor () -> Void) throws {
        if failSchedule { throw URLError(.cannotDecodeContentData) }
        self.pcm.append(pcm); completions.append(played)
    }
    func interrupt() { interrupts += 1 }
    func setInputEnabled(_ enabled: Bool) { inputEnabled = enabled }
    // Keep callbacks so tests can explicitly exercise callbacks queued before stop.
    func stop() { stops += 1 }
    func feed(_ seconds: Double, level: Double) {
        input?(AgentVoiceSample(data: Data(repeating: 0, count: Int(seconds * 16_000) * 2), level: level))
    }
    func beginSpeech() { for _ in 0..<3 { feed(0.06, level: 0.04) } }
}

@MainActor private final class PermissionProbe {
    var waiting: CheckedContinuation<Bool, Never>?
    func request() async -> Bool { await withCheckedContinuation { waiting = $0 } }
    func answer(_ allowed: Bool) { waiting?.resume(returning: allowed); waiting = nil }
}

@main struct AgentVoiceAudioContractTests {
    @MainActor private static func make(_ socket: AudioSocketProbe, _ device: AudioDeviceProbe,
                               transcriptionTimeout: Duration = .seconds(30),
                               playbackTimeout: Duration = .seconds(120),
                               connectionTimeout: Duration = .seconds(1)) -> AgentVoiceAudio {
        AgentVoiceAudio(permission: { true }, makeSocket: { _ in socket }, makeDevice: { device },
            serviceURL: { URL(string: "http://127.0.0.1:18742")! }, requireSending: {},
            connectionTimeout: connectionTimeout, transcriptionTimeout: transcriptionTimeout,
            playbackTimeout: playbackTimeout)
    }

    @MainActor static func settle() async { try? await Task.sleep(for: .milliseconds(12)) }
    @MainActor static func transcript(_ commit: [String: Any], text: String) -> [String: Any] {
        ["type": "transcript", "text": text, "utterance_id": commit["utterance_id"]!, "generation": commit["generation"]!]
    }
    @MainActor static func audioEvent(_ id: UUID) -> [String: Any] {
        ["type": "audio", "speech_id": id.uuidString, "audio": Data(repeating: 0, count: 480).base64EncodedString()]
    }

    @MainActor static func main() async throws {
        let gate = AgentVoiceCallbackGate()
        precondition(gate.ticket() == nil)
        gate.update(enabled: true)
        let ticket = gate.ticket()!
        precondition(gate.accepts(ticket))
        gate.update(enabled: false); gate.update(enabled: true)
        precondition(!gate.accepts(ticket), "queued pre-mute audio cannot return after unmute")
        var activity = AgentVoiceActivity(), bytes = 0, commits = 0
        for _ in 0..<1_301 {
            for action in activity.consume(AgentVoiceSample(data: Data(repeating: 0, count: 2_240), level: 0.04)) {
                switch action {
                case .began(let data), .append(let data): bytes += data.count
                case .commit:
                    precondition(bytes == 2_880_000, "a long utterance must not exceed the server's 90 second PCM bound by one frame")
                    bytes = 0; commits += 1
                }
            }
        }
        precondition(commits == 1 && activity.active && bytes > 0, "the tail after the exact cap continues as another utterance")
        try await permissionAndConnection()
        try await vadAndTranscriptBinding()
        try await playbackAndMute()
        try await bargeInAndReconnect()
        try await failuresAndBounds()
        print("PASS: injected production audio lifecycle; permission cancellation, owner binding, VAD/pause/noise, ASR ordering/deduplication, mute preservation, actual playback completion, barge-in, reconnect/late callbacks, timeouts and bounded queues; no hardware/network")
    }

    @MainActor static func permissionAndConnection() async throws {
        let permission = PermissionProbe()
        var socketsMade = 0, devicesMade = 0
        let cancelled = AgentVoiceAudio(permission: { await permission.request() },
            makeSocket: { _ in socketsMade += 1; return AudioSocketProbe() },
            makeDevice: { devicesMade += 1; return AudioDeviceProbe() }, requireSending: {})
        let waiting = Task { try await cancelled.start(ownerID: UUID()) }
        await settle()
        precondition(cancelled.connecting && permission.waiting != nil)
        cancelled.stop(); permission.answer(true)
        do { try await waiting.value; preconditionFailure("cancelled permission must not start audio") }
        catch is CancellationError {} catch { preconditionFailure("unexpected cancellation error") }
        precondition(!cancelled.connected && !cancelled.connecting && socketsMade == 0 && devicesMade == 0)

        let denied = AgentVoiceAudio(permission: { false }, makeSocket: { _ in
            preconditionFailure("denied permission must not create a socket")
        })
        var failures = 0
        denied.onFailure = { _ in failures += 1 }
        do { try await denied.start(ownerID: UUID()); preconditionFailure("permission must fail") } catch {}
        precondition(failures == 1 && denied.error?.contains("未授权") == true && !denied.connecting)

        let socket = AudioSocketProbe(), device = AudioDeviceProbe(), owner = UUID()
        var requestedURL: URL?
        let audio = AgentVoiceAudio(permission: { true }, makeSocket: { url in requestedURL = url; return socket },
            makeDevice: { device }, serviceURL: { URL(string: "https://localhost:18742/old")! }, requireSending: {})
        try await audio.start(ownerID: owner)
        precondition(audio.connected && !audio.connecting && device.starts == 1)
        precondition(requestedURL?.scheme == "wss" && requestedURL?.path == "/v2/agent/voice/\(owner.uuidString.lowercased())/audio")
        audio.stop()
        precondition(socket.closed && device.stops == 1 && audio.inputLevel == 0 && audio.outputLevel == 0)

        let unready = AudioSocketProbe(); unready.automaticallyReady = false
        let unused = AudioDeviceProbe(), timeout = make(unready, unused, connectionTimeout: .milliseconds(25))
        do { try await timeout.start(ownerID: UUID()); preconditionFailure("missing ready must time out") } catch {}
        precondition(timeout.error?.contains("连接超时") == true && unready.closed && unused.starts == 0)
    }

    @MainActor static func vadAndTranscriptBinding() async throws {
        let socket = AudioSocketProbe(), device = AudioDeviceProbe(), audio = make(socket, device)
        var began = 0, received: [(String, UUID, Int)] = []
        audio.onSpeechStart = { began += 1 }
        audio.onTranscript = { received.append(($0, $1, $2)) }
        try await audio.start(ownerID: UUID())
        defer { audio.stop() }
        device.feed(0.10, level: 0.06); device.feed(0.10, level: 0)
        await settle()
        precondition(began == 0 && socket.sends.isEmpty && !audio.capturingSpeech,
                     "a short noise cannot interrupt or upload an utterance")
        device.beginSpeech()
        precondition(began == 1 && audio.capturingSpeech && audio.inputLevel > 0)
        for _ in 0..<16 { device.feed(0.10, level: 0) }
        await settle()
        precondition(socket.commits.isEmpty && audio.capturingSpeech, "a 1.6 second pause still belongs to the utterance")
        device.feed(0.06, level: 0)
        await settle()
        precondition(socket.commits.count == 1 && audio.pendingTranscriptions == 1 && !audio.capturingSpeech)
        let first = socket.commits[0]
        device.beginSpeech(); audio.finishUtterance(); await settle()
        precondition(socket.commits.count == 2 && audio.pendingTranscriptions == 2)
        let second = socket.commits[1]
        precondition(first["utterance_id"] as? String != second["utterance_id"] as? String)
        precondition((first["generation"] as! Int) < (second["generation"] as! Int))
        var forged = transcript(first, text: "错误绑定")
        forged["generation"] = 999
        socket.push(forged); await settle()
        precondition(received.isEmpty && audio.pendingTranscriptions == 2)
        socket.push(transcript(second, text: "  第二段  "))
        socket.push(transcript(first, text: "第一段"))
        socket.push(transcript(first, text: "重复第一段"))
        await settle()
        precondition(received.map(\.0) == ["第二段", "第一段"] && audio.pendingTranscriptions == 0,
                     "bound out-of-order transcripts reach the coordinator once with their original generations")
        precondition(socket.sends.filter { $0["type"] as? String == "audio" }.allSatisfy {
            let data = Data(base64Encoded: $0["audio"] as! String)!
            return !data.isEmpty && data.count <= 64_000 && data.count % 2 == 0
        })
    }

    @MainActor static func playbackAndMute() async throws {
        let socket = AudioSocketProbe(), device = AudioDeviceProbe(), audio = make(socket, device)
        var played: [UUID] = [], received: [String] = []
        audio.onSpeechPlayed = { played.append($0) }
        audio.onTranscript = { text, _, _ in received.append(text) }
        try await audio.start(ownerID: UUID())
        defer { audio.stop() }
        device.beginSpeech(); audio.finishUtterance(); await settle()
        let commit = socket.commits[0], id = UUID()
        audio.speak(text: "这是完整的一句。", id: id)
        precondition(!audio.playingSpeech, "queued text alone is not playing audio")
        socket.push(audioEvent(id)); socket.push(audioEvent(id)); await settle()
        device.output?(0.04)
        precondition(audio.playingSpeech && audio.outputLevel > 0 && device.pcm.count == 2)
        let interruptionCount = device.interrupts
        audio.toggleMute(); device.beginSpeech(); await settle()
        precondition(audio.muted && !device.inputEnabled && audio.inputLevel == 0 && !audio.capturingSpeech && audio.pendingTranscriptions == 1)
        precondition(device.interrupts == interruptionCount && device.stops == 0 && audio.outputLevel > 0,
                     "muting input must not stop agent output or lose committed ASR")
        let clear = socket.sends.last { $0["type"] as? String == "clear" }!
        precondition(clear["cancel_transcripts"] as? Bool == false)
        socket.push(transcript(commit, text: "提交的内容")); await settle()
        precondition(received == ["提交的内容"] && audio.pendingTranscriptions == 0)
        socket.push(["type": "speech_done", "speech_id": id.uuidString]); await settle()
        precondition(played.isEmpty, "server done is not a playback completion")
        device.completions[0](); precondition(played.isEmpty)
        device.completions[0](); precondition(played.isEmpty, "a repeated completion cannot stand in for another buffer")
        device.completions[1](); precondition(played == [id] && audio.outputLevel == 0 && !audio.playingSpeech)
        device.completions[1](); socket.push(["type": "speech_done", "speech_id": id.uuidString]); await settle()
        precondition(played == [id], "duplicate playback callbacks cannot advance the sentence queue twice")
        audio.toggleMute()
        precondition(!audio.muted && audio.connected)
    }

    @MainActor static func bargeInAndReconnect() async throws {
        let firstSocket = AudioSocketProbe(), secondSocket = AudioSocketProbe()
        let firstDevice = AudioDeviceProbe(), secondDevice = AudioDeviceProbe()
        var connections = 0, devices = 0, played: [UUID] = [], speechStarts = 0
        let audio = AgentVoiceAudio(permission: { true }, makeSocket: { _ in
            connections += 1; return connections == 1 ? firstSocket : secondSocket
        }, makeDevice: { devices += 1; return devices == 1 ? firstDevice : secondDevice }, requireSending: {})
        audio.onSpeechPlayed = { played.append($0) }; audio.onSpeechStart = { speechStarts += 1 }
        try await audio.start(ownerID: UUID())
        let id = UUID()
        audio.speak(text: "可以打断的句子。", id: id)
        firstSocket.push(audioEvent(id)); firstSocket.push(["type": "speech_done", "speech_id": id.uuidString]); await settle()
        firstDevice.beginSpeech(); await settle()
        precondition(audio.capturingSpeech && speechStarts == 1 && audio.outputLevel == 0)
        firstDevice.completions[0](); await settle()
        precondition(played.isEmpty, "interrupted buffers cannot claim a fully played sentence")
        precondition(firstSocket.sends.last { $0["type"] as? String == "interrupt" } != nil)

        try await audio.start(ownerID: UUID())
        precondition(firstSocket.closed && firstDevice.stops == 1 && secondDevice.starts == 1)
        firstDevice.beginSpeech(); firstDevice.output?(1); firstDevice.completions[0](); await settle()
        precondition(speechStarts == 1 && played.isEmpty && audio.inputLevel == 0 && audio.outputLevel == 0,
                     "callbacks captured by the previous audio lifetime cannot affect the new owner")
        secondDevice.beginSpeech(); precondition(speechStarts == 2 && audio.capturingSpeech)
        audio.stop()
        secondDevice.beginSpeech(); precondition(speechStarts == 2 && !audio.connected && !audio.capturingSpeech)
    }

    @MainActor static func failuresAndBounds() async throws {
        let timeoutSocket = AudioSocketProbe(), timeoutDevice = AudioDeviceProbe()
        let timeout = make(timeoutSocket, timeoutDevice, transcriptionTimeout: .milliseconds(30))
        var failures = 0
        timeout.onFailure = { _ in failures += 1 }
        try await timeout.start(ownerID: UUID())
        timeoutDevice.beginSpeech(); timeout.finishUtterance()
        try await Task.sleep(for: .milliseconds(70))
        precondition(failures == 1 && !timeout.connected && timeout.pendingTranscriptions == 0)
        precondition(timeout.error?.contains("转写等待超时") == true && timeoutSocket.closed && timeoutDevice.stops == 1)

        let missingSocket = AudioSocketProbe(), missingDevice = AudioDeviceProbe(), missing = make(missingSocket, missingDevice)
        try await missing.start(ownerID: UUID())
        let id = UUID(); missing.speak(text: "有字但没有声音。", id: id)
        var played = false; missing.onSpeechPlayed = { _ in played = true }
        missingSocket.push(["type": "speech_done", "speech_id": id.uuidString]); await settle()
        precondition(!played && !missing.connected && missing.error?.contains("没有返回声音") == true)

        let blockedSocket = AudioSocketProbe(), blockedDevice = AudioDeviceProbe(), blocked = make(blockedSocket, blockedDevice)
        try await blocked.start(ownerID: UUID())
        let blockedID = UUID(); blocked.speak(text: "应当逐字核对。", id: blockedID)
        blockedSocket.push(["type": "speech_blocked", "speech_id": UUID().uuidString]); await settle()
        precondition(blocked.connected, "a stale speech rejection cannot stop the current sentence")
        blockedSocket.push(["type": "speech_blocked", "speech_id": blockedID.uuidString]); await settle()
        precondition(!blocked.connected && blocked.error?.contains("不一致") == true)

        let saturatedSocket = AudioSocketProbe(), saturatedDevice = AudioDeviceProbe(), saturated = make(saturatedSocket, saturatedDevice)
        try await saturated.start(ownerID: UUID())
        saturatedSocket.holdSends = true
        saturatedDevice.beginSpeech()
        for _ in 0..<120 { saturatedDevice.feed(0.10, level: 0.04) }
        await settle()
        precondition(!saturated.connected && saturatedSocket.closed && saturated.error?.contains("网络较慢") == true,
                     "a stalled sender must fail closed instead of accumulating unbounded PCM")

        let brokenSocket = AudioSocketProbe(), brokenDevice = AudioDeviceProbe(); brokenDevice.failStart = true
        let broken = make(brokenSocket, brokenDevice)
        do { try await broken.start(ownerID: UUID()); preconditionFailure("device failure must be reported") } catch {}
        precondition(!broken.connected && brokenSocket.closed && brokenDevice.stops == 1 && broken.error != nil)

        let playbackSocket = AudioSocketProbe(), playbackDevice = AudioDeviceProbe()
        let playback = make(playbackSocket, playbackDevice, playbackTimeout: .milliseconds(30))
        try await playback.start(ownerID: UUID())
        playback.speak(text: "一直没有播完。", id: UUID())
        try await Task.sleep(for: .milliseconds(70))
        precondition(!playback.connected && playback.error?.contains("播报等待超时") == true)
    }
}
