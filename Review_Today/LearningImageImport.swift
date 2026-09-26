import AppKit
import Foundation
import Observation
import UniformTypeIdentifiers

/// A batch is atomic; ready batches publish in gesture order, even if providers
/// finish out of order. Cancelling changes ownership before any late completion.
@MainActor @Observable final class LearningImageImportQueue {
    struct Ticket: Equatable {
        let id = UUID()
        let count: Int
    }
    private var waiting: [Ticket] = []
    private var ready: [UUID: Result<[LearningImageAttachment], Error>] = [:]
    var pendingCount: Int { waiting.reduce(0) { $0 + $1.count } }
    var isLoading: Bool { !waiting.isEmpty }

    func reserve(_ count: Int, existing: Int) throws -> Ticket {
        guard count > 0, count + existing + pendingCount <= LearningImageAttachment.maximumCount else {
            throw LearningImageAttachment.Failure.count
        }
        let ticket = Ticket(count: count)
        waiting.append(ticket)
        return ticket
    }

    func finish(_ ticket: Ticket, with result: Result<[LearningImageAttachment], Error>) -> [Result<[LearningImageAttachment], Error>] {
        guard waiting.contains(ticket) else { return [] }
        ready[ticket.id] = result
        var results: [Result<[LearningImageAttachment], Error>] = []
        while let first = waiting.first, let value = ready.removeValue(forKey: first.id) {
            waiting.removeFirst()
            results.append(value)
        }
        return results
    }

    func cancel() { waiting.removeAll(); ready.removeAll() }
}

enum LearningImageImport {
    enum Input: Sendable {
        case file(URL)
        case bytes(Data, String)

        nonisolated func load() throws -> LearningImageAttachment {
            switch self {
            case .file(let url): return try LearningImageAttachment.load(url)
            case .bytes(let data, let name): return try LearningImageAttachment.prepare(data, name: name, clipboard: true)
            }
        }
    }

    static let dropTypes: [UTType] = [.fileURL, .png, .jpeg, .tiff]
    static let pasteboardTypes: [NSPasteboard.PasteboardType] = [.fileURL, .png, .tiff, .init(UTType.jpeg.identifier)]

    static func containsImages(_ pasteboard: NSPasteboard) -> Bool {
        pasteboard.availableType(from: pasteboardTypes) != nil
    }

    static func pasteboardInputs(_ pasteboard: NSPasteboard) throws -> [Input] {
        let items = pasteboard.pasteboardItems ?? []
        guard items.count <= LearningImageAttachment.maximumCount else { throw LearningImageAttachment.Failure.count }
        return try items.map { item in
            if let value = item.string(forType: .fileURL), let url = URL(string: value), url.isFileURL { return .file(url) }
            for type in pasteboardTypes.dropFirst() {
                if let data = item.data(forType: type) { return .bytes(data, "剪贴板图片.png") }
            }
            throw LearningImageAttachment.Failure.format
        }
    }

    /// Start every provider load in the drop callback itself. Temporary file
    /// contents are consumed in its completion, before the provider releases it.
    static func loadProviders(_ providers: [NSItemProvider], completion: @escaping @MainActor (Result<[LearningImageAttachment], Error>) -> Void) {
        guard !providers.isEmpty, providers.count <= LearningImageAttachment.maximumCount else {
            completion(.failure(LearningImageAttachment.Failure.count))
            return
        }
        let collector = ProviderResults(count: providers.count, completion: completion)
        for (index, provider) in providers.enumerated() {
            ProviderImageLoader(provider: provider) { result in
                collector.receive(index, result: result)
            }.start()
        }
    }

    /// An advertised JPEG may be backed by a file or image object, without an
    /// NSData representation. Retain its provider through the serial fallback
    /// chain and consume temporary URLs before returning from their callbacks.
    private nonisolated final class ProviderImageLoader: @unchecked Sendable {
        private enum Representation {
            case fileURL
            case file(String), data(String), item(String)
        }
        private let provider: NSItemProvider
        private let completion: @Sendable (Result<LearningImageAttachment, Error>) -> Void
        private let representations: [Representation]
        private var next = 0
        private var imageFailure: LearningImageAttachment.Failure?

        init(provider: NSItemProvider, completion: @escaping @Sendable (Result<LearningImageAttachment, Error>) -> Void) {
            self.provider = provider
            self.completion = completion
            let supported: [UTType] = [.png, .jpeg, .tiff]
            var types = provider.registeredTypeIdentifiers.filter { identifier in
                guard let type = UTType(identifier) else { return false }
                return supported.contains { type.conforms(to: $0) }
            }
            for type in supported where !types.contains(type.identifier) && provider.hasItemConformingToTypeIdentifier(type.identifier) {
                types.append(type.identifier)
            }
            var choices: [Representation] = []
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) { choices.append(.fileURL) }
            for type in types { choices += [.file(type), .data(type), .item(type)] }
            representations = choices
        }

