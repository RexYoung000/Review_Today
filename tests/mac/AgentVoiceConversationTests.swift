import Foundation

@MainActor private final class ConversationSocketProbe: AgentVoiceSocket {
    var sends: [[String: Any]] = []
    var closed = false
    private var events: [Data] = []
    private var waiting: CheckedContinuation<Data, Error>?
    func resume() { push(["type": "ready"]) }
    func receive() async throws -> Data {
        if !events.isEmpty { return events.removeFirst() }
        if closed { throw CancellationError() }
        return try await withCheckedThrowingContinuation { waiting = $0 }
    }
    func send(_ data: Data) async throws {
        guard !closed else { throw CancellationError() }
        sends.append(try JSONSerialization.jsonObject(with: data) as! [String: Any])
    }
    func close() { closed = true; waiting?.resume(throwing: CancellationError()); waiting = nil }
    func push(_ value: [String: Any]) {
        let data = try! JSONSerialization.data(withJSONObject: value)
        if let waiting { self.waiting = nil; waiting.resume(returning: data) }
        else { events.append(data) }
    }
    var commits: [[String: Any]] { sends.filter { $0["type"] as? String == "commit_audio" } }
    var speeches: [[String: Any]] { sends.filter { $0["type"] as? String == "speak" } }
}

@MainActor private final class ConversationDeviceProbe: AgentVoiceDevice {
    var input: (@MainActor (AgentVoiceSample) -> Void)?
    var completions: [@MainActor () -> Void] = []
    var starts = 0
    var stops = 0
    var interrupts = 0
    func start(input: @escaping @MainActor (AgentVoiceSample) -> Void,
               outputLevel: @escaping @MainActor (Double) -> Void) throws { starts += 1; self.input = input }
    func schedule(_ pcm: Data, played: @escaping @MainActor () -> Void) throws { completions.append(played) }
    func setInputEnabled(_ enabled: Bool) {}
    func interrupt() { interrupts += 1 }
    func stop() { stops += 1 }
    func beginSpeech() {
        for _ in 0..<4 { input?(.init(data: Data(repeating: 0, count: 1_920), level: 0.04)) }
    }
}

@MainActor private final class ConversationHarness {
    let owner = UUID()
    let socket: ConversationSocketProbe
    let device: ConversationDeviceProbe
    let audio: AgentVoiceAudio
    let voice: AgentVoiceConversation
    var snapshot = AgentVoiceConversation.Snapshot()
    var submitted: [String] = []
    var submittedIDs: [UUID] = []
    var createdSession: UUID?
    var submitSucceeds = true
    var stopSucceeds = true
    var persistSucceeds = true
    var stopCalls = 0
    var persisted: [UUID: AgentVoicePlayback] = [:]
    var persistenceAttempts: [(UUID, AgentVoicePlayback)] = []
    var lastRun: UUID { snapshot.messages.last(where: { $0.role == "user" })!.runID! }

