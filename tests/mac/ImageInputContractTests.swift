import AppKit
import Foundation
import ImageIO
import SwiftData
import UniformTypeIdentifiers

@main
struct ImageInputContractTests {
    enum Disk: Error { case failed }
    @MainActor static func main() async throws {
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
        try await multipleImages(first: image, firstPath: path, directory: directory)
        print("PASS: image normalization, metadata removal, draft isolation, first-send rollback, image-only draft preservation, disk restart, archive/delete lifecycle and native paste dispatch")
        print("Synthetic image fixture: \(path.path)")
    }

    @MainActor static func multipleImages(first: LearningImageAttachment, firstPath: URL, directory: URL) async throws {
        let fixture = NSImage(size: NSSize(width: 1200, height: 700))
        fixture.lockFocus()
        NSColor.white.setFill(); NSRect(x: 0, y: 0, width: 1200, height: 700).fill()
        let style: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 40), .foregroundColor: NSColor.black]
        ("第二张合成学习材料：检查回答" as NSString).draw(at: NSPoint(x: 60, y: 570), withAttributes: style)
        ("生成  →  核对依据" as NSString).draw(at: NSPoint(x: 140, y: 400), withAttributes: style)
        ("引用缺失时，需要补查资料。" as NSString).draw(at: NSPoint(x: 60, y: 240), withAttributes: style)
        ("样例编号：RT-043；预算：18.75 元；数量：5。" as NSString).draw(at: NSPoint(x: 60, y: 110), withAttributes: style)
        fixture.unlockFocus()
        let second = try LearningImageAttachment.prepare(fixture.tiffRepresentation!, name: "第二张学习截图.png", clipboard: true)
        let secondPath = URL(fileURLWithPath: "/tmp/review-today-image-fixture-2.png")
        try second.data.write(to: secondPath)
        let images = [first, second], encoded = LearningImageAttachment.encodeAll(images)!
        precondition(LearningImageAttachment.decodeAll(first.encoded) == [first])
        precondition(LearningImageAttachment.decodeAll(encoded) == images)
        precondition(LearningImageAttachment.encodeAll([]) == nil)
        let singleFields = try ConversationProcessor.imageFields(first.encoded!, protocolVersion: 1)
        let fields = try ConversationProcessor.imageFields(encoded, protocolVersion: 2)
        precondition(singleFields["image"] != nil && singleFields["images"] == nil)
        precondition((fields["images"] as? [[String: Any]])?.compactMap { $0["sha256"] as? String } == images.map(\.sha256))
        do { _ = try ConversationProcessor.imageFields(encoded, protocolVersion: 1); preconditionFailure() }
        catch { precondition(HarnessAPIError.code(for: error) == "RT.IMAGE.SERVICE_UPDATE_REQUIRED") }

        let queue = LearningImageImportQueue()
        let a = try queue.reserve(2, existing: 1), b = try queue.reserve(1, existing: 1)
        precondition(queue.pendingCount == 3)
        do { _ = try queue.reserve(5, existing: 1); preconditionFailure() } catch LearningImageAttachment.Failure.count {}
        precondition(queue.finish(b, with: .success([second])).isEmpty)
        let ordered = queue.finish(a, with: .success(images))
        let published = try ordered.flatMap { try $0.get() }
        precondition(published == images + [second])
        precondition(!queue.isLoading)
        let cancelled = try queue.reserve(1, existing: 0)
        queue.cancel()
        precondition(queue.finish(cancelled, with: .success([first])).isEmpty)
        let bad = try queue.reserve(1, existing: 0), good = try queue.reserve(1, existing: 0)
        precondition(queue.finish(good, with: .success([second])).isEmpty)
        let drained = queue.finish(bad, with: .failure(LearningImageAttachment.Failure.format))
        precondition(drained.count == 2 && !queue.isLoading)
        let afterFailure = try drained[1].get()
        precondition(afterFailure == [second])

        let board = NSPasteboard.withUniqueName()
        defer { board.releaseGlobally() }
        precondition(board.writeObjects([firstPath as NSURL, secondPath as NSURL]))
        precondition(LearningImageImport.containsImages(board))
        // File loading normalizes an encoded file once more; compare against
        // independently loaded files, not the original TIFF conversion bytes.
        let fileImages = try [firstPath, secondPath].map { try LearningImageAttachment.load($0) }
        let pasted = try LearningImageImport.pasteboardInputs(board).map { try $0.load() }
        precondition(pasted.map(\.sha256) == fileImages.map(\.sha256))
        let editor = LearningEditor(); editor.isEditable = true; editor.string = "文字草稿不改变"
        var target = false, received: [LearningImageAttachment] = []
        editor.onImageDragTarget = { target = $0 }
        editor.onImagePaste = { board in
            received = (try? LearningImageImport.pasteboardInputs(board).map { try $0.load() }) ?? []
            return true
        }
        let dragging = ImageDragInfo(board)
        precondition(editor.draggingEntered(dragging) == .copy && target)
        precondition(editor.prepareForDragOperation(dragging))
        precondition(editor.performDragOperation(dragging) && !target)
        precondition(received.map(\.sha256) == fileImages.map(\.sha256) && editor.string == "文字草稿不改变")
        _ = editor.draggingEntered(dragging); editor.draggingExited(dragging)
        precondition(!target)
        editor.isEditable = false
        precondition(editor.draggingEntered(dragging).isEmpty && !editor.performDragOperation(dragging))

        // Exercise NSItemProvider itself for conversation-body drops, preserving
        // file ordering and rejecting the whole batch if a file is invalid.
        let providers = [NSItemProvider(object: firstPath as NSURL), NSItemProvider(object: secondPath as NSURL)]
        let providerImages: [LearningImageAttachment] = try await withCheckedThrowingContinuation { continuation in
            LearningImageImport.loadProviders(providers) { continuation.resume(with: $0) }
        }
        precondition(providerImages.map(\.sha256) == fileImages.map(\.sha256))
        try await fileBackedProviders(first: first, directory: directory)
        try await nativeDrops(first: first, firstPath: firstPath)
        let broken = directory.appendingPathComponent("broken.png")
        try Data("not a picture".utf8).write(to: broken)
        do {
            let _: [LearningImageAttachment] = try await withCheckedThrowingContinuation { continuation in
                LearningImageImport.loadProviders([providers[0], NSItemProvider(object: broken as NSURL)]) { continuation.resume(with: $0) }
            }
            preconditionFailure()
        } catch LearningImageAttachment.Failure.format {}
        let storeURL = directory.appendingPathComponent("multi.store")
        var sid: UUID!
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: storeURL))
            let c = container.mainContext; c.autosaveEnabled = false
            _ = try AgentComposerStore.prepare(c)
            let session = try AgentComposerStore.createSession(context: c); sid = session.id
            try LearningDraftStore().saveImage(encoded, sessionID: sid, context: c)
            do {
                _ = try AgentComposerStore.sendInitial("比较两张图片", in: session, context: c, image: encoded, save: { throw Disk.failed })
                preconditionFailure()
            } catch Disk.failed {}
            precondition(LearningImageAttachment.decodeAll(session.composerImage) == images)
        }
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: storeURL))
            let c = container.mainContext; c.autosaveEnabled = false
            let session = try c.fetch(FetchDescriptor<AgentSession>()).first { $0.id == sid }!
            precondition(LearningImageAttachment.decodeAll(session.composerImage) == images)
            let message = try AgentComposerStore.sendInitial("比较两张图片", in: session, context: c, image: session.composerImage)
            precondition(LearningImageAttachment.decodeAll(message.imageAttachment) == images && session.composerImage == nil)
        }
        print("PASS: legacy/multi-image codec, protocol guard, async order/cancellation/limit, multi-file clipboard, native editor drop, NSItemProvider batch, multi-image rollback and disk draft recovery")
        print("Second synthetic image fixture: \(secondPath.path)")
    }

    @MainActor static func fileBackedProviders(first: LearningImageAttachment, directory: URL) async throws {
        let source = CGImageSourceCreateWithData(first.data as CFData, nil)!
        let jpeg = NSMutableData()
        let destination = CGImageDestinationCreateWithData(jpeg, UTType.jpeg.identifier as CFString, 1, nil)!
        CGImageDestinationAddImageFromSource(destination, source, 0, nil)
        precondition(CGImageDestinationFinalize(destination))
        let path = directory.appendingPathComponent("拖入的 JPEG.jpg")
        try (jpeg as Data).write(to: path)
        let provider = FileBackedImageProvider()
        provider.suggestedName = path.lastPathComponent
        provider.registerFileRepresentation(forTypeIdentifier: UTType.jpeg.identifier, fileOptions: [], visibility: .all) { complete in
            complete(path, false, nil)
            return nil
        }
        // Some drag sources advertise public.jpeg but cannot supply NSData.
        // Keep Foundation's real temporary-file representation; reject only
        // the data request to reproduce the user's -1000 error deterministically.
        let bytesError: Error? = await withCheckedContinuation { c in
            _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.jpeg.identifier) { _, error in c.resume(returning: error) }
        }
        precondition((bytesError as NSError?)?.domain == NSItemProvider.errorDomain)
        let actual: [LearningImageAttachment] = try await withCheckedThrowingContinuation { c in
            LearningImageImport.loadProviders([provider]) { c.resume(with: $0) }
        }
        let expected = try LearningImageAttachment.load(path)
        precondition(actual.count == 1 && actual[0].sha256 == expected.sha256)
        precondition(actual[0].name == path.lastPathComponent && actual[0].mimeType == "image/jpeg")

        let bytes = jpeg as Data
        let dataProvider = DataBackedImageProvider()
        dataProvider.registerDataRepresentation(forTypeIdentifier: UTType.jpeg.identifier, visibility: .all) { done in
            done(bytes, nil); return nil
        }
        let legacy = LegacyImageProvider(item: path as NSURL, typeIdentifier: UTType.jpeg.identifier)
        let alternate = NSItemProvider()
        alternate.registerDataRepresentation(forTypeIdentifier: UTType.png.identifier, visibility: .all) { done in
            done(nil, Disk.failed); return nil
        }
        alternate.registerDataRepresentation(forTypeIdentifier: UTType.jpeg.identifier, visibility: .all) { done in
            done(bytes, nil); return nil
        }
        let staleURL = NSItemProvider()
        staleURL.registerDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier, visibility: .all) { done in
            done(nil, Disk.failed); return nil
        }
        staleURL.registerDataRepresentation(forTypeIdentifier: UTType.jpeg.identifier, visibility: .all) { done in
            done(bytes, nil); return nil
        }
        let fallbacks: [LearningImageAttachment] = try await withCheckedThrowingContinuation { c in
            LearningImageImport.loadProviders([provider, dataProvider, legacy, alternate, staleURL]) { c.resume(with: $0) }
        }
        precondition(fallbacks.count == 5 && fallbacks.allSatisfy { $0.sha256 == expected.sha256 })

        // Even a readable fallback must not bypass the original image limits.
        let oversized = directory.appendingPathComponent("too-large.jpg")
        try Data(count: LearningImageAttachment.maximumBytes + 1).write(to: oversized)
        let limited = NSItemProvider(object: oversized as NSURL)
        limited.registerDataRepresentation(forTypeIdentifier: UTType.jpeg.identifier, visibility: .all) { done in
            done(bytes, nil); return nil
        }
        do {
            let _: [LearningImageAttachment] = try await withCheckedThrowingContinuation { c in
                LearningImageImport.loadProviders([provider, limited]) { c.resume(with: $0) }
            }
            preconditionFailure()
        } catch LearningImageAttachment.Failure.size {}

        let unavailable = NSItemProvider()
        unavailable.registerDataRepresentation(forTypeIdentifier: UTType.jpeg.identifier, visibility: .all) { done in
            done(nil, Disk.failed); return nil
        }
        do {
            let _: [LearningImageAttachment] = try await withCheckedThrowingContinuation { c in
                LearningImageImport.loadProviders([unavailable]) { c.resume(with: $0) }
            }
            preconditionFailure()
        } catch LearningImageAttachment.Failure.unavailable {
            precondition(!LearningImageAttachment.Failure.unavailable.localizedDescription.contains("public.jpeg"))
        }
        let remote = LegacyImageProvider(item: URL(string: "https://example.invalid/image.jpg")! as NSURL, typeIdentifier: UTType.jpeg.identifier)
        do {
            let _: [LearningImageAttachment] = try await withCheckedThrowingContinuation { c in
                LearningImageImport.loadProviders([remote]) { c.resume(with: $0) }
            }
            preconditionFailure()
        } catch LearningImageAttachment.Failure.format {}
        print("PASS: JPEG file representation works when its data representation is unavailable")
        print("PASS: data/item/type fallbacks, stale URL recovery, atomic limit rejection and remote URL rejection")
    }

    @MainActor static func nativeDrops(first: LearningImageAttachment, firstPath: URL) async throws {
        let board = NSPasteboard.withUniqueName()
        defer { board.releaseGlobally() }
        let item = NSPasteboardItem()
        item.setString("file:///private/unreadable-cache-image.png", forType: .fileURL)
        item.setData(first.data, forType: .png)
        precondition(board.writeObjects([item]))
        let plan = try LearningImageImport.captureDrop(board, capacity: 8)
        precondition(plan.reservationCount == 1)
        let raw = try await drop(plan)
        let normalized = try LearningImageAttachment.load(firstPath)
        precondition(raw.count == 1 && raw[0].sha256 == normalized.sha256)
        let view = LearningImageDropView(frame: NSRect(x: 0, y: 0, width: 400, height: 300))
        let button = NSButton(frame: NSRect(x: 0, y: 0, width: 100, height: 30))
        view.addSubview(button)
        precondition(view.hitTest(NSPoint(x: 20, y: 15)) === button)
        var targeted = false, calls = 0
        view.onTarget = { targeted = $0 }
        view.onDrop = { calls += 1; return $0.name == board.name }
        let dragging = ImageDragInfo(board)
        precondition(view.draggingEntered(dragging) == .copy && targeted)
        precondition(view.performDragOperation(dragging) && calls == 1 && !targeted)
        view.enabled = false
        precondition(view.draggingEntered(dragging).isEmpty && !view.performDragOperation(dragging))
        let editor = LearningEditor(); editor.isEditable = true; editor.string = "保留输入"
        editor.onImageDrop = { calls += 1; return $0.name == board.name }
        precondition(editor.performDragOperation(dragging) && calls == 2 && editor.string == "保留输入")

        // Real AppKit promise metadata must be captured during the drop; calling
        // the promise outside a real NSDraggingSession is prohibited by AppKit.
        board.clearContents()
        let source = PromiseMetadataSource()
        let promised = NSFilePromiseProvider(fileType: UTType.png.identifier, delegate: source)
        precondition(board.writeObjects([promised]))
        let promisedPlan = try LearningImageImport.captureDrop(board, capacity: 5)
        precondition(promisedPlan.reservationCount == 5 && promisedPlan.parts.count == 1)
        guard case .promise = promisedPlan.parts[0] else { preconditionFailure() }

        let receiver = ControlledImagePromise(names: ["第一张.png", "第二张.png"], bytes: first.data, reverse: true)
        let combined = LearningImageImport.DropPlan(parts: [.input(.file(firstPath)), .promise(receiver)], reservationCount: 4)
        let loaded = try await drop(combined)
        precondition(loaded.map(\.name) == [firstPath.lastPathComponent, "第一张.png", "第二张.png"])
        precondition(!FileManager.default.fileExists(atPath: receiver.destination!.path))
        let tooMany = ControlledImagePromise(names: ["一.png", "二.png"], bytes: first.data)
        do {
            _ = try await drop(.init(parts: [.promise(tooMany)], reservationCount: 1))
            preconditionFailure()
        } catch LearningImageAttachment.Failure.count {}
        precondition(!FileManager.default.fileExists(atPath: tooMany.destination!.path))
        let refused = ControlledImagePromise(names: ["失败.png"], bytes: first.data, refuses: true)
        do {
            _ = try await drop(.init(parts: [.input(.file(firstPath)), .promise(refused)], reservationCount: 8))
            preconditionFailure()
        } catch LearningImageAttachment.Failure.unavailable {}
        precondition(!FileManager.default.fileExists(atPath: refused.destination!.path))
        let silent = ControlledImagePromise(names: ["未完成.png"], bytes: first.data, silent: true)
        do {
            _ = try await drop(.init(parts: [.promise(silent)], reservationCount: 8), timeout: 0.03)
            preconditionFailure()
        } catch LearningImageAttachment.Failure.unavailable {}
        precondition(!FileManager.default.fileExists(atPath: silent.destination!.path))
        withExtendedLifetime(source) {}
        print("PASS: native drop routing, click pass-through, raw pixels before cache URL, real promise metadata, ordered promised files, atomic failure/limit/timeout and temporary-file cleanup")
    }

    @MainActor static func drop(_ plan: LearningImageImport.DropPlan, timeout: TimeInterval = 2) async throws -> [LearningImageAttachment] {
        try await withCheckedThrowingContinuation { c in
            LearningImageImport.loadDrop(plan, timeout: timeout) { c.resume(with: $0) }
        }
    }
}

