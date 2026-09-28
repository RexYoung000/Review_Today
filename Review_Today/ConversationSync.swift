import Foundation
import SwiftData

/// Drain the network while SwiftData and SwiftUI finish the previous frame.
private actor ConversationPageInbox {
    private var pages: [Data] = []
    private var finished = false
    private var failure: Error?

    func append(_ page: Data) { pages.append(page) }
    func finish(_ error: Error? = nil) { failure = error; finished = true }
    func drain() -> (pages: [Data], finished: Bool, failure: Error?) {
        let result = pages
        pages.removeAll(keepingCapacity: true)
        return (result, finished, failure)
    }
}

struct ConversationEventSubscriptions {
    private var requested: [UUID: Int] = [:]
    private var completed: [UUID: Int] = [:]
    func version(_ id: UUID) -> Int { requested[id, default: 0] }
    func needsRefresh(_ id: UUID) -> Bool { completed[id] != version(id) }
    mutating func refresh(_ id: UUID) { requested[id] = version(id) + 1 }
    mutating func finish(_ id: UUID, version: Int) { completed[id] = version }
}

/// One outbox owner and one event consumer per Session. Network suspension never
/// delays editor input, and the legacy capture/review loop cannot hold this queue.
@MainActor
final class ConversationSync {
    private static let wakeName = Notification.Name("ReviewTodayConversationWake")
    static func wake() { NotificationCenter.default.post(name: wakeName, object: nil) }

    private var streams: [UUID: Task<Void, Never>] = [:]
    private var subscriptions = ConversationEventSubscriptions()
    private var deletionCleaner: Task<Void, Never>?
    private var lookups: [UUID: Task<Void, Never>] = [:]
    private var senders: [UUID: Task<Void, Never>] = [:]
    private var controllers: [UUID: Task<Void, Never>] = [:]
    private var ackTargets: [UUID: Int] = [:]
    private var ackers: [UUID: Task<Void, Never>] = [:]
    private var snapshotters: [UUID: Task<Void, Never>] = [:]

    func run(context: ModelContext, monitor: AgentServiceMonitor) async {
        guard AppRuntime.current.allowsSending else { return }
        try? LearningMemory.backfill(context: context)
        for session in (try? context.fetch(FetchDescriptor<AgentSession>())) ?? [] {
            session.memoryPolicySyncedRevision = -1
            session.memoryContentSyncedRevision = -1
        }
        let (signals, continuation) = AsyncStream<Void>.makeStream(bufferingPolicy: .bufferingNewest(1))
        let observer = NotificationCenter.default.addObserver(forName: Self.wakeName, object: nil, queue: .main) { _ in continuation.yield(()) }
        let recovery = Task {
            while !Task.isCancelled {
                continuation.yield(())
                try? await Task.sleep(for: .seconds(1))
            }
        }
        defer {
            NotificationCenter.default.removeObserver(observer)
            recovery.cancel()
            for stream in streams.values { stream.cancel() }
            for task in Array(senders.values) + Array(controllers.values) + Array(ackers.values) + Array(snapshotters.values) { task.cancel() }
            streams.removeAll()
        }
        for await _ in signals {
            if Task.isCancelled { return }
            guard monitor.serviceReachable && monitor.conversationSupported else { continue }
            if deletionCleaner == nil {
                deletionCleaner = Task {
                    defer { self.deletionCleaner = nil }
                    await SessionDeletion.cleanPending(context: context)
                    await LocalDataReset.cleanPending(context: context)
                }
            }
            guard let work = try? ConversationWorkSnapshot(context: context) else { continue }
            let sessions = work.sessions
            let existingIDs = Set(sessions.map(\.id))
            for id in streams.keys where !existingIDs.contains(id) { streams[id]?.cancel(); streams[id] = nil; ackTargets[id] = nil }
            respondToLookups(context: context, runs: work.runs)
            for session in sessions {
                if controllers[session.id] == nil && work.needsControl(session) {
                    controllers[session.id] = Task {
                        defer { self.controllers[session.id] = nil }
                        await ConversationProcessor.tick(context: context, monitor: monitor, pollEvents: false, onlySession: session.id, controlsOnly: true, work: work)
                        if (work.controlsBySession[session.id] ?? []).contains(where: { $0.sent }) {
                            // A completed/failed Session has no live subscription.
                            // Control acceptance reopens it even if retry finished
                            // before its POST response reached the App.
                            self.subscriptions.refresh(session.id)
                            Self.wake()
                        }
                    }
                }
                if senders[session.id] == nil && session.status == "active" && !(work.messagesBySession[session.id] ?? []).isEmpty {
                    senders[session.id] = Task {
                        defer { self.senders[session.id] = nil }
                        await ConversationProcessor.tick(context: context, monitor: monitor, pollEvents: false, onlySession: session.id, skipControls: true, work: work)
                    }
                }
                scheduleACK(session.id)
            }
            for session in sessions {
                guard let runs = work.runsBySession[session.id] else { continue }
                let active = runs.contains { (["accepted", "running", "stopping", "adjusting", "resuming"].contains($0.status) || ($0.status == "queued" && !session.runPaused)) }
                let awaitingCaptureReceipt = TopicCaptureOffer.read(session.captureOffersJSON).contains { $0.status == "saving" }
                guard streams[session.id] == nil, active || awaitingCaptureReceipt || subscriptions.needsRefresh(session.id) else { continue }
                let subscriptionVersion = subscriptions.version(session.id)
                streams[session.id] = Task {
                    defer { self.streams[session.id] = nil }
                    do {
                        if monitor.responseStreamSupported {
                            try await AgentAPI.consumeSessionEvents(session.id, after: session.lastSessionEventSeq, recoveryVersion: ConversationCheckpoint.version(session.checkpointJSON)) { page in
                                try await self.consume(page, session: session, context: context)
                            }
                        } else {
                            let page = try await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/events?after_seq=\(session.lastSessionEventSeq)&recovery_version=\(ConversationCheckpoint.version(session.checkpointJSON))")
                            try await self.consume(page, session: session, context: context)
                        }
                        self.subscriptions.finish(session.id, version: subscriptionVersion)
                    } catch is CancellationError {
                        return
                    } catch {
                        guard (try? SessionDeletion.contains(session.id, context: context)) == false else { return }
                        session.syncError = HarnessAPIError.code(for: error)
                        if session.syncError == "RT.SESSION.UNKNOWN" {
                            do { try await ConversationProcessor.restoreCheckpoint(session, context: context) }
                            catch { session.syncError = HarnessAPIError.code(for: error) }
                        }
                        try? context.save()
                        self.subscriptions.refresh(session.id)
                    }
                }
            }
        }
    }