    init() {
        let socket = ConversationSocketProbe(), device = ConversationDeviceProbe()
        self.socket = socket; self.device = device
        audio = AgentVoiceAudio(permission: { true }, makeSocket: { _ in socket }, makeDevice: { device },
            serviceURL: { URL(string: "http://127.0.0.1:18742")! }, requireSending: {},
            connectionTimeout: .seconds(1), transcriptionTimeout: .seconds(5), playbackTimeout: .seconds(5))
        voice = AgentVoiceConversation(audio: audio)
    }
    func start() async {
        voice.start(ownerID: owner, read: { self.snapshot }, submit: { text in self.submit(text) },
            stopReply: { self.stopCalls += 1; return self.stopSucceeds },
            persist: { id, record in
                self.persistenceAttempts.append((id, record))
                if self.persistSucceeds { self.persisted[id] = record }
                return self.persistSucceeds
            }, automaticallyRefresh: false)
        await wait { self.audio.connected }
    }
    func submit(_ text: String) -> UUID? {
        guard submitSucceeds else { return nil }
        createdSession = owner
        let id = UUID(), run = UUID()
        submitted.append(text); submittedIDs.append(id)
        snapshot.messages.append(.init(id: id, runID: run, role: "user", content: text))
        snapshot.runningIDs.insert(run)
        return id
    }
    func commit() async -> [String: Any] {
        let count = socket.commits.count
        device.beginSpeech(); audio.finishUtterance()
        await wait { self.socket.commits.count == count + 1 }
        return socket.commits.last!
    }
    func transcript(_ commit: [String: Any], _ text: String, generation: Int? = nil) {
        socket.push(["type": "transcript", "text": text, "utterance_id": commit["utterance_id"]!, "generation": generation ?? (commit["generation"] as! Int)])
    }
    @discardableResult func response(_ text: String, state: String = "complete", revision: Int = 0) -> UUID {
        let id = UUID(), run = lastRun
        snapshot.messages.append(.init(id: id, runID: run, role: "assistant", content: text, state: state, revision: revision))
        if state == "complete" { snapshot.runningIDs.remove(run) }
        voice.refresh()
        return id
    }
    func receiveAudio(for speech: [String: Any]) async -> Int {
        let count = device.completions.count
        socket.push(["type": "audio", "speech_id": speech["speech_id"]!, "audio": Data(repeating: 0, count: 480).base64EncodedString()])
        await wait { self.device.completions.count == count + 1 }
        return count
    }
    func serverDone(_ speech: [String: Any]) { socket.push(["type": "speech_done", "speech_id": speech["speech_id"]!]) }
    func play(_ index: Int) async {
        await wait { self.socket.speeches.count > index }
        let speech = socket.speeches[index]
        let completion = await receiveAudio(for: speech)
        serverDone(speech); await settle()
        device.completions[completion](); await settle()
        voice.refresh()
    }
    func close() { voice.end() }
    func wait(_ predicate: () -> Bool) async {
        for _ in 0..<100 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(5))
        }
        preconditionFailure("Timed out waiting for injected conversation state")
    }
    func settle() async { try? await Task.sleep(for: .milliseconds(15)) }
}

@main struct AgentVoiceConversationTests {
    @MainActor static func main() async {
        await threeRoundsAndOwnerPromotion()
        await resumedRunVoiceCausality()
        await actualPlaybackAndEnd()
        await bargeInAndRevisions()
        await failureAndUnsentRecovery()
        await inactiveSnapshotAndPersistenceFailure()
        print("PASS: same-owner first promotion, three turns, resumed-run voice causality, out-of-order/duplicate ASR, playback receipts, barge-in/revision fences, end without cancelling submitted work, unsent retry, lifecycle and persistence failures; fake permission/socket/device only")
    }

    @MainActor static func threeRoundsAndOwnerPromotion() async {
        let h = ConversationHarness()
        let historical = UUID()
        h.snapshot.messages = [.init(id: historical, runID: UUID(), role: "assistant", content: "已有历史，不应播报。")]
        await h.start(); defer { h.close() }
        precondition(h.voice.ownerID == h.owner && h.createdSession == nil && h.submitted.isEmpty && h.socket.speeches.isEmpty,
                     "Entering voice must not create an empty session or replay history")
        let first = await h.commit(); h.transcript(first, "第一轮问题")
        await h.wait { h.submitted.count == 1 }
        precondition(h.createdSession == h.owner && h.voice.ownerID == h.owner)
        let reply1 = h.response("第一轮回答。还有一点。")
        await h.play(0); await h.play(1)
        precondition(h.persisted[reply1]?.played == ["第一轮回答。", "还有一点。"] && h.persisted[reply1]?.state == "played")

        let secondA = await h.commit(), secondB = await h.commit()
        h.transcript(secondB, "第二轮补充"); await h.settle()
        precondition(h.submitted.count == 1, "Out-of-order ASR must wait for earlier pending generations")
        h.transcript(secondA, "第二轮先说"); h.transcript(secondB, "重复的补充")
        await h.wait { h.submitted.count == 2 }
        precondition(h.submitted[1] == "第二轮先说\n第二轮补充", "ASR fragments are submitted once in captured order")
        let reply2 = h.response("第二轮回答。")
        await h.play(2)
        precondition(h.persisted[reply2]?.played == ["第二轮回答。"])

        let third = await h.commit()
        h.transcript(third, "伪造绑定", generation: 999); await h.settle()
        precondition(h.submitted.count == 2 && h.audio.pendingTranscriptions == 1)
        h.transcript(third, "第三轮问题"); h.transcript(first, "旧轮迟到重复")
        await h.wait { h.submitted.count == 3 }
        let reply3 = h.response("第三轮回答。")
        await h.play(3)
        precondition(h.submitted == ["第一轮问题", "第二轮先说\n第二轮补充", "第三轮问题"])
        precondition(h.snapshot.messages.filter { $0.role == "user" }.count == 3 && h.persisted[reply3]?.state == "played")
        h.snapshot.messages[0].revision = 1
        h.snapshot.messages[0].content = "历史修订也不应播报。"
        h.voice.refresh(); await h.settle()
        precondition(h.socket.speeches.count == 4, "A historical revision must not enter the current voice response set")
    }