@MainActor private final class PromiseMetadataSource: NSObject, NSFilePromiseProviderDelegate {
    func filePromiseProvider(_ provider: NSFilePromiseProvider, fileNameForType fileType: String) -> String { "原生承诺.png" }
    nonisolated func filePromiseProvider(_ provider: NSFilePromiseProvider, writePromiseTo url: URL, completionHandler: @escaping ((any Error)?) -> Void) {
        preconditionFailure("Metadata capture must not call in the file promise")
    }
}

private nonisolated final class ControlledImagePromise: NSFilePromiseReceiver, @unchecked Sendable {
    private let names: [String]
    private let bytes: Data
    private let reverse: Bool
    private let refuses: Bool
    private let silent: Bool
    private(set) var destination: URL?
    override var fileNames: [String] { names }
    init(names: [String], bytes: Data, reverse: Bool = false, refuses: Bool = false, silent: Bool = false) {
        self.names = names; self.bytes = bytes; self.reverse = reverse; self.refuses = refuses; self.silent = silent
        super.init()
    }
    required init?(pasteboardPropertyList propertyList: Any, ofType type: NSPasteboard.PasteboardType) { return nil }
    override func receivePromisedFiles(atDestination destination: URL, options: [AnyHashable: Any] = [:], operationQueue: OperationQueue, reader: @escaping (URL, (any Error)?) -> Void) {
        self.destination = destination
        guard !silent else { return }
        for name in reverse ? Array(names.reversed()) : names {
            let url = destination.appendingPathComponent(name)
            let bytes = bytes, refuses = refuses
            operationQueue.addOperation {
                do {
                    if refuses { throw NSError(domain: NSCocoaErrorDomain, code: 513) }
                    try bytes.write(to: url)
                    reader(url, nil)
                } catch { reader(url, error) }
            }
        }
    }
}