    private func consume(_ page: [String: Any], session: AgentSession, context: ModelContext) async throws {
        guard try !SessionDeletion.contains(session.id, context: context) else { return }
        var checkpoint: String?
        if let recovery = page["recovery"] as? [String: Any] {
            let savedCursor = session.lastSessionEventSeq
            let savedCheckpoint = session.checkpointJSON
            let cursor = max(savedCursor,
                             (page["events"] as? [[String: Any]] ?? []).compactMap { $0["seq"] as? Int }.max() ?? 0)
            checkpoint = try await ConversationCheckpoint.mergeOffMain(recovery, into: savedCheckpoint,
                                                                       sessionID: session.id, cursor: cursor)
            // A local stop/archive or checkpoint refresh may run while the
            // detached merge is in flight. Rebase inside the save if so.
            if session.lastSessionEventSeq != savedCursor || session.checkpointJSON != savedCheckpoint { checkpoint = nil }
        }
        // No suspension until all content, revisions and cursor are durable.
        do {
            if session.syncError != nil { session.syncError = nil }
            try ConversationProcessor.persist(page, session: session, context: context, premergedCheckpoint: checkpoint)
        } catch {
            context.rollback()
            throw error
        }
        let events = page["events"] as? [[String: Any]] ?? []
        if events.isEmpty || !events.allSatisfy({ $0["stage"] as? String == "response.delta" }) {
            respondToLookups(context: context)
        }
        ackTargets[session.id] = max(ackTargets[session.id] ?? 0, session.lastSessionEventSeq)
        scheduleACK(session.id)
        let active = page["has_running_run"] as? Bool ?? (page["runs"] as? [[String: Any]] ?? []).contains { ["running", "accepted"].contains($0["status"] as? String ?? "") }
        if page["recovery"] == nil && !active && snapshotters[session.id] == nil {
            snapshotters[session.id] = Task {
                defer { self.snapshotters[session.id] = nil }
                let lifecycle = session.lifecycleRevision
                guard let snapshot = try? await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/snapshot") else { return }
                guard (try? SessionDeletion.contains(session.id, context: context)) == false, session.lifecycleRevision == lifecycle,
                      let checkpoint = snapshot["checkpoint"] as? [String: Any],
                      (checkpoint["event_base_seq"] as? Int ?? 0) + (checkpoint["events"] as? [Any] ?? []).count >= session.lastSessionEventSeq,
                      (checkpoint["lifecycle_revision"] as? Int ?? 0) == lifecycle else { return }
                session.checkpointJSON = ConversationProcessor.json(snapshot)
                try? context.save()
            }
        }
    }

