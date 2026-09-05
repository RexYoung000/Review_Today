import Foundation
import SwiftData

/// One outbox owner and one event consumer per Session. Network suspension never
/// delays editor input, and the legacy capture/review loop cannot hold this queue.
@MainActor
final class ConversationSync {
    private static let wakeName = Notification.Name("ReviewTodayConversationWake")
    static func wake() { NotificationCenter.default.post(name: wakeName, object: nil) }

    private var streams: [UUID: Task<Void, Never>] = [:]
    private var synced = Set<UUID>()
    private var senders: [UUID: Task<Void, Never>] = [:]
    private var controllers: [UUID: Task<Void, Never>] = [:]
    private var ackTargets: [UUID: Int] = [:]
    private var ackers: [UUID: Task<Void, Never>] = [:]
    private var snapshotters: [UUID: Task<Void, Never>] = [:]

    func run(context: ModelContext, monitor: AgentServiceMonitor) async {
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
            let sessions = (try? context.fetch(FetchDescriptor<AgentSession>())) ?? []
            for session in sessions {
                if controllers[session.id] == nil {
                    controllers[session.id] = Task {
                        defer { self.controllers[session.id] = nil }
                        await ConversationProcessor.tick(context: context, monitor: monitor, pollEvents: false, onlySession: session.id, controlsOnly: true)
                    }
                }
                if senders[session.id] == nil && session.status == "active" {
                    senders[session.id] = Task {
                        defer { self.senders[session.id] = nil }
                        await ConversationProcessor.tick(context: context, monitor: monitor, pollEvents: false, onlySession: session.id, skipControls: true)
                    }
                }
                scheduleACK(session.id)
            }
            let runs = (try? context.fetch(FetchDescriptor<AgentRun>())) ?? []
            for session in sessions where runs.contains(where: { $0.sessionID == session.id }) {
                let active = runs.contains { $0.sessionID == session.id && (["accepted", "running", "stopping", "adjusting"].contains($0.status) || ($0.status == "queued" && !session.runPaused)) }
                guard streams[session.id] == nil, active || !synced.contains(session.id) else { continue }
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
                        self.synced.insert(session.id)
                    } catch is CancellationError {
                        return
                    } catch {
                        session.syncError = HarnessAPIError.code(for: error)
                        if session.syncError == "RT.SESSION.UNKNOWN" {
                            do { try await ConversationProcessor.restoreCheckpoint(session, context: context) }
                            catch { session.syncError = HarnessAPIError.code(for: error) }
                        }
                        try? context.save()
                        self.synced.remove(session.id)
                    }
                }
            }
        }
    }

    private func consume(_ page: [String: Any], session: AgentSession, context: ModelContext) async throws {
        // No suspension until all content, revisions and cursor are durable.
        do {
            try ConversationProcessor.persist(page, session: session, context: context)
            session.syncError = nil
            try context.save()
        } catch {
            context.rollback()
            throw error
        }
        ackTargets[session.id] = max(ackTargets[session.id] ?? 0, session.lastSessionEventSeq)
        scheduleACK(session.id)
        let active = (page["runs"] as? [[String: Any]] ?? []).contains { ["running", "accepted"].contains($0["status"] as? String ?? "") }
        if page["recovery"] == nil && !active && snapshotters[session.id] == nil {
            snapshotters[session.id] = Task {
                defer { self.snapshotters[session.id] = nil }
                let lifecycle = session.lifecycleRevision
                guard let snapshot = try? await AgentAPI.conversationRequest("/v2/sessions/\(session.id.uuidString.lowercased())/snapshot") else { return }
                guard session.lifecycleRevision == lifecycle,
                      let checkpoint = snapshot["checkpoint"] as? [String: Any],
                      (checkpoint["event_base_seq"] as? Int ?? 0) + (checkpoint["events"] as? [Any] ?? []).count >= session.lastSessionEventSeq,
                      (checkpoint["lifecycle_revision"] as? Int ?? 0) == lifecycle else { return }
                session.checkpointJSON = ConversationProcessor.json(snapshot)
                try? context.save()
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
        let url = URL(string: (endpoint ?? base).absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/v2/sessions/\(id.uuidString.lowercased())/events/stream?after_seq=\(after)&recovery_version=\(recoveryVersion)")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 30 // reset by SSE keepalives while generation is active
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else {
            throw HarnessAPIError.http((response as? HTTPURLResponse)?.statusCode ?? 0)
        }
        guard response.mimeType == "text/event-stream" else { throw HarnessAPIError.http(415) }
        for try await line in bytes.lines {
            try Task.checkCancellation()
            if line.hasPrefix("data:") {
                // Our service emits exactly one compact JSON data line per event.
                // Foundation's AsyncLineSequence omits empty separator lines, so
                // waiting for a blank line would buffer every event until EOF.
                let data = Data(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces).utf8)
                if let page = try JSONSerialization.jsonObject(with: data) as? [String: Any] { try await receive(page) }
            }
        }
    }
}
