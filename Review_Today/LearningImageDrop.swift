import AppKit
import OSLog
import SwiftUI

/// Keep the real AppKit drag pasteboard. SwiftUI's NSItemProvider conversion
/// may try to copy another app's protected cache before handing us the image.
struct LearningImageDropContainer<Content: View>: NSViewRepresentable {
    let enabled: Bool
    let onTarget: (Bool) -> Void
    let onDrop: (NSPasteboard) -> Bool
    @ViewBuilder let content: () -> Content

    func makeNSView(context: Context) -> LearningImageDropView {
        let view = LearningImageDropView()
        let host = NSHostingView(rootView: AnyView(content().environment(\.self, context.environment)))
        host.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(host)
        NSLayoutConstraint.activate([
            host.leadingAnchor.constraint(equalTo: view.leadingAnchor), host.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            host.topAnchor.constraint(equalTo: view.topAnchor), host.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
        view.host = host
        return view
    }

    func updateNSView(_ view: LearningImageDropView, context: Context) {
        view.enabled = enabled
        view.onTarget = onTarget
        view.onDrop = onDrop
        view.host?.rootView = AnyView(content().environment(\.self, context.environment))
    }
}

final class LearningImageDropView: NSView {
    var host: NSHostingView<AnyView>?
    var enabled = true
    var onTarget: ((Bool) -> Void)?
    var onDrop: ((NSPasteboard) -> Bool)?
    override init(frame: NSRect) {
        super.init(frame: frame)
        registerForDraggedTypes(LearningImageImport.draggedTypes)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }

    override func draggingEntered(_ sender: any NSDraggingInfo) -> NSDragOperation {
        let accepted = enabled && sender.draggingSourceOperationMask.contains(.copy)
            && LearningImageImport.containsDropImages(sender.draggingPasteboard)
        onTarget?(accepted)
        return accepted ? .copy : []
    }
    override func draggingUpdated(_ sender: any NSDraggingInfo) -> NSDragOperation { draggingEntered(sender) }
    override func draggingExited(_ sender: (any NSDraggingInfo)?) { onTarget?(false) }
    override func prepareForDragOperation(_ sender: any NSDraggingInfo) -> Bool {
        enabled && LearningImageImport.containsDropImages(sender.draggingPasteboard)
    }
    override func performDragOperation(_ sender: any NSDraggingInfo) -> Bool {
        onTarget?(false)
        return enabled && (onDrop?(sender.draggingPasteboard) ?? false)
    }
    override func concludeDragOperation(_ sender: (any NSDraggingInfo)?) { onTarget?(false) }
}

extension LearningImageImport {
    private nonisolated static let dropLog = Logger(subsystem: "Rex.Review-Today", category: "ImageDrop")
    enum DropPart {
        case input(Input)
        case promise(NSFilePromiseReceiver)
    }
    struct DropPlan {
        let parts: [DropPart]
        let reservationCount: Int
    }
    static var promiseTypes: [NSPasteboard.PasteboardType] { NSFilePromiseReceiver.readableDraggedTypes.map { .init($0) } }
    static var draggedTypes: [NSPasteboard.PasteboardType] { pasteboardTypes + promiseTypes }
    static func containsDropImages(_ board: NSPasteboard) -> Bool { board.availableType(from: draggedTypes) != nil }

    /// Capture while NSDraggingInfo is valid, preferring file promises over a
    /// URL into the source app's cache. The source writes into our destination.
    static func captureDrop(_ board: NSPasteboard, capacity: Int) throws -> DropPlan {
        let items = board.pasteboardItems ?? []
        guard !items.isEmpty, items.count <= capacity else { throw LearningImageAttachment.Failure.count }
        let urls = fileURLs(board)
        guard let objects = board.readObjects(forClasses: [NSFilePromiseReceiver.self, NSPasteboardItem.self]), objects.count == items.count else {
            throw LearningImageAttachment.Failure.unavailable
        }
        var promised = false
        let parts: [DropPart] = try objects.map { object in
            if let receiver = object as? NSFilePromiseReceiver {
                promised = true
                return .promise(receiver)
            }
            guard let item = object as? NSPasteboardItem else { throw LearningImageAttachment.Failure.format }
            return .input(try pasteboardInput(item, fileURLs: urls))
        }
        dropLog.notice("Native image drop: \(parts.count) items, promised files: \(promised)")
        // Legacy promises can contain several files in one pasteboard item.
        // Reserve the available capacity until their actual filenames arrive.
        return DropPlan(parts: parts, reservationCount: promised ? capacity : parts.count)
    }

    static func loadDrop(_ plan: DropPlan, timeout: TimeInterval = 30,
                         completion: @escaping @MainActor (Result<[LearningImageAttachment], Error>) -> Void) {
        guard !plan.parts.isEmpty, plan.reservationCount > 0, plan.reservationCount <= LearningImageAttachment.maximumCount else {
            completion(.failure(LearningImageAttachment.Failure.count)); return
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("review-today-image-drop-" + UUID().uuidString, isDirectory: true)
        do { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false) }
        catch { completion(.failure(LearningImageAttachment.Failure.unavailable)); return }
        let collector = DropResults(count: plan.parts.count, capacity: plan.reservationCount, directory: directory, completion: completion)
        let queue = OperationQueue()
        queue.name = "ReviewToday.ImageDrop"
        queue.maxConcurrentOperationCount = 1
        queue.qualityOfService = .userInitiated
        for (index, part) in plan.parts.enumerated() {
            switch part {
            case .input(let input):
                queue.addOperation { collector.receive(index, result: Result { [try input.load()] }) }
            case .promise(let receiver):
                // Call in the promise in the original drop event, not a later Task.
                receiver.receivePromisedFiles(atDestination: directory, options: [:], operationQueue: queue) { url, error in
                    let result = Result {
                        if let error { throw error }
                        guard url.isFileURL,
                              url.resolvingSymlinksInPath().path.hasPrefix(directory.resolvingSymlinksInPath().path + "/") else {
                            throw LearningImageAttachment.Failure.unavailable
                        }
                        // NSFilePromiseReceiver holds a coordinated read here.
                        return try LearningImageAttachment.load(url)
                    }
                    collector.receivePromise(index, names: receiver.fileNames, name: url.lastPathComponent, result: result)
                }
            }
        }
        Task {
            try? await Task.sleep(for: .seconds(timeout))
            collector.fail(LearningImageAttachment.Failure.unavailable)
        }
    }

    private nonisolated final class DropResults: @unchecked Sendable {
        private let lock = NSLock()
        private let count: Int
        private let capacity: Int
        private let directory: URL
        private let completion: @MainActor (Result<[LearningImageAttachment], Error>) -> Void
        private var values: [Int: [LearningImageAttachment]] = [:]
        private var promises: [Int: [String: LearningImageAttachment]] = [:]
        private var finished = false

        init(count: Int, capacity: Int, directory: URL, completion: @escaping @MainActor (Result<[LearningImageAttachment], Error>) -> Void) {
            self.count = count; self.capacity = capacity; self.directory = directory; self.completion = completion
        }
        func receivePromise(_ index: Int, names: [String], name: String, result: Result<LearningImageAttachment, Error>) {
            do {
                let image = try result.get()
                guard !names.isEmpty, names.contains(name), Set(names).count == names.count else { throw LearningImageAttachment.Failure.unavailable }
                guard names.count <= capacity else { throw LearningImageAttachment.Failure.count }
                lock.lock()
                guard !finished else { lock.unlock(); return }
                promises[index, default: [:]][name] = image
                let received = promises[index]!
                let complete = names.count == received.count
                lock.unlock()
                if complete { receive(index, result: .success(names.map { received[$0]! })) }
            } catch { fail(error) }
        }
        func receive(_ index: Int, result: Result<[LearningImageAttachment], Error>) {
            do {
                let images = try result.get()
                lock.lock()
                guard !finished else { lock.unlock(); return }
                values[index] = images
                let complete = values.count == count
                let total = values.values.reduce(0) { $0 + $1.count }
                let ordered = complete ? (0..<count).flatMap { values[$0]! } : []
                lock.unlock()
                guard total <= capacity else { throw LearningImageAttachment.Failure.count }
                if complete { finish(.success(ordered)) }
            } catch { fail(error) }
        }
        func fail(_ error: Error) {
            finish(.failure(error))
        }
        private func finish(_ result: Result<[LearningImageAttachment], Error>) {
            lock.lock()
            guard !finished else { lock.unlock(); return }
            finished = true
            lock.unlock()
            try? FileManager.default.removeItem(at: directory)
            switch result {
            case .success(let images):
                dropLog.notice("Native image drop completed: \(images.count) images")
                Task { @MainActor in completion(.success(images)) }
            case .failure(let error):
                let detail = error as NSError
                dropLog.error("Native image drop failed: \(detail.domain, privacy: .public)/\(detail.code)")
                let failure = (error as? LearningImageAttachment.Failure) ?? .unavailable
                Task { @MainActor in completion(.failure(failure)) }
            }
        }
    }
}