        func start() { loadNext() }

        private func loadNext() {
            guard next < representations.count else {
                completion(.failure(imageFailure ?? LearningImageAttachment.Failure.unavailable))
                return
            }
            let representation = representations[next]
            next += 1
            switch representation {
            case .fileURL:
                provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { [self] value, error in
                    accept(Result {
                        if let error { throw error }
                        let url: URL?
                        if let value = value as? URL { url = value }
                        else if let data = value as? Data { url = URL(dataRepresentation: data, relativeTo: nil) }
                        else if let text = value as? String { url = URL(string: text) }
                        else { url = nil }
                        guard let url, url.isFileURL else { throw LearningImageAttachment.Failure.format }
                        return try LearningImageAttachment.load(url)
                    })
                }
            case .file(let type):
                provider.loadFileRepresentation(forTypeIdentifier: type) { [self] url, error in
                    accept(Result {
                        if let error { throw error }
                        guard let url else { throw LearningImageAttachment.Failure.format }
                        return try readFile(url, type: type)
                    })
                }
            case .data(let type):
                provider.loadDataRepresentation(forTypeIdentifier: type) { [self] data, error in
                    accept(Result {
                        if let error { throw error }
                        guard let data else { throw LearningImageAttachment.Failure.format }
                        return try LearningImageAttachment.prepare(data, name: name(for: type), clipboard: true)
                    })
                }
            case .item(let type):
                provider.loadItem(forTypeIdentifier: type, options: nil) { [self] value, error in
                    accept(Result {
                        if let error { throw error }
                        if let url = value as? URL { return try readFile(url, type: type) }
                        if let data = value as? Data { return try LearningImageAttachment.prepare(data, name: name(for: type), clipboard: true) }
                        if let image = value as? NSImage, let data = image.tiffRepresentation {
                            return try LearningImageAttachment.prepare(data, name: name(for: type), clipboard: true)
                        }
                        throw LearningImageAttachment.Failure.format
                    })
                }
            }
        }

        private func readFile(_ url: URL, type: String) throws -> LearningImageAttachment {
            guard url.isFileURL else { throw LearningImageAttachment.Failure.format }
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            let limit = UTType(type)?.conforms(to: .tiff) == true ? 64 * 1024 * 1024 : LearningImageAttachment.maximumBytes
            guard let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= limit else { throw LearningImageAttachment.Failure.size }
            return try LearningImageAttachment.prepare(Data(contentsOf: url, options: .mappedIfSafe), name: name(for: type), clipboard: true)
        }

        private func name(for type: String) -> String {
            if let name = provider.suggestedName, !name.isEmpty { return name }
            return "拖入图片." + (UTType(type)?.preferredFilenameExtension ?? "png")
        }

        private func accept(_ result: Result<LearningImageAttachment, Error>) {
            switch result {
            case .success:
                completion(result)
            case .failure(let error):
                // A failed transport may have another representation; an image
                // that actually exceeds our limits must not fall back to a preview.
                if let failure = error as? LearningImageAttachment.Failure {
                    switch failure {
                    case .size, .dimensions, .count: completion(result); return
                    case .format: imageFailure = failure
                    case .unavailable: break
                    }
                }
                loadNext()
            }
        }
    }

    private nonisolated final class ProviderResults: @unchecked Sendable {
        private let lock = NSLock()
        private var values: [Int: Result<LearningImageAttachment, Error>] = [:]
        private let count: Int
        private let completion: @MainActor (Result<[LearningImageAttachment], Error>) -> Void
        nonisolated init(count: Int, completion: @escaping @MainActor (Result<[LearningImageAttachment], Error>) -> Void) {
            self.count = count; self.completion = completion
        }
        nonisolated func receive(_ index: Int, result: Result<LearningImageAttachment, Error>) {
            lock.lock()
            values[index] = result
            let complete = values.count == count
            let snapshot = values
            lock.unlock()
            guard complete else { return }
            let ordered = Result { try (0..<count).map { try snapshot[$0]!.get() } }
            Task { @MainActor in completion(ordered) }
        }
    }
}