private final class FileBackedImageProvider: NSItemProvider, @unchecked Sendable {
    override func loadDataRepresentation(forTypeIdentifier typeIdentifier: String, completionHandler: @escaping @Sendable (Data?, (any Error)?) -> Void) -> Progress {
        completionHandler(nil, NSError(domain: NSItemProvider.errorDomain, code: -1000, userInfo: [NSLocalizedDescriptionKey: "Cannot load representation of type \(typeIdentifier)"]))
        return Progress(totalUnitCount: 1)
    }
}

private class DataBackedImageProvider: NSItemProvider, @unchecked Sendable {
    override func loadFileRepresentation(forTypeIdentifier typeIdentifier: String, completionHandler: @escaping @Sendable (URL?, (any Error)?) -> Void) -> Progress {
        completionHandler(nil, NSError(domain: NSItemProvider.errorDomain, code: -1000))
        return Progress(totalUnitCount: 1)
    }
}

private final class LegacyImageProvider: DataBackedImageProvider, @unchecked Sendable {
    override func loadDataRepresentation(forTypeIdentifier typeIdentifier: String, completionHandler: @escaping @Sendable (Data?, (any Error)?) -> Void) -> Progress {
        completionHandler(nil, NSError(domain: NSItemProvider.errorDomain, code: -1000))
        return Progress(totalUnitCount: 1)
    }
}

