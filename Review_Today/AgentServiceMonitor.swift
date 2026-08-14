import Foundation
import Observation

enum AgentConnectionState: Equatable {
    case unavailable
    case connecting
    case ready
}

struct HealthResponse: Decodable {
    let status: String
    let keyConfigured: Bool

    enum CodingKeys: String, CodingKey {
        case status
        case keyConfigured = "key_configured"
    }
}

@Observable
final class AgentServiceMonitor {
    private static let healthURL = URL(string: "http://127.0.0.1:8742/healthz")!
    private static let pollInterval: Duration = .seconds(2)
    private static let requestTimeout: TimeInterval = 1.5

    var connection: AgentConnectionState = .connecting
    var keyConfigured = false

    @ObservationIgnored
    private var pollTask: Task<Void, Never>?

    func start() {
        guard pollTask == nil else { return }
        connection = .connecting
        pollTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.ping()
                try? await Task.sleep(for: Self.pollInterval)
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func ping() async {
        var request = URLRequest(url: Self.healthURL)
        request.timeoutInterval = Self.requestTimeout
        request.cachePolicy = .reloadIgnoringLocalCacheData

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard
                let http = response as? HTTPURLResponse,
                http.statusCode == 200
            else {
                markUnavailable()
                return
            }
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            guard health.status == "ok" else {
                markUnavailable()
                return
            }
            connection = .ready
            keyConfigured = health.keyConfigured
        } catch {
            markUnavailable()
        }
    }

    private func markUnavailable() {
        connection = .unavailable
        keyConfigured = false
    }
}
