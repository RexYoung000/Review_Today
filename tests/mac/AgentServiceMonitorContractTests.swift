import Foundation

@main
struct AgentServiceMonitorContractTests {
    static func main() {
        let startedAt = Date(timeIntervalSince1970: 1_000)
        var startup = AgentServiceStartup(startedAt: startedAt)
        precondition(!startup.shouldTerminate(at: startedAt.addingTimeInterval(35)), "cold startup must survive the old 30 second watchdog")
        precondition(startup.shouldTerminate(at: startedAt.addingTimeInterval(90)), "hung startup must still be bounded")
        startup.observeOutput("RT.STARTUP.INTERPRETER_READY\n")
        precondition(startup.stage == .imports)
        startup.observeOutput("RT.STARTUP.SERVICE_IMPORTED\n")
        precondition(startup.stage == .server)
        startup.observeOutput("RT.STARTUP.INTERPRETER_READY\n")
        precondition(startup.stage == .server, "late output cannot regress startup stage")
        startup.healthy(at: startedAt.addingTimeInterval(80))
        precondition(!startup.shouldTerminate(at: startedAt.addingTimeInterval(85)), "one failed poll must not kill a ready service")
        precondition(startup.shouldTerminate(at: startedAt.addingTimeInterval(90)), "sustained health loss should recover promptly")
        startup.healthy(at: startedAt.addingTimeInterval(89))
        precondition(!startup.shouldTerminate(at: startedAt.addingTimeInterval(95)), "health recovery resets the outage window")
        startup.terminationRequested = true
        precondition(!startup.shouldTerminate(at: startedAt.addingTimeInterval(200)), "terminate each process only once")
        precondition(AgentServiceStartup(startedAt: startedAt).stage == .interpreter, "each new attempt begins before interpreter initialization")
        print("PASS: 90s cold startup, 10s sustained outage, recovery resets timer, monotonic startup diagnostics, single termination")

        func role(_ model: String, _ status: String, _ error: String = "") -> HealthResponse.ModelRole {
            HealthResponse.ModelRole(model: model, status: status, error: error, streaming: nil)
        }

        let checking = AgentServiceMonitor.capabilityPresentation(
            checking: [role("router", "checking"), role("coach", "checking")],
            unavailable: [],
            totalRoleCount: 3,
            readyDetail: "由 App 托管本地服务"
        )
        precondition(checking.connection == .ready)
        precondition(checking.notice.isEmpty, "background probing must not occupy the conversation")

        let partial = AgentServiceMonitor.capabilityPresentation(
            checking: [],
            unavailable: [role("risk", "unavailable", "timeout")],
            totalRoleCount: 3,
            readyDetail: "已连接现有本地服务"
        )
        precondition(partial.connection == .ready)
        precondition(!partial.notice.isEmpty)

        let blocked = AgentServiceMonitor.capabilityPresentation(
            checking: [],
            unavailable: [role("router", "unavailable"), role("coach", "unavailable"), role("risk", "unavailable")],
            totalRoleCount: 3,
            readyDetail: ""
        )
        precondition(blocked.connection == .unavailable)
        precondition(blocked.notice.isEmpty)
        print("PASS: capability probing is background state; partial capability is compact; all unavailable blocks")
    }
}
