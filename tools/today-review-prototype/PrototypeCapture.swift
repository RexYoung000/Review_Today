import AppKit
import AVFoundation
@preconcurrency import ScreenCaptureKit
import Observation

/// Evidence export is limited to this prototype's own windows. No audio or desktop capture.
@MainActor @Observable
final class PrototypeCapture {
    var recording = false
    var message = ""
    var folder: URL {
        URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent("docs/evidence/2026-09-23-today-review-prototype")
    }
    func snapshot() {
        guard let window = NSApp.keyWindow else { return }
        Task { @MainActor in
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let content = try await SCShareableContent.currentProcess
                guard let own = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else { return }
                let config = SCStreamConfiguration(); config.width = Int(window.frame.width) * 2; config.height = Int(window.frame.height) * 2
                config.ignoreShadowsSingleWindow = true
                let shot = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: own), configuration: config)
                let bitmap = NSBitmapImageRep(cgImage: shot)
                let name = "native-\(Int(Date.now.timeIntervalSince1970 * 1000)).png"
                try bitmap.representation(using: .png, properties: [:])?.write(to: folder.appendingPathComponent(name))
                message = "截图已保存"
            } catch { message = "截图失败：\(error.localizedDescription)" }
        }
    }
    func toggleRecording() {
        if recording { recording = false; return }
        guard let window = NSApp.keyWindow else { return }
        recording = true; message = "正在录制 · 原速"
        Task { @MainActor in
            do { try await record(window) }
            catch { message = "录制失败：\(error.localizedDescription)" }
            recording = false
        }
    }
    private func record(_ window: NSWindow) async throws {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let content = try await SCShareableContent.currentProcess
        guard let own = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) && $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier }) else { throw CocoaError(.fileReadNoPermission) }
        let configuration = SCStreamConfiguration()
        configuration.width = Int(window.frame.width) / 2 * 2; configuration.height = Int(window.frame.height) / 2 * 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)
        configuration.capturesAudio = false; configuration.captureMicrophone = false
        configuration.showsCursor = true; configuration.ignoreShadowsSingleWindow = true
        let stream = SCStream(filter: SCContentFilter(desktopIndependentWindow: own), configuration: configuration, delegate: nil)
        let outputConfiguration = SCRecordingOutputConfiguration()
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("today-review-\(UUID().uuidString).mp4")
        outputConfiguration.outputURL = temporary; outputConfiguration.videoCodecType = .h264; outputConfiguration.outputFileType = .mp4
        let delegate = PrototypeRecordingDelegate()
        let output = SCRecordingOutput(configuration: outputConfiguration, delegate: delegate)
        try stream.addRecordingOutput(output)
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            DispatchQueue.global(qos: .userInitiated).async { stream.startCapture { error in if let error { continuation.resume(throwing: error) } else { continuation.resume() } } }
        }
        let start = ProcessInfo.processInfo.systemUptime
        while recording && ProcessInfo.processInfo.systemUptime - start < 90 && delegate.error == nil {
            try await Task.sleep(for: .milliseconds(100))
        }
        try await stream.stopCapture()
        for _ in 0..<100 { if delegate.finished || delegate.error != nil { break }; try await Task.sleep(for: .milliseconds(50)) }
        if let error = delegate.error { throw error }
        guard delegate.finished else { throw CocoaError(.fileWriteUnknown) }
        let url = folder.appendingPathComponent("native-interaction-\(Int(Date.now.timeIntervalSince1970)).mp4")
        try FileManager.default.moveItem(at: temporary, to: url)
        try "Native current-process window recording, 30 fps target, actual presentation timestamps, \(configuration.width)x\(configuration.height). No audio. Synthetic interactions; no model or microphone.\n".write(to: url.deletingPathExtension().appendingPathExtension("txt"), atomically: true, encoding: .utf8)
        message = "原速录像已保存"
    }
}
@MainActor
private final class PrototypeRecordingDelegate: NSObject, SCRecordingOutputDelegate {
    var finished = false
    var error: Error?
    nonisolated func recordingOutputDidFinishRecording(_ output: SCRecordingOutput) { Task { @MainActor in self.finished = true } }
    nonisolated func recordingOutput(_ output: SCRecordingOutput, didFailWithError error: Error) { Task { @MainActor in self.error = error } }
}