    @MainActor static func resumedRunVoiceCausality() async {
        let h = ConversationHarness()
        let resumedRun = UUID(), unrelatedRun = UUID(), oldHistory = UUID()
        h.snapshot.messages = [.init(id: oldHistory, runID: resumedRun, role: "assistant", content: "暂停前已经显示的历史。")]
        await h.start(); defer { h.close() }
        let first = await h.commit(); h.transcript(first, "继续刚才的任务")
        await h.wait { h.submitted.count == 1 }
        let commandRun = h.lastRun, currentInput = h.submittedIDs[0]
        precondition(commandRun != resumedRun)
        h.snapshot.runningIDs = [resumedRun]
        h.snapshot.voiceOrigins[resumedRun] = [currentInput]
        h.snapshot.voiceOrigins[unrelatedRun] = [UUID()]
        h.snapshot.messages.append(.init(id: UUID(), runID: unrelatedRun, role: "assistant", content: "另一个来源的答复不能播。"))
        h.snapshot.messages.append(.init(id: UUID(), runID: UUID(), role: "assistant", content: "没有语音因果的答复不能播。"))
        h.voice.refresh(); await h.settle()
        precondition(h.voice.waitingForAgent && h.socket.speeches.isEmpty,
                     "Only current-input causality may attach a resumed run; unrelated runs and existing history remain silent")

        let resumedReply = UUID()
        h.snapshot.messages.append(.init(id: resumedReply, runID: resumedRun, role: "assistant", content: "这是本次语音恢复的任务答复。"))
        h.snapshot.runningIDs.remove(resumedRun)
        h.voice.refresh(); await h.play(0)
        precondition(h.persisted[resumedReply]?.played == ["这是本次语音恢复的任务答复。"] && h.persisted[oldHistory] == nil,
                     "A response from the explicitly voice-originated resumed run is spoken once, without replaying its history")

        let second = await h.commit(); h.transcript(second, "换一个新的问题")
        await h.wait { h.submitted.count == 2 }
        let lateOldReply = UUID()
        h.snapshot.messages.append(.init(id: lateOldReply, runID: resumedRun, role: "assistant", content: "打断后迟到的旧任务回答。"))
        h.snapshot.messages[0].revision += 1
        h.snapshot.messages[0].content = "旧历史的新修订也不能恢复播报。"
        h.voice.refresh(); await h.settle()
        precondition(h.socket.speeches.count == 1 && h.persisted[lateOldReply] == nil,
                     "After barge-in clears inputs, a stale voice-origin mapping cannot revive an old run")
        let directReply = h.response("新问题的直接回答。")
        await h.play(1)
        precondition(h.persisted[directReply]?.played == ["新问题的直接回答。"] && h.socket.speeches.count == 2)
    }

