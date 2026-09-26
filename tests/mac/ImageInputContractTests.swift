import AppKit
import Foundation
import ImageIO
import SwiftData

@main
struct ImageInputContractTests {
    enum Disk: Error { case failed }
    @MainActor static func main() throws {
        let fixture = NSImage(size: NSSize(width: 1200, height: 700))
        fixture.lockFocus()
        NSColor.white.setFill(); NSRect(x: 0, y: 0, width: 1200, height: 700).fill()
        let title: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 42, weight: .bold), .foregroundColor: NSColor.black]
        let body: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 32), .foregroundColor: NSColor.black]
        ("合成学习材料：RAG 的两步流程" as NSString).draw(at: NSPoint(x: 60, y: 580), withAttributes: title)
        ("先检索相关资料，再结合资料生成回答。" as NSString).draw(at: NSPoint(x: 60, y: 480), withAttributes: body)
        ("检索  →  生成" as NSString).draw(at: NSPoint(x: 150, y: 340), withAttributes: title)
        ("保留原句：未找到依据时，不应编造答案。" as NSString).draw(at: NSPoint(x: 60, y: 200), withAttributes: body)
        ("样例编号：RT-042；预算：12.50 元；数量：3。" as NSString).draw(at: NSPoint(x: 60, y: 110), withAttributes: body)
        fixture.unlockFocus()
        let image = try LearningImageAttachment.prepare(fixture.tiffRepresentation!, name: "学习截图.png", clipboard: true)
        let encoded = image.encoded!
        precondition(image.width > 0 && image.height > 0 && image.mimeType == "image/png")
        precondition(LearningImageAttachment.decode(encoded) == image)
        let source = CGImageSourceCreateWithData(image.data as CFData, nil)!
        let metadata = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as! [CFString: Any]
        precondition(metadata[kCGImagePropertyGPSDictionary] == nil)
        let exif = metadata[kCGImagePropertyExifDictionary] as? [CFString: Any]
        precondition(exif?[kCGImagePropertyExifDateTimeOriginal] == nil)
        // A source with actual private metadata proves removal, rather than
        // merely checking that a metadata-free fixture remains metadata-free.
        let tagged = NSMutableData()
        let destination = CGImageDestinationCreateWithData(tagged, "public.jpeg" as CFString, 1, nil)!
        CGImageDestinationAddImageFromSource(destination, source, 0, [
            kCGImagePropertyExifDictionary: [kCGImagePropertyExifDateTimeOriginal: "2001:01:02 03:04:05"],
            kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 12.3, kCGImagePropertyGPSLatitudeRef: "N"]
        ] as CFDictionary)
        precondition(CGImageDestinationFinalize(destination))
        let taggedSource = CGImageSourceCreateWithData(tagged, nil)!
        let before = CGImageSourceCopyPropertiesAtIndex(taggedSource, 0, nil) as! [CFString: Any]
        precondition(before[kCGImagePropertyGPSDictionary] != nil)
        let clean = try LearningImageAttachment.prepare(tagged as Data, name: "元数据测试.jpg")
        let after = CGImageSourceCopyPropertiesAtIndex(CGImageSourceCreateWithData(clean.data as CFData, nil)!, 0, nil) as! [CFString: Any]
        precondition(after[kCGImagePropertyGPSDictionary] == nil)
        precondition((after[kCGImagePropertyExifDictionary] as? [CFString: Any])?[kCGImagePropertyExifDateTimeOriginal] == nil)
        do { _ = try LearningImageAttachment.prepare(Data(count: LearningImageAttachment.maximumBytes + 1), name: "large.png"); preconditionFailure() } catch LearningImageAttachment.Failure.size {}
        let directory = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("review-today-images-contract-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("images.store")
        let path = URL(fileURLWithPath: "/tmp/review-today-image-fixture.png")
        try image.data.write(to: path)
        do { _ = try LearningImageAttachment.prepare(Data("not a picture".utf8), name: "broken.png"); preconditionFailure() } catch LearningImageAttachment.Failure.format {}
        var sid: UUID!, mid: UUID!
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let c = container.mainContext; c.autosaveEnabled = false
            let draft = try AgentComposerStore.prepare(c)
            let store = LearningDraftStore()
            try store.saveImage(encoded, sessionID: nil, context: c)
            do {
                _ = try AgentComposerStore.sendFirst("看图", context: c, image: encoded, save: { throw Disk.failed })
                preconditionFailure()
            } catch Disk.failed {}
            precondition(draft.agentDraftImage == encoded)
            let moved = try AgentComposerStore.preserveLandingDraft(context: c)!
            precondition(moved.composerImage == encoded && draft.agentDraftImage == nil)
            let other = try AgentComposerStore.createSession(context: c)
            let otherImage = try store.image(sessionID: other.id, context: c)
            precondition(otherImage == nil)
            do {
                _ = try AgentComposerStore.sendInitial("解释这张图", in: moved, context: c, image: encoded, save: { throw Disk.failed })
                preconditionFailure()
            } catch Disk.failed {}
            precondition(moved.composerImage == encoded)
            let message = try AgentComposerStore.sendInitial("解释这张图", in: moved, context: c, image: encoded)
            sid = moved.id; mid = message.id
            precondition(message.contentType == "image" && message.imageAttachment == encoded && moved.composerImage == nil)
            precondition(LearningSessionActions.archive(moved, context: c))
            precondition(message.imageAttachment == encoded)
        }
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let c = container.mainContext; c.autosaveEnabled = false
            let message = try c.fetch(FetchDescriptor<AgentMessage>()).first { $0.id == mid }!
            precondition(LearningImageAttachment.decode(message.imageAttachment)?.sha256 == image.sha256)
            let impact = try SessionDeletion.impact([sid], context: c)
            _ = try SessionDeletion.perform(impact, includeCards: false, context: c)
            let remaining = try c.fetch(FetchDescriptor<AgentMessage>())
            precondition(remaining.isEmpty)
        }
        let editor = LearningEditor()
        editor.isEditable = true
        editor.string = "输入草稿"
        var pasted = 0
        editor.onImagePaste = { _ in pasted += 1; return true }
        editor.paste(nil)
        precondition(pasted == 1 && editor.string == "输入草稿")
        editor.isEditable = false; editor.paste(nil)
        precondition(pasted == 1)
        print("PASS: image normalization, metadata removal, draft isolation, first-send rollback, image-only draft preservation, disk restart, archive/delete lifecycle and native paste dispatch")
        print("Synthetic image fixture: \(path.path)")
    }
}
