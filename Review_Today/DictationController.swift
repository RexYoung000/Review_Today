import AVFoundation
import AppKit
import Foundation
import OSLog
import SwiftUI

extension Notification.Name { static let dictationSessionsDeleted = Notification.Name("ReviewToday.DictationSessionsDeleted") }

struct DictationResult: Codable {
    var text: String
    var raw_text: String?
    var cleaned: Bool?
    var cleanup_reason: String? = nil
}

enum DictationFiles {
    static var root: URL { FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appending(path: "Review Today/Dictation") }
    static func audio(_ id: UUID) -> URL { root.appending(path: id.uuidString + ".wav") }
    static func result(_ id: UUID) -> URL { root.appending(path: id.uuidString + ".json") }
    static func remove(_ id: UUID) { for url in [audio(id), result(id)] { try? FileManager.default.removeItem(at: url) } }
    static func exists(_ id: UUID) -> Bool { FileManager.default.fileExists(atPath: audio(id).path) || FileManager.default.fileExists(atPath: result(id).path) }
}

@Observable @MainActor
final class DictationController {
    enum Phase { case idle, permission, recording, transcribing, cleaning, applying }
    enum Stage: String { case recordingStart, transcription, cleanup, draftSave }
    var phase: Phase = .idle
    var level = 0.0
    var elapsed = 0.0
    var error: String?
    var notice: String?
    var pending = false
    var settling = false
    var insertion: EditorInsertion?
    private(set) var owner: UUID?
    private(set) var timings: [Stage: Double] = [:]
    private var applyingStarted: TimeInterval?
    private var appliedRaw = false
    private let clock: () -> TimeInterval
    private static let logger = Logger(subsystem: "ReviewToday.Dictation", category: "timing")
    private var recorder: AVAudioRecorder?
    private var timer: Timer?
    private var work: Task<Void, Never>?
    private var generation = UUID()
    private let permission: () async -> Bool
    private let transport: ((String, Data) async throws -> DictationResult)?
    init(permission: @escaping () async -> Bool = { await AVCaptureDevice.requestAccess(for: .audio) },
         transport: ((String, Data) async throws -> DictationResult)? = nil,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.permission = permission; self.transport = transport; self.clock = clock
    }
    var busy: Bool { phase != .idle }
    var mascotPhase: MascotPhase {
        switch phase {
        case .recording: .listening
        case .transcribing, .cleaning: .thinking
        case .idle, .permission, .applying: .idle
        }
    }
    var title: String {
        switch phase {
        case .idle: error ?? (pending ? "有未完成听写，可重试或删除" : (notice ?? (settling ? "已停止" : "")))
        case .permission: "正在请求麦克风权限"
        case .recording: "正在聆听 · \(Int(elapsed)) / 300 秒"
        case .transcribing: "正在转写"
        case .cleaning: "正在整理文字"
        case .applying: "正在保存草稿"
        }
    }
    func bind(_ id: UUID?) {
        guard owner != id else { return }
        leave(); owner = id; error = nil; pending = id.map(DictationFiles.exists) ?? false
    }
    func leave() {
        generation = UUID(); work?.cancel(); work = nil
        recorder?.stop(); recorder = nil; timer?.invalidate(); timer = nil
        phase = .idle; level = 0; insertion = nil; settling = false
        notice = nil; applyingStarted = nil; appliedRaw = false
        pending = owner.map(DictationFiles.exists) ?? false
    }
    func cancel() { let id = owner; leave(); if let id { DictationFiles.remove(id) }; pending = false; error = nil; settle() }
    func start() {
        guard !busy, let id = owner else { return }
        error = nil; notice = nil; settling = false; timings = [:]; phase = .permission; generation = UUID(); let token = generation
        work = Task { [weak self] in
            guard let self else { return }
            let allowed = await self.permission()
            guard self.generation == token, !Task.isCancelled else { return }
            guard allowed else { self.phase = .idle; self.error = "麦克风权限未开启，请在系统设置中允许 Review Today 使用麦克风。"; return }
            let startup = self.clock()
            do {
                try FileManager.default.createDirectory(at: DictationFiles.root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                DictationFiles.remove(id)
                let recording = try AVAudioRecorder(url: DictationFiles.audio(id), settings: [AVFormatIDKey: Int(kAudioFormatLinearPCM), AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
                recording.isMeteringEnabled = true
                guard recording.record(forDuration: 300) else { throw CocoaError(.fileWriteUnknown) }
                self.recorder = recording; self.elapsed = 0; self.phase = .recording; self.pending = true
                self.recordTiming(.recordingStart, since: startup)
                self.timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
                    MainActor.assumeIsolated {
                        guard let self, let recorder = self.recorder else { return }
                        recorder.updateMeters(); self.elapsed = recorder.currentTime
                        self.level = max(0, min(1, (Double(recorder.averagePower(forChannel: 0)) + 50) / 45))
                        if self.elapsed >= 300 { self.finish() }
                        else if !recorder.isRecording { self.finish() }
                    }
                }
            } catch { self.phase = .idle; self.error = "无法开始录音，请检查麦克风和可用存储空间。" }
        }
    }
    func finish() { guard phase == .recording else { return }; recorder?.stop(); recorder = nil; timer?.invalidate(); timer = nil; phase = .idle; beginProcessing() }
    func retry() {
        guard !busy, let id = owner else { return }
        guard DictationFiles.exists(id) else { return }
        timings = [:]
        beginProcessing()
    }
    private func beginProcessing() {
        guard !busy, let id = owner else { return }
        generation = UUID(); let token = generation; error = nil; notice = nil; settling = false; level = 0; appliedRaw = false
        phase = .transcribing
        work = Task { [weak self] in
            guard let self else { return }
            do {
                var result: DictationResult
                if let data = try? Data(contentsOf: DictationFiles.result(id)), let saved = try? JSONDecoder().decode(DictationResult.self, from: data) { result = saved }
                else {
                    result = try await self.request("transcribe", body: Data(contentsOf: DictationFiles.audio(id)), audio: true)
                    guard self.generation == token, !Task.isCancelled, DictationFiles.exists(id) else { return }
                    try JSONEncoder().encode(result).write(to: DictationFiles.result(id), options: .atomic)
                }
                guard self.generation == token, !Task.isCancelled else { return }
                if result.raw_text == nil {
                    self.phase = .cleaning
                    let raw = result.text
                    do { result = try await self.request("clean", body: JSONSerialization.data(withJSONObject: ["text": raw]), audio: false) }
                    catch { if Task.isCancelled { throw CancellationError() }; result = .init(text: raw, raw_text: raw, cleaned: false) }
                    guard self.generation == token, !Task.isCancelled, DictationFiles.exists(id) else { return }
                    try JSONEncoder().encode(result).write(to: DictationFiles.result(id), options: .atomic)
                }
                self.appliedRaw = result.cleaned == false
                self.phase = .applying
                self.applyingStarted = self.clock()
                self.insertion = EditorInsertion(text: result.text, appendToEnd: true)
            } catch {
                guard self.generation == token, !Task.isCancelled else { return }
                self.phase = .idle; self.pending = true
                self.error = (error as? DictationFailure)?.message ?? "听写未完成，录音已保留。可以重试或删除。"
            }
        }
    }
    func applied(saved: Bool) {
        guard phase == .applying, let id = owner else { return }
        insertion = nil; phase = .idle; settle()
        if let applyingStarted { recordTiming(.draftSave, since: applyingStarted); self.applyingStarted = nil }
        if saved {
            DictationFiles.remove(id); pending = false
            showNotice(appliedRaw ? "已保留原始转写，可直接编辑" : "已添加到草稿")
        }
        else { pending = true; error = "草稿未能保存，听写结果已保留，请重试。" }
    }
    private func showNotice(_ text: String) {
        notice = text
        NSAccessibility.post(element: NSApplication.shared, notification: .announcementRequested,
                             userInfo: [.announcement: text, .priority: NSAccessibilityPriorityLevel.medium.rawValue])
        let token = generation
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(4))
            guard let self, self.generation == token else { return }
            self.notice = nil
        }
    }
    private func recordTiming(_ stage: Stage, since started: TimeInterval) {
        let duration = max(0, clock() - started)
        timings[stage] = duration
        Self.logger.info("stage=\(stage.rawValue, privacy: .public) elapsed_ms=\(Int(duration * 1000), privacy: .public)")
    }
    private func settle() {
        settling = true
        let token = generation
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(450))
            guard let self, self.generation == token else { return }
            self.settling = false
        }
    }
    private func request(_ action: String, body: Data, audio: Bool) async throws -> DictationResult {
        let started = clock(), token = generation
        defer { if generation == token { recordTiming(audio ? .transcription : .cleanup, since: started) } }
        if let transport { return try await transport(action, body) }
        try AppRuntime.current.requireSending()
        var request = URLRequest(url: AgentAPI.base.appending(path: "v2/dictation/\(action)"))
        request.httpMethod = "POST"; request.httpBody = body; request.timeoutInterval = audio ? 90 : 30
        request.setValue(audio ? "audio/wav" : "application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Dictation-ID")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            let code = (try? JSONSerialization.jsonObject(with: data) as? [String: String])?["detail"] ?? ""
            throw DictationFailure(code: code)
        }
        return try JSONDecoder().decode(DictationResult.self, from: data)
    }
}
struct DictationFailure: Error {
    var code: String
    var message: String {
        switch code {
        case "DICTATION_SILENCE": "没有识别到清晰人声，请重新录制。"
        case "DICTATION_NOT_CONFIGURED", "DICTATION_ACCESS": "转写服务尚未配置或无访问权限，录音已保留。"
        case "DICTATION_DURATION", "DICTATION_TOO_LARGE": "录音超过 5 分钟限制，请重新录制。"
        case "DICTATION_TIMEOUT": "转写等待超时，录音已保留；重试可能再次计费。"
        default: "转写未完成，录音已保留；可以重试或删除。"
        }
    }
}