    @MainActor static func actualPlaybackAndEnd() async {
        let h = ConversationHarness(); await h.start(); defer { h.close() }
        let commit = await h.commit(); h.transcript(commit, "请解释")
        await h.wait { h.submitted.count == 1 }
        let reply = h.response("第一句。第二句。")
        await h.wait { h.socket.speeches.count == 1 }
        precondition(h.persisted[reply]?.played.isEmpty == true, "Queueing text is not hearing it")
        let speech = h.socket.speeches[0], callback = await h.receiveAudio(for: h.socket.speeches[0])
        h.serverDone(speech); await h.settle()
        precondition(h.persisted[reply]?.played.isEmpty == true && h.socket.speeches.count == 1,
                     "Server speech_done cannot mark a hardware buffer played")
        h.device.completions[callback](); await h.wait { h.socket.speeches.count == 2 }
        precondition(h.persisted[reply]?.played == ["第一句。"])
        let stopCount = h.stopCalls, graphCount = h.snapshot.messages.count
        h.voice.end()
        precondition(h.stopCalls == stopCount && h.snapshot.messages.count == graphCount,
                     "Ending voice must not cancel/delete accepted Agent work")
        precondition(h.persisted[reply]?.state == "interrupted" && h.persisted[reply]?.interrupted == "第二句。" && h.persisted[reply]?.played == ["第一句。"])
        h.device.completions[callback](); h.transcript(commit, "结束后的迟到内容"); await h.settle()
        precondition(h.submitted.count == 1 && h.persisted[reply]?.played == ["第一句。"])
        precondition(!h.voice.active && !h.audio.connected && h.socket.closed)
    }

    @MainActor static func bargeInAndRevisions() async {
        let existing = ConversationHarness()
        existing.snapshot.runningIDs.insert(UUID())
        await existing.start()
        existing.device.beginSpeech(); await existing.settle()
        precondition(existing.stopCalls == 1 && existing.submitted.isEmpty,
                     "First speech also interrupts an already-running text reply before any voice submission")
        existing.close()

        let h = ConversationHarness(); await h.start(); defer { h.close() }
        let first = await h.commit(); h.transcript(first, "旧问题")
        await h.wait { h.submitted.count == 1 }
        let oldReply = h.response("旧回复第一句。\n旧回复第二句。", state: "streaming")
        await h.wait { h.socket.speeches.count == 1 }
        let oldCallback = await h.receiveAudio(for: h.socket.speeches[0])
        h.device.beginSpeech(); await h.settle()
        precondition(h.stopCalls == 1 && h.voice.phase == .listening && h.persisted[oldReply]?.state == "interrupted")
        h.audio.finishUtterance(); await h.wait { h.socket.commits.count == 2 }
        h.transcript(h.socket.commits[1], "新的追问")
        await h.wait { h.submitted.count == 2 }
        let index = h.snapshot.messages.firstIndex { $0.id == oldReply }!
        h.snapshot.messages[index].revision += 1
        h.snapshot.messages[index].content = "旧任务迟到的新修订。"
        h.voice.refresh(); h.device.completions[oldCallback](); await h.settle()
        precondition(h.socket.speeches.count == 1 && h.persisted[oldReply]?.played.isEmpty == true,
                     "Barge-in must fence late audio and new revisions from the abandoned run")
        let newReply = h.response("新的追问回答。")
        await h.play(1)
        precondition(h.persisted[newReply]?.state == "played")

        for incrementRevision in [false, true] {
            let corrected = ConversationHarness(); await corrected.start()
            let commit = await corrected.commit(); corrected.transcript(commit, "容易修正的问题")
            await corrected.wait { corrected.submitted.count == 1 }
            let id = corrected.response("原来的措辞。\n", state: "streaming")
            await corrected.wait { corrected.socket.speeches.count == 1 }
            let callback = await corrected.receiveAudio(for: corrected.socket.speeches[0])
            let position = corrected.snapshot.messages.firstIndex { $0.id == id }!
            corrected.snapshot.messages[position].content = "修正后的措辞。"
            corrected.snapshot.messages[position].state = "complete"
            if incrementRevision { corrected.snapshot.messages[position].revision += 1 }
            corrected.voice.refresh(); corrected.device.completions[callback](); await corrected.settle()
            precondition(corrected.socket.speeches.count == 1 && corrected.persisted[id]?.state == "interrupted" && corrected.persisted[id]?.played.isEmpty == true,
                         "Both source replacement and a new revision must stop old playback without pretending nothing had been heard")
            corrected.close()
        }
    }

