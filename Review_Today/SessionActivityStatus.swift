import SwiftData
import SwiftUI

/// This identity boundary must not contain Query/DynamicProperty. SwiftUI may
/// update those before testing equality, even when navigation did not change
/// the row's session. The child still independently observes real data changes.
struct SessionActivityStatus: View {
    let sessionID: UUID
    let archived: Bool
    var body: some View {
        SessionStatusIdentity(sessionID: sessionID, archived: archived).equatable()
    }
}

private struct SessionStatusIdentity: View, Equatable {
    let sessionID: UUID
    let archived: Bool
    var body: some View { SessionActivityContent(sessionID: sessionID, archived: archived) }
}

private struct SessionActivityContent: View {
    let archived: Bool
    private let sessionID: UUID
    @Query private var runs: [AgentRun]
    @Query private var tasks: [LearningTask]
    init(sessionID: UUID, archived: Bool) {
        self.archived = archived
        self.sessionID = sessionID
        _runs = Query(SessionRecentRecords.run(sessionID))
        _tasks = Query(SessionRecentRecords.task(sessionID))
    }
    private var state: (symbol: String, label: String, problem: Bool) {
        guard !archived else { return ("archivebox", "已归档", false) }
        guard let run = runs.first else { return ("circle", "尚未运行", false) }
        if ["retryable_failed", "terminal_failed"].contains(run.status) { return ("exclamationmark.triangle", "运行失败", true) }
        if ["interrupted", "cancelled"].contains(run.status) { return ("pause.circle", "已停止", false) }
        if ["running", "accepted", "queued", "adjusting", "stopping"].contains(run.status) { return ("circle.dotted", run.userSummary, false) }
        if let task = tasks.first, task.status == "awaiting_user" {
            return ("bubble.left", task.requiredActionType == "submit_answer" ? "等待作答" : "可继续学习", false)
        }
        return ("circle", "", false)
    }
    var body: some View {
        let state = state
#if DEBUG
        let _ = SessionStatusDiagnostics.didRender?(sessionID, state.symbol, state.label)
#endif
        Group {
            if state.symbol == "circle" { Circle().fill(.secondary.opacity(0.4)).frame(width: 5, height: 5) }
            else { Image(systemName: state.symbol).help(state.label) }
        }.font(.caption).foregroundStyle(state.problem ? Color.orange : .secondary).frame(width: 13)
    }
}

enum SessionRecentRecords {
    static func run(_ id: UUID) -> FetchDescriptor<AgentRun> {
        var d = FetchDescriptor<AgentRun>(predicate: #Predicate { $0.sessionID == id }, sortBy: [SortDescriptor(\.updatedAt, order: .reverse)])
        d.fetchLimit = 1; return d
    }
    static func task(_ id: UUID, withPlan: Bool = false) -> FetchDescriptor<LearningTask> {
        var d = FetchDescriptor<LearningTask>(predicate: #Predicate { $0.sessionID == id && (!withPlan || $0.learningPlanJSON != nil) },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)])
        d.fetchLimit = 1; return d
    }
}

struct TodaySessionStatus: View {
    @Query private var runs: [AgentRun]
    @Query private var tasks: [LearningTask]
    @Query private var plans: [LearningTask]
    init(sessionID: UUID) {
        _runs = Query(SessionRecentRecords.run(sessionID))
        _tasks = Query(SessionRecentRecords.task(sessionID))
        _plans = Query(SessionRecentRecords.task(sessionID, withPlan: true))
    }
    private var label: String {
        if let task = plans.first,
           let plan = ConversationProcessor.object(task.learningPlanJSON),
           let steps = plan["steps"] as? [[String: Any]],
           let current = steps.first(where: { $0["id"] as? String == plan["current_step_id"] as? String }),
           let title = current["title"] as? String {
            return task.status == "completed" ? "查看本次学习小结" : "上次学到：" + title
        }
        return runs.first?.userSummary ?? tasks.first?.userSummary ?? "尚未开始任务"
    }
    var body: some View { Text(label) }
}

#if DEBUG
/// Native-host integration evidence; omitted from optimized performance QA and Release.
enum SessionStatusDiagnostics {
    static var didRender: ((UUID, String, String) -> Void)?
}
#endif
