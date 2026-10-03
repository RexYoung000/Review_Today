import Foundation
import Observation

/// Records device completion, never inference from generated text or server ACKs.
struct AgentVoicePlayback: Codable, Equatable {
    var played: [String] = []
    var interrupted: String?
    var state = "playing"

    var json: String { String(data: (try? JSONEncoder().encode(self)) ?? Data(), encoding: .utf8) ?? "{}" }
    static func read(_ value: String?) -> Self? {
        value.flatMap { $0.data(using: .utf8) }.flatMap { try? JSONDecoder().decode(Self.self, from: $0) }
    }
    var caption: String {
        switch state {
        case "played": "语音已播完 · \(played.count) 段"
        case "interrupted": "语音已中断 · 完整播完 \(played.count) 段"
        case "unavailable": "语音播放未完成 · 完整播完 \(played.count) 段"
        default: "语音已播 \(played.count) 段"
        }
    }
}

/// The chat owns persistence and Agent control. This coordinator only manages
/// explicit voice turns, sentence delivery and the lifetime of the audio mode.
@Observable @MainActor
final class AgentVoiceConversation {
    struct Message: Equatable {
        var id: UUID
        var runID: UUID?
        var role: String
        var content: String
        var state: String = "complete"
        var revision = 0
        var delivery = "delivered"
        var key: String { "\(id):\(revision)" }
    }
    struct Snapshot {
        var messages: [Message] = []
        var active = true
        var runningIDs: Set<UUID> = []
        var failedIDs: Set<UUID> = []
        var voiceOrigins: [UUID: Set<UUID>] = [:]
    }

    let audio: AgentVoiceAudio
    private(set) var active = false
    private(set) var ownerID: UUID?
    private(set) var error: String?
    private(set) var unsentText: String?
    private(set) var unsentOwnerID: UUID?
    private(set) var waitingForAgent = false
    private(set) var preparingSpeech = false
    private(set) var persistenceWarning: String?

    @ObservationIgnored private var lifetime = UUID()
    @ObservationIgnored private var startup: Task<Void, Never>?
    @ObservationIgnored private var observer: Task<Void, Never>?
    @ObservationIgnored private var read: (() -> Snapshot)?
    @ObservationIgnored private var submit: ((String) -> UUID?)?
    @ObservationIgnored private var stopReply: (() -> Bool)?
    @ObservationIgnored private var persist: ((UUID, AgentVoicePlayback) -> Bool)?
    @ObservationIgnored private var inputs: Set<UUID> = []
    @ObservationIgnored private var ignored: Set<String> = []
    @ObservationIgnored private var transcripts: [Int: String] = [:]
    @ObservationIgnored private var receivedUtterances: Set<UUID> = []
    @ObservationIgnored private var cursors: [String: Int] = [:]
    @ObservationIgnored private var sourcePrefixes: [String: String] = [:]
    @ObservationIgnored private var adoptedRevisions: [UUID: Int] = [:]
    @ObservationIgnored private var records: [UUID: AgentVoicePlayback] = [:]
    @ObservationIgnored private var current: (speechID: UUID, messageID: UUID, key: String, text: String)?

    init(audio: AgentVoiceAudio? = nil) { self.audio = audio ?? AgentVoiceAudio() }

    var phase: AgentVoiceComposerPhase {
        if error != nil { return .failed }
        if audio.connecting || !audio.connected { return .connecting }
        if audio.capturingSpeech { return .listening }
        if audio.pendingTranscriptions > 0 { return .transcribing }
        if audio.playingSpeech { return .speaking }
        if waitingForAgent || preparingSpeech { return .thinking }
        return .listening
    }

    var statusDetail: String? {
        if let error { return error }
        if let persistenceWarning { return persistenceWarning }
        if preparingSpeech && !audio.playingSpeech { return "正在准备语音回复" }
        return nil
    }

