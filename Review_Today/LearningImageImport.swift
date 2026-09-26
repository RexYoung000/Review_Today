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
        let collector = ProviderResults(count: providers.count, completion: completion)
        for (index, provider) in providers.enumerated() {
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { value, error in
                    collector.receive(index, result: Result {
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
            } else if let type = [UTType.png, .jpeg, .tiff].first(where: { provider.hasItemConformingToTypeIdentifier($0.identifier) }) {
                let name = provider.suggestedName ?? "拖入图片.png"
                provider.loadDataRepresentation(forTypeIdentifier: type.identifier) { data, error in
                    collector.receive(index, result: Result {
                        if let error { throw error }
                        guard let data else { throw LearningImageAttachment.Failure.format }
                        return try LearningImageAttachment.prepare(data, name: name, clipboard: true)
                    })
                }
            } else {
                collector.receive(index, result: .failure(LearningImageAttachment.Failure.format))
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