    private func respondToLookups(context: ModelContext, runs: [AgentRun]? = nil) {
        for run in runs ?? ((try? context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate { $0.status == "running" }))) ?? []) {
            guard run.status == "running", lookups[run.id] == nil,
                  let lookup = ConversationProcessor.object(run.memoryLookupJSON), lookup["state"] as? String == "pending",
                  let query = lookup["query"] as? String, let requestID = lookup["request_id"] as? String else { continue }
            lookups[run.id] = Task {
                defer { self.lookups[run.id] = nil }
                do {
                    guard try !SessionDeletion.contains(run.sessionID, context: context) else { return }
                    let candidates = try LearningMemory.candidates(for: query, excluding: run.sessionID, context: context)
                    _ = try await AgentAPI.conversationRequest("/v2/runs/\(run.id.uuidString.lowercased())/memory-results", body: [
                        "request_id": requestID, "revision": lookup["revision"] ?? run.revision,
                        "lifecycle_revision": lookup["lifecycle_revision"] ?? 0, "candidates": candidates])
                    guard try !SessionDeletion.contains(run.sessionID, context: context) else { return }
                    if ConversationProcessor.object(run.memoryLookupJSON)?["request_id"] as? String == requestID {
                        run.memoryLookupJSON = nil
                        try context.save()
                    }
                } catch {
                    if HarnessAPIError.code(for: error) == "RT.MEMORY.STALE_RESULT" { run.memoryLookupJSON = nil; try? context.save() }
                }
            }
        }
    }

    private func scheduleACK(_ id: UUID) {
        guard ackers[id] == nil, ackTargets[id] != nil else { return }
        ackers[id] = Task {
            defer { self.ackers[id] = nil }
            while let seq = self.ackTargets[id], !Task.isCancelled {
                do {
                    _ = try await AgentAPI.conversationRequest("/v2/sessions/\(id.uuidString.lowercased())/ack", body: ["last_event_seq": seq])
                    if self.ackTargets[id] == seq { self.ackTargets[id] = nil }
                } catch { return } // next wake retries the same durable cursor
            }
        }
    }
}

extension AgentAPI {
    @MainActor
    static func consumeSessionEvents(_ id: UUID, after: Int, recoveryVersion: Int = 0, endpoint: URL? = nil, receive: @MainActor ([String: Any]) async throws -> Void) async throws {
        try AppRuntime.current.requireSending()
        let url = URL(string: (endpoint ?? base).absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/v2/sessions/\(id.uuidString.lowercased())/events/stream?after_seq=\(after)&recovery_version=\(recoveryVersion)")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 30 // reset by SSE keepalives while generation is active
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else {
            throw HarnessAPIError.http((response as? HTTPURLResponse)?.statusCode ?? 0)
        }
        guard response.mimeType == "text/event-stream" else { throw HarnessAPIError.http(415) }
        let inbox = ConversationPageInbox()
        let (signals, signal) = AsyncStream<Void>.makeStream(bufferingPolicy: .bufferingNewest(1))
        let reader = Task.detached {
            do {
                for try await line in bytes.lines {
                    try Task.checkCancellation()
                    guard line.hasPrefix("data:") else { continue }
                    // Foundation omits SSE blank lines; each data line is a page.
                    let data = Data(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces).utf8)
                    await inbox.append(data)
                    // Stage and terminal pages should not wait for the next tick.
                    if let page = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        let events = page["events"] as? [[String: Any]] ?? []
                        if events.isEmpty || !events.allSatisfy({ $0["stage"] as? String == "response.delta" }) {
                            signal.yield(())
                        }
                    }
                }
                await inbox.finish()
            } catch {
                await inbox.finish(error)
            }
            signal.yield(())
        }
        let cadence = Task.detached {
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(80))
                if !Task.isCancelled { signal.yield(()) }
            }
        }
        defer { reader.cancel(); cadence.cancel(); signal.finish() }
        for await _ in signals {
            try Task.checkCancellation()
            let batch = await inbox.drain()
            var pending: [String: Any]?
            var deltas: [[String: Any]] = []
            func flush() async throws {
                guard var latest = pending else { return }
                latest["events"] = deltas
                pending = nil
                deltas.removeAll(keepingCapacity: true)
                try await receive(latest)
            }
            for data in batch.pages {
                guard let page = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                let events = page["events"] as? [[String: Any]] ?? []
                let deltaOnly = !events.isEmpty && events.allSatisfy { $0["stage"] as? String == "response.delta" }
                if deltaOnly {
                    var combined = page
                    if let old = pending?["recovery"] as? [String: Any],
                       let newer = page["recovery"] as? [String: Any] {
                        if newer["checkpoint"] != nil {
                            // A full checkpoint supersedes earlier deltas.
                        } else if old["checkpoint"] != nil {
                            // A full base plus later deltas must be saved in
                            // order; the wire format cannot carry both.
                            try await flush()
                        } else {
                            let earlier = old["deltas"] as? [[String: Any]] ?? []
                            let later = newer["deltas"] as? [[String: Any]] ?? []
                            combined["recovery"] = ["version": newer["version"] ?? 0,
                                                    "deltas": earlier + later]
                        }
                    }
                    pending = combined
                    deltas.append(contentsOf: events)
                } else {
                    try await flush()
                    try await receive(page)
                }
            }
            try await flush()
            if let failure = batch.failure { throw failure }
            if batch.finished { break }
        }
    }
}
