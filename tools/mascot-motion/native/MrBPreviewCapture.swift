import AppKit
import AVFoundation
import ScreenCaptureKit
import SwiftUI

/// Captures the isolated motion studies with simulated presentation state. All exports are
/// from this preview's own view, never another app or the daily database.
@MainActor @Observable
final class MrBPreviewCapture {
    var reduced = false
    var recording = false
    var message = ""

    private var folder: URL {
        URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as! String)
            .appendingPathComponent(Bundle.main.bundleIdentifier == "Rex.Review-Today.MrBContactPreview" ? "docs/evidence/2026-09-08-mr-b/paragraph-wipe" : "docs/evidence/2026-09-08-mr-b")
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

    func recordIngestion(model: MrBPreviewModel, compact: Bool) {
        guard !recording && !model.reduced && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion,
              let window = NSApp.keyWindow else { return }
        NSApp.activate(ignoringOtherApps:true); window.makeKeyAndOrderFront(nil)
        model.enter("知识入库")
        if model.ingestion.outcome == "processing" { model.ingestion.resolve(id:model.ingestion.id,outcome:"cancelled") }
        model.beginIngestion(compact:compact); model.studyRecording = true; model.studyPaused = true; recording = true
        Task { @MainActor in
            do {
                try await Task.sleep(for:.milliseconds(600))
                // ScreenCaptureKit composites an attached sheet into its parent window.
                // Capture that parent at its actual size to avoid shrinking/cropping it.
                guard let view = window.contentView else { throw CocoaError(.fileWriteUnknown) }
                try await record(view,onStarted:{
                    model.ingestion.resolve(id:model.ingestion.id,outcome:"cancelled")
                    model.ingestion.begin(count:model.count,compact:compact); model.studyPaused = false
                },shouldStop:{model.ingestion.finished || !model.ingestion.presented})
            } catch { message=String(describing:error);NSLog("QA export failed: %@",message) }
            model.studyRecording = false; recording = false
        }
    }
    func recordAnswer(model: MrBPreviewModel) {
        guard !recording && !model.reduced && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion, let view=NSApp.keyWindow?.contentView else{return}
        NSApp.activate(ignoringOtherApps:true);view.window?.makeKeyAndOrderFront(nil)
        model.enter("答题反馈");model.answerSession.next();model.answerSession.fail=false;model.failedResource=false
        model.answerSession.text = model.answerSession.scenario == "again" ? "检索和生成都在直接生成答案。" : model.answerSession.scenario == "hard" ? "提示后想起来了：检索找资料，生成依据资料组织回答。" : "检索找到相关资料，生成依据资料组织回答。"
        model.studyRecording=true;recording=true
        Task { @MainActor in
            do {try await record(view,onStarted:{
                model.finished=false
                if let id=model.answerSession.begin() {Task {try? await Task.sleep(for:.milliseconds(650));model.answerSession.resolve(id:id)}}
            },shouldStop:{model.finished && model.answerSession.hasFeedback})}
            catch {message=String(describing:error);NSLog("QA export failed: %@",message)}
            model.studyRecording=false;recording=false
        }
    }
    func recordReactions(model: MrBPreviewModel) {
        guard !recording && !model.reduced && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion, let view=NSApp.keyWindow?.contentView else{return}
        NSApp.activate(ignoringOtherApps:true);view.window?.makeKeyAndOrderFront(nil)
        model.enter("答题反应");model.reactionLabels=false;model.studyMesh=false;model.studyPaused=true;model.studyRecording=true;recording=true
        Task { @MainActor in
            do {try await record(view,onStarted:{model.replayReactions()},shouldStop:{model.finished})}
            catch {message=String(describing:error);NSLog("QA export failed: %@",message)}
            model.studyRecording=false;recording=false
        }
    }
    func recordReview(model: MrBPreviewModel) {
        guard !recording && !model.reduced && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion,
              let view = NSApp.keyWindow?.contentView else { return }
        NSApp.activate(ignoringOtherApps:true); view.window?.makeKeyAndOrderFront(nil)
        model.enter("复习结算"); model.reviewReason="complete"; model.reviewCount=3
        model.studyRecording=true; recording=true
        Task { @MainActor in
            do { try await record(view,onStarted:{model.finished=false;model.token += 1},shouldStop:{model.finished}) }
            catch { message=String(describing:error);NSLog("QA export failed: %@",message) }
            model.studyRecording=false;recording=false
        }
    }

    func recordStudy(model:MrBPreviewModel,scene:String,completeAt:Double? = nil) {
        guard !recording && !model.reduced && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else { return }
        model.enter(scene); model.studyRecording = true; model.studyPaused = true; model.finished = false
        guard let view = NSApp.keyWindow?.contentView else { model.studyRecording = false; return }
        NSApp.activate(ignoringOtherApps:true); view.window?.makeKeyAndOrderFront(nil)
        recording = true
        Task { @MainActor in
            do { try await record(view,onStarted:{model.replayStudy()},shouldStop:{
                if let completeAt, model.isFlow && model.flowOutcome == "processing" && model.studyTime >= completeAt { model.signalFlow("saved") }
                return model.finished
            }) }
            catch { message=String(describing:error);NSLog("QA export failed: %@",message) }
            model.studyRecording = false; recording = false
        }
    }

    private func record(_ view: NSView,onStarted:()->Void = {},shouldStop:()->Bool = {false}) async throws {
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
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("mr-b-capture-\(UUID().uuidString).mp4")
        outputConfiguration.outputURL = temporary
        outputConfiguration.videoCodecType = .h264; outputConfiguration.outputFileType = .mp4
        let delegate = PreviewRecordingDelegate()
        let output = SCRecordingOutput(configuration: outputConfiguration, delegate: delegate)
        try stream.addRecordingOutput(output)
        // startCapture may synchronously wait on its file-extension request.
        // Keep that system call off the UI thread; record into our temporary
        // directory and only move a successfully finished file into evidence.
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            DispatchQueue.global(qos: .userInitiated).async {
                stream.startCapture { error in
                    if let error { continuation.resume(throwing: error) }
                    else { continuation.resume() }
                }
            }
        }
        try await Task.sleep(for:.milliseconds(350)); onStarted()
        let start = ProcessInfo.processInfo.systemUptime
        while recording && ProcessInfo.processInfo.systemUptime - start < 45 && delegate.error == nil && !shouldStop() {
            try await Task.sleep(for: .milliseconds(50))
        }
        if shouldStop() { try await Task.sleep(for:.milliseconds(600)) }
        try await stream.stopCapture()
        for _ in 0..<100 {
            if delegate.finished || delegate.error != nil { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        if let error = delegate.error { throw error }
        guard delegate.finished else { throw CocoaError(.fileWriteUnknown) }
        try FileManager.default.moveItem(at: temporary, to: url)
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
