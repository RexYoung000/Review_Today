import Foundation
import Observation

/// Synthetic, in-memory state shared by both native dictation studies.
/// This model never records audio, calls a service, or sends a real message.
@MainActor
@Observable
final class DictationDemoState {
    enum Phase: Equatable {
        case idle, recording, transcribing, cleaning, failed
    }

    enum Signal: String, CaseIterable {
        case natural = "自然说话"
        case quiet = "轻声"
        case silent = "静音"
    }

    private(set) var phase: Phase = .idle
    var draft = ""
    private(set) var notice: String?
    private(set) var elapsed: Double = 0
    var signal: Signal = .natural
    var failNext = false
    private(set) var lastSent: String?
    var hasPending: Bool { phase != .idle }

    @ObservationIgnored private var startedAt: Date?
    @ObservationIgnored private var heardSpeech = false
    @ObservationIgnored private var pendingTranscript: String?
    @ObservationIgnored private var generation: UInt = 0
    @ObservationIgnored private var processingTask: Task<Void, Never>?
    @ObservationIgnored private let transcriptionDelay: Duration
    @ObservationIgnored private let cleaningDelay: Duration

    init(
        transcriptionDelay: Duration = .milliseconds(1_300),
        cleaningDelay: Duration = .milliseconds(900)
    ) {
        self.transcriptionDelay = transcriptionDelay
        self.cleaningDelay = cleaningDelay
    }

    func start() {
        guard phase == .idle else { return }
        invalidateProcessing()
        notice = nil
        elapsed = 0
        heardSpeech = false
        pendingTranscript = nil
        startedAt = .now
        phase = .recording
    }

    func tick(date: Date) {
        guard phase == .recording, let startedAt else { return }
        elapsed = min(300, max(elapsed, date.timeIntervalSince(startedAt), 0))
        if level(at: elapsed) > 0.018 {
            heardSpeech = true
        }
        if elapsed >= 300 {
            finish()
        }
    }

    /// Pass elapsed seconds from the beginning of this simulated recording.
    /// Gaps are genuinely zero, so a silent signal never produces a voice trace.
    func level(at time: TimeInterval) -> Double {
        guard phase == .recording, signal != .silent, time.isFinite else { return 0 }
        let position = max(0, time).truncatingRemainder(dividingBy: 5.8)
        let phrase: (start: Double, end: Double)?
        switch position {
        case 0.15..<1.35: phrase = (0.15, 1.35)
        case 1.85..<3.55: phrase = (1.85, 3.55)
        case 4.35..<5.10: phrase = (4.35, 5.10)
        default: phrase = nil
        }
        guard let phrase else { return 0 }
        let edge = min(1, (position - phrase.start) / 0.12, (phrase.end - position) / 0.16)
        let syllables = 0.42 + 0.38 * pow(sin(position * 8.2), 2)
        let detail = 0.85 + 0.15 * sin(position * 23)
        let volume = signal == .quiet ? 0.19 : 0.95
        return max(0, min(1, edge * syllables * detail * volume))
    }

    func finish() {
        guard phase == .recording else { return }
        if let startedAt {
            elapsed = min(300, max(elapsed, Date.now.timeIntervalSince(startedAt)))
        }
        heardSpeech = heardSpeech || level(at: elapsed) > 0.018
        startedAt = nil
        guard heardSpeech else {
            pendingTranscript = nil
            phase = .idle
            notice = "未检测到语音，没有添加文字"
            return
        }
        pendingTranscript = "请帮我把今天学到的内容整理成三个要点，再给我一道理解检查题。"
        processPendingTranscript()
    }

    func cancel() {
        guard hasPending else { return }
        invalidateProcessing()
        startedAt = nil
        heardSpeech = false
        pendingTranscript = nil
        phase = .idle
        notice = "已取消，草稿已保留"
    }

    func retry() {
        guard phase == .failed, pendingTranscript != nil else { return }
        processPendingTranscript()
    }

    func reset() {
        invalidateProcessing()
        phase = .idle
        draft = ""
        notice = nil
        elapsed = 0
        signal = .natural
        failNext = false
        lastSent = nil
        startedAt = nil
        heardSpeech = false
        pendingTranscript = nil
    }

    func send() {
        guard phase == .idle else { return }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            notice = "草稿为空"
            return
        }
        lastSent = text
        draft = ""
        notice = "已模拟发送"
    }

    private func invalidateProcessing() {
        generation &+= 1
        processingTask?.cancel()
        processingTask = nil
    }

    private func processPendingTranscript() {
        guard let transcript = pendingTranscript else { return }
        invalidateProcessing()
        let activeGeneration = generation
        let shouldFail = failNext
        failNext = false
        notice = nil
        phase = .transcribing
        processingTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await Task.sleep(for: transcriptionDelay)
                guard generation == activeGeneration, !Task.isCancelled else { return }
                if shouldFail {
                    phase = .failed
                    notice = "模拟转写失败，可以重试或丢弃"
                    processingTask = nil
                    return
                }
                phase = .cleaning
                try await Task.sleep(for: cleaningDelay)
                guard generation == activeGeneration, !Task.isCancelled else { return }
                if !draft.isEmpty, draft.last?.isWhitespace != true {
                    draft += "\n"
                }
                draft += transcript
                pendingTranscript = nil
                heardSpeech = false
                phase = .idle
                notice = "已添加到草稿"
                processingTask = nil
            } catch {
                // Cancellation invalidates this generation. It must never
                // overwrite a later recording or append a late result.
            }
        }
    }
}