@MainActor private final class ImageDragInfo: NSObject, NSDraggingInfo {
    let draggingPasteboard: NSPasteboard
    init(_ pasteboard: NSPasteboard) { draggingPasteboard = pasteboard }
    var draggingDestinationWindow: NSWindow? { nil }
    var draggingSourceOperationMask: NSDragOperation { .copy }
    var draggingLocation: NSPoint { .zero }
    var draggedImageLocation: NSPoint { .zero }
    var draggedImage: NSImage? { nil }
    var draggingSource: Any? { nil }
    var draggingSequenceNumber: Int { 1 }
    var draggingFormation: NSDraggingFormation = .none
    var animatesToDestination = false
    var numberOfValidItemsForDrop = 2
    var springLoadingHighlight: NSSpringLoadingHighlight { .none }
    func slideDraggedImage(to screenPoint: NSPoint) {}
    override func namesOfPromisedFilesDropped(atDestination dropDestination: URL) -> [String]? { nil }
    func resetSpringLoading() {}
    func enumerateDraggingItems(options enumOpts: NSDraggingItemEnumerationOptions, for view: NSView?, classes classArray: [AnyClass], searchOptions: [NSPasteboard.ReadingOptionKey: Any], using block: (NSDraggingItem, Int, UnsafeMutablePointer<ObjCBool>) -> Void) {}
}
