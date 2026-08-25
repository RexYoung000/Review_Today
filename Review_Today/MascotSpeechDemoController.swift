import AVFoundation
import Combine
import SwiftUI

@MainActor
final class MascotSpeechDemoController: NSObject, ObservableObject, AVAudioPlayerDelegate {
    enum Phase: Equatable {
        case idle
        case preparing
        case playing
        case finishing
        case failed(String)
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var level = 0.0
    @Published private(set) var progress = 0.0

    private let synthesizer = AVSpeechSynthesizer()
    private var player: AVAudioPlayer?
    private var meterTimer: Timer?
    private var generationID = UUID()
    private var playbackID = UUID()
    private var temporaryURL: URL?
    private var completion: (() -> Void)?

    var isActive: Bool {
        switch phase {
        case .preparing, .playing, .finishing:
            true
        case .idle, .failed:
            false
        }
    }

    var isAudioDrivingMouth: Bool {
        phase == .playing
    }

    var isShowingFinishingSmile: Bool {
        phase == .finishing
    }

    var statusText: String {
        switch phase {
        case .idle:
            String(localized: "等待播放真实测试语音")
        case .preparing:
            String(localized: "正在生成本机测试语音…")
        case .playing:
            String(localized: "真实 TTS 正在播放 · 嘴型随音量变化")
        case .finishing:
            String(localized: "回应完成 · 短暂温柔微笑")
        case let .failed(message):
            String(localized: "语音生成失败：\(message)")
        }
    }

    func play(text: String, completion: @escaping () -> Void) {
        stop()
        self.completion = completion
        phase = .preparing

        let generationID = UUID()
        self.generationID = generationID
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("review-today-mascot-\(generationID.uuidString)")
            .appendingPathExtension("caf")
        temporaryURL = url

        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        utterance.rate = 0.47
        utterance.pitchMultiplier = 1.04
        utterance.volume = 0.92

        var audioFile: AVAudioFile?
        synthesizer.write(utterance) { [weak self] buffer in
            guard let pcmBuffer = buffer as? AVAudioPCMBuffer else { return }
            guard let self else { return }

            if pcmBuffer.frameLength == 0 {
                audioFile = nil
                Task { @MainActor in
                    guard self.generationID == generationID else { return }
                    self.beginPlayback(url: url)
                }
                return
            }

            do {
                if audioFile == nil {
                    audioFile = try AVAudioFile(forWriting: url, settings: pcmBuffer.format.settings)
                }
                try audioFile?.write(from: pcmBuffer)
            } catch {
                Task { @MainActor in
                    guard self.generationID == generationID else { return }
                    self.fail(error.localizedDescription)
                }
            }
        }
    }

    func stop() {
        generationID = UUID()
        playbackID = UUID()
        synthesizer.stopSpeaking(at: .immediate)
        player?.stop()
        player = nil
        meterTimer?.invalidate()
        meterTimer = nil
        completion = nil
        phase = .idle
        level = 0
        progress = 0
        removeTemporaryFile()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            finishPlayback(successfully: flag)
        }
    }

    private func beginPlayback(url: URL) {
        do {
            let player = try AVAudioPlayer(contentsOf: url)
            player.delegate = self
            player.isMeteringEnabled = true
            player.prepareToPlay()
            self.player = player
            playbackID = UUID()
            phase = .playing
            level = 0
            progress = 0
            player.play()

            meterTimer?.invalidate()
            meterTimer = Timer.scheduledTimer(
                timeInterval: 1 / 30,
                target: self,
                selector: #selector(sampleAudioLevel),
                userInfo: nil,
                repeats: true
            )
        } catch {
            fail(error.localizedDescription)
        }
    }

    @objc private func sampleAudioLevel() {
        guard let player, player.isPlaying else { return }
        player.updateMeters()
        let decibels = Double(player.averagePower(forChannel: 0))
        let target = decibels < -43 ? 0 : min(1, max(0, (decibels + 43) / 34))
        let response = target > level ? 0.54 : 0.24
        level += (target - level) * response
        progress = player.duration > 0 ? min(1, player.currentTime / player.duration) : 0
    }

    private func finishPlayback(successfully: Bool) {
        meterTimer?.invalidate()
        meterTimer = nil
        player = nil
        level = 0
        progress = 1

        guard successfully else {
            fail(String(localized: "播放被系统中止"))
            return
        }

        let finishingID = UUID()
        playbackID = finishingID
        phase = .finishing
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(650))
            guard let self, self.playbackID == finishingID else { return }
            self.phase = .idle
            self.progress = 0
            self.removeTemporaryFile()
            let completion = self.completion
            self.completion = nil
            completion?()
        }
    }

    private func fail(_ message: String) {
        synthesizer.stopSpeaking(at: .immediate)
        player?.stop()
        player = nil
        meterTimer?.invalidate()
        meterTimer = nil
        level = 0
        progress = 0
        phase = .failed(message)
        removeTemporaryFile()
    }

    private func removeTemporaryFile() {
        guard let temporaryURL else { return }
        try? FileManager.default.removeItem(at: temporaryURL)
        self.temporaryURL = nil
    }
}
