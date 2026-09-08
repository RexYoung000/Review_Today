import AppKit
import AVFoundation
import ScreenCaptureKit
import SwiftUI

/// Runs the actual product views against an in-memory store. All exports are
/// from this preview's own view, never another app or the daily database.
@MainActor @Observable
final class MrBPreviewCapture {
    var reduced = false
    var recording = false
    var message = ""

    private var folder: URL {
        URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent("docs/evidence/2026-09-08-mr-b")
    }

    func resize(_ width: CGFloat, _ height: CGFloat) {
        guard let window = NSApp.keyWindow else { return }
        window.setContentSize(NSSize(width: width, height: height)); window.center()
    }

    func snapshot() {
        guard let key = NSApp.keyWindow else { return }
        let window = key.sheetParent ?? key
        Task { @MainActor in
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let content = try await SCShareableContent.currentProcess
                guard let own = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else { return }
                let config = SCStreamConfiguration()
                config.width = Int(window.frame.width) * 2; config.height = Int(window.frame.height) * 2
                config.ignoreShadowsSingleWindow = true
                let shot = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: own), configuration: config)
                let bitmap = NSBitmapImageRep(cgImage: shot)
                try bitmap.representation(using: .png, properties: [:])?.write(to: folder.appendingPathComponent("native-\(Int(Date.now.timeIntervalSince1970)).png"))
            } catch { message = String(describing: error) }
        }
    }

    func toggleRecording() {
        if recording { recording = false; return }
        guard let view = NSApp.keyWindow?.contentView else { return }
        recording = true
        Task { @MainActor in
            do { try await record(view) }
            catch { message = String(describing: error); NSLog("QA export failed: %@", message) }
            recording = false
        }
    }

    private func record(_ view: NSView) async throws {
        guard let window = view.window else { throw CocoaError(.fileWriteUnknown) }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        // SDK currentProcess explicitly restricts this inventory to content available
        // to this process without TCC consent. Never request whole-desktop access.
        let content = try await SCShareableContent.currentProcess
        guard let ownWindow = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) && $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier }) else { throw CocoaError(.fileReadNoPermission) }
        let url = folder.appendingPathComponent("native-interaction-\(Int(Date.now.timeIntervalSince1970)).mp4")
        let configuration = SCStreamConfiguration()
        configuration.width = Int(window.frame.width) / 2 * 2
        configuration.height = Int(window.frame.height) / 2 * 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)
        configuration.capturesAudio = false; configuration.captureMicrophone = false
        configuration.showsCursor = true; configuration.ignoreShadowsSingleWindow = true
        let stream = SCStream(filter: SCContentFilter(desktopIndependentWindow: ownWindow), configuration: configuration, delegate: nil)
        let outputConfiguration = SCRecordingOutputConfiguration()
        outputConfiguration.outputURL = url
        outputConfiguration.videoCodecType = .h264; outputConfiguration.outputFileType = .mp4
        let delegate = PreviewRecordingDelegate()
        let output = SCRecordingOutput(configuration: outputConfiguration, delegate: delegate)
        try stream.addRecordingOutput(output)
        try await stream.startCapture()
        let start = ProcessInfo.processInfo.systemUptime
        while recording && ProcessInfo.processInfo.systemUptime - start < 45 && delegate.error == nil {
            try await Task.sleep(for: .milliseconds(50))
        }
        try await stream.stopCapture()
        for _ in 0..<100 {
            if delegate.finished || delegate.error != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        if let error = delegate.error { throw error }
        guard delegate.finished else { throw CocoaError(.fileWriteUnknown) }
        let record = "Native current-process window recording; 30 fps target; actual presentation timestamps; \(configuration.width)x\(configuration.height); reduced=\(reduced); no audio.\n"
        try record.write(to: url.deletingPathExtension().appendingPathExtension("txt"), atomically: true, encoding: .utf8)
        message = url.lastPathComponent
    }

}


@MainActor
private final class PreviewRecordingDelegate: NSObject, SCRecordingOutputDelegate {
    var finished = false
    var error: Error?
    nonisolated func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) {
        Task { @MainActor in self.finished = true }
    }
    nonisolated func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: Error) {
        Task { @MainActor in self.error = error }
    }
}