    func start(ownerID: UUID, read: @escaping () -> Snapshot,
               submit: @escaping (String) -> UUID?, stopReply: @escaping () -> Bool,
               persist: @escaping (UUID, AgentVoicePlayback) -> Bool,
               automaticallyRefresh: Bool = true) {
        guard !active, unsentText == nil else { return }
        lifetime = UUID(); let token = lifetime
        self.ownerID = ownerID; active = true; error = nil; persistenceWarning = nil
        self.read = read; self.submit = submit; self.stopReply = stopReply; self.persist = persist
        inputs.removeAll(); transcripts.removeAll(); receivedUtterances.removeAll()
        cursors.removeAll(); sourcePrefixes.removeAll(); records.removeAll(); adoptedRevisions.removeAll()
        ignored = Set(read().messages.filter { $0.role != "user" }.map(\.key))
        audio.onTranscript = { [weak self] text, id, generation in
            guard let self, self.active, self.lifetime == token,
                  self.receivedUtterances.insert(id).inserted else { return }
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { self.transcripts[generation] = trimmed }
            self.refresh()
        }
        audio.onSpeechStart = { [weak self] in
            guard let self, self.active, self.lifetime == token else { return }
            self.interruptReply()
        }
        audio.onSpeechPlayed = { [weak self] id in
            guard let self, self.active, self.lifetime == token,
                  let item = self.current, item.speechID == id else { return }
            var record = self.records[item.messageID] ?? AgentVoicePlayback()
            record.played.append(item.text); record.interrupted = nil
            self.records[item.messageID] = record
            self.saveRecord(item.messageID)
            self.current = nil; self.preparingSpeech = false
            self.refresh()
        }
        audio.onFailure = { [weak self] message in
            guard let self, self.active, self.lifetime == token else { return }
            self.finishCurrent(state: "unavailable")
            self.error = message
        }
        startup = Task { [weak self] in
            guard let self else { return }
            do { try await self.audio.start(ownerID: ownerID) }
            catch {
                guard self.active, self.lifetime == token else { return }
                self.error = self.audio.error ?? "语音连接失败，可以结束语音后重试。"
            }
        }
        if automaticallyRefresh {
            observer = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(250))
                    guard let self, self.active, self.lifetime == token, !Task.isCancelled else { return }
                    self.refresh()
                }
            }
        }
    }

    func refresh() {
        guard active, let snapshot = read?() else { return }
        guard snapshot.active else { end(); return }
        guard error == nil else { return }
        if !audio.capturingSpeech, audio.pendingTranscriptions == 0, !transcripts.isEmpty {
            let text = transcripts.keys.sorted().compactMap { transcripts[$0] }.joined(separator: "\n")
            transcripts.removeAll()
            guard let id = submit?(text) else {
                unsentText = text; unsentOwnerID = ownerID
                error = "这句话尚未保存，请保持当前页面，重试提交或复制后用文字继续。"
                audio.stop(); finishCurrent(state: "interrupted")
                return
            }
            inputs.insert(id); waitingForAgent = true
            return // Observe the saved graph on the next refresh.
        }
        let submitted = snapshot.messages.filter { inputs.contains($0.id) }
        if submitted.contains(where: { ["held", "failed", "retryable_failed", "terminal_failed"].contains($0.delivery) }) {
            error = "语音消息未送达，文字已保留在聊天中。结束语音后重试发送。"
            audio.stop(); finishCurrent(state: "unavailable"); return
        }
        let runIDs = Set(submitted.compactMap(\.runID)).union(snapshot.voiceOrigins.compactMap { runID, origins in
            origins.isDisjoint(with: inputs) ? nil : runID
        })
        let responses = snapshot.messages.filter {
            $0.role != "user" && $0.runID.map(runIDs.contains) == true && !ignored.contains($0.key)
        }
        waitingForAgent = !inputs.isEmpty && (submitted.contains { $0.runID == nil }
            || !runIDs.isDisjoint(with: snapshot.runningIDs))
        if !runIDs.isDisjoint(with: snapshot.failedIDs) {
            error = "这轮回复未完成，已保留文字。结束语音后可重试。"
            audio.stop(); finishCurrent(state: "unavailable"); return
        }
        guard audio.connected, !audio.capturingSpeech, audio.pendingTranscriptions == 0 else { return }
        for response in responses {
            if let adopted = adoptedRevisions[response.id], adopted != response.revision {
                if current?.messageID == response.id { audio.interrupt(); finishCurrent(state: "interrupted") }
                var record = records[response.id] ?? AgentVoicePlayback()
                record.state = "interrupted"; records[response.id] = record; saveRecord(response.id)
                ignored.insert(response.key); continue
            }
            guard !["failed", "interrupted"].contains(response.state) else {
                if current?.messageID == response.id { audio.interrupt(); finishCurrent(state: "interrupted") }
                ignored.insert(response.key); continue
            }
            // A final correction to a streamed prefix is not replayed as though
            // the already-heard wording had never existed.
            if let prefix = sourcePrefixes[response.key], !response.content.hasPrefix(prefix) {
                if current?.messageID == response.id { audio.interrupt(); finishCurrent(state: "interrupted") }
                var record = records[response.id] ?? AgentVoicePlayback()
                record.state = "interrupted"; records[response.id] = record; saveRecord(response.id)
                ignored.insert(response.key); continue
            }
            guard current == nil else { continue }
            let cursor = cursors[response.key] ?? 0
            let segments = AgentSpeechSegments.project(response.content, final: response.state == "complete")
            if let segment = segments.first(where: { $0.sourceEnd > cursor }) {
                let speechID = UUID()
                current = (speechID, response.id, response.key, segment.text)
                adoptedRevisions[response.id] = response.revision
                preparingSpeech = true
                cursors[response.key] = segment.sourceEnd
                sourcePrefixes[response.key] = String(decoding: response.content.utf16.prefix(segment.sourceEnd), as: UTF16.self)
                if records[response.id] == nil { records[response.id] = AgentVoicePlayback() }
                saveRecord(response.id)
                audio.speak(text: segment.text, id: speechID)
                break
            } else if response.state == "complete", var record = records[response.id], record.state == "playing" {
                record.state = "played"; records[response.id] = record; saveRecord(response.id)
            }
        }
    }

    private func interruptReply() {
        audio.interrupt(); finishCurrent(state: "interrupted")
        var running = false
        if let snapshot = read?() {
            ignored.formUnion(snapshot.messages.filter { $0.role != "user" }.map(\.key))
            running = !snapshot.runningIDs.isEmpty
        }
        if (running || !inputs.isEmpty), stopReply?() == false {
            persistenceWarning = "声音已停止；停止回复未保存，文字可能继续生成。"
        }
        inputs.removeAll(); waitingForAgent = false
    }

    /// Ending audio deliberately leaves an accepted Agent request in the chat.
    func end() {
        lifetime = UUID(); startup?.cancel(); observer?.cancel(); startup = nil; observer = nil
        finishCurrent(state: "interrupted")
        audio.stop(); audio.onTranscript = nil; audio.onSpeechStart = nil
        audio.onSpeechPlayed = nil; audio.onFailure = nil
        active = false; waitingForAgent = false; preparingSpeech = false; error = nil
        transcripts.removeAll(); read = nil; submit = nil; stopReply = nil; persist = nil
    }

    @discardableResult
    func retryUnsent(ownerID: UUID, submit: (String) -> UUID?) -> Bool {
        guard let text = unsentText, ownerID == unsentOwnerID, submit(text) != nil else { return false }
        unsentText = nil; unsentOwnerID = nil
        end()
        return true
    }

    func dismissCopiedInput() {
        unsentText = nil; unsentOwnerID = nil
        end()
    }

    private func finishCurrent(state: String) {
        if let item = current {
            var record = records[item.messageID] ?? AgentVoicePlayback()
            record.state = state; record.interrupted = item.text
            records[item.messageID] = record; saveRecord(item.messageID)
        }
        // A generation can still be producing its next paragraph after the
        // previous sentence finished; ending at that gap is also interruption.
        for id in Array(records.keys) where records[id]?.state == "playing" {
            records[id]?.state = state; saveRecord(id)
        }
        current = nil; preparingSpeech = false
    }

    private func saveRecord(_ id: UUID) {
        guard let record = records[id] else { return }
        if persist?(id, record) == false {
            persistenceWarning = "播放进度未保存；请以实际听到的内容为准。"
        }
    }
}