    @MainActor static func failureAndUnsentRecovery() async {
        let h = ConversationHarness(); h.submitSucceeds = false; await h.start()
        let commit = await h.commit(); h.transcript(commit, "尚未保存的发言")
        await h.wait { h.voice.unsentText != nil }
        precondition(h.voice.unsentText == "尚未保存的发言" && h.voice.unsentOwnerID == h.owner && h.submitted.isEmpty && !h.audio.connected)
        h.voice.end()
        var attempts = 0
        let wrongOwner = h.voice.retryUnsent(ownerID: UUID()) { _ in attempts += 1; return UUID() }
        precondition(!wrongOwner && attempts == 0 && h.voice.unsentText != nil)
        let failed = h.voice.retryUnsent(ownerID: h.owner) { _ in attempts += 1; return nil }
        precondition(!failed && attempts == 1 && h.voice.unsentText != nil)
        h.submitSucceeds = true
        let recovered = h.voice.retryUnsent(ownerID: h.owner) { h.submit($0) }
        precondition(recovered && h.submitted == ["尚未保存的发言"] && h.voice.unsentText == nil && !h.voice.active)

        for delivery in ["failed", "retryable_failed", "terminal_failed", "held"] {
            let delivered = ConversationHarness(); await delivered.start()
            let pending = await delivered.commit(); delivered.transcript(pending, "已保存但未送达")
            await delivered.wait { delivered.submitted.count == 1 }
            delivered.snapshot.messages[0].delivery = delivery
            delivered.voice.refresh()
            precondition(delivered.voice.error != nil && delivered.voice.phase == .failed && delivered.voice.unsentText == nil && !delivered.audio.connected,
                         "Delivery \(delivery) must stop waiting and offer the existing text recovery path")
            precondition(delivered.snapshot.messages[0].content == "已保存但未送达", "A delivery failure retains the already-persisted chat message")
            delivered.close()
        }

        let network = ConversationHarness(); await network.start(); defer { network.close() }
        let input = await network.commit(); network.transcript(input, "网络错误前的提问")
        await network.wait { network.submitted.count == 1 }
        let reply = network.response("尚未播完的回答。")
        await network.wait { network.socket.speeches.count == 1 }
        let completion = await network.receiveAudio(for: network.socket.speeches[0])
        network.socket.push(["type": "error"]); await network.wait { network.voice.error != nil }
        network.device.completions[completion](); await network.settle()
        precondition(network.persisted[reply]?.state == "unavailable" && network.persisted[reply]?.played.isEmpty == true)
    }

    @MainActor static func inactiveSnapshotAndPersistenceFailure() async {
        let h = ConversationHarness(); await h.start()
        let commit = await h.commit()
        h.snapshot.active = false; h.voice.refresh()
        h.transcript(commit, "页面结束后的转写"); await h.settle()
        precondition(!h.voice.active && h.socket.closed && h.submitted.isEmpty, "Inactive owner/page must end audio and reject late transcripts")

        let warning = ConversationHarness(); warning.persistSucceeds = false; await warning.start(); defer { warning.close() }
        let input = await warning.commit(); warning.transcript(input, "播报记录保存失败")
        await warning.wait { warning.submitted.count == 1 }
        let reply = warning.response("实际仍可听到这一句。")
        await warning.play(0)
        precondition(warning.voice.persistenceWarning != nil && warning.persisted[reply] == nil)
        precondition(warning.persistenceAttempts.contains { $0.0 == reply && $0.1.played == ["实际仍可听到这一句。"] },
                     "Persistence failure must be explicit while real played callbacks remain distinct from queued text")
        let encoded = AgentVoicePlayback(played: ["完整一句。"], interrupted: "未完一句。", state: "interrupted")
        precondition(AgentVoicePlayback.read(encoded.json) == encoded && encoded.caption.contains("完整播完 1 段"))
    }
}
