import AVFoundation
import Foundation

@Observable
final class VoiceRecorder {
    private var recorder: AVAudioRecorder?
    var isRecording = false
    var lastFileURL: URL?

    func toggle() {
        if isRecording {
            recorder?.stop()
            isRecording = false
            return
        }
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appending(path: "capture-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]
        recorder = try? AVAudioRecorder(url: url, settings: settings)
        recorder?.record()
        lastFileURL = url
        isRecording = recorder?.isRecording == true
    }
}
