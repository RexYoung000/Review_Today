import Foundation

@main
struct AgentServiceMonitorContractTests {
    static func main() {
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
