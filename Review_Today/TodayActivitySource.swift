import SwiftData
import SwiftUI
import Observation

/// Window-owned observation performs no query from a navigation-driven body.
struct TodayActivitySource: View {
    let cache: TodayActivityCache
    @Environment(\.modelContext) private var context
    @State private var observation = TodayActivityObservation()
    var body: some View {
        Color.clear.frame(width: 0, height: 0).accessibilityHidden(true)
            .task { observation.start(cache: cache, context: context) }
            .onDisappear { observation.stop() }
    }
}

@MainActor final class TodayActivityObservation {
    private weak var cache: TodayActivityCache?
    private var context: ModelContext?
    private var observers: [NSObjectProtocol] = []
    private var refreshTask: Task<Void, Never>?
    private var generation = 0
    private var membershipChanged = false
    private var runIDs: Set<UUID> = []
    private var attemptIDs: Set<UUID> = []

    func start(cache: TodayActivityCache, context: ModelContext) {
        guard self.context !== context || self.cache !== cache else { return }
        stop(); self.cache = cache; self.context = context
        observers.append(NotificationCenter.default.addObserver(forName: ModelContext.willSave, object: context, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.prepareSave() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: ModelContext.didSave, object: context, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                if self?.membershipChanged == true { self?.scheduleRefresh() }
            }
        })
        refresh()
    }

    func stop() {
        generation += 1
        refreshTask?.cancel(); refreshTask = nil
        observers.forEach(NotificationCenter.default.removeObserver); observers = []
        context = nil; cache = nil; membershipChanged = false
        runIDs = []; attemptIDs = []
    }
    deinit { observers.forEach(NotificationCenter.default.removeObserver) }

    private func prepareSave() {
        guard let context else { return }
        // Existing projected fields use Observation below. Membership changes
        // require a fetch, including a previously running activity completing.
        let membership = context.insertedModelsArray + context.deletedModelsArray
        if membership.contains(where: { $0 is AgentRun || $0 is ReviewAttempt || $0 is AgentSession || $0 is Knowledge }) {
            membershipChanged = true; return
        }
        for model in context.changedModelsArray {
            if let run = model as? AgentRun, !runIDs.contains(run.id),
               run.status == "completed", run.activityKind != nil, run.completedAt != nil {
                membershipChanged = true; return
            }
            if let attempt = model as? ReviewAttempt, !attemptIDs.contains(attempt.attemptId),
               attempt.mode != "preview", attempt.acked, !attempt.effectiveGrade.isEmpty, attempt.completedAt != nil {
                membershipChanged = true; return
            }
        }
    }

    private func scheduleRefresh() {
        guard refreshTask == nil, context != nil else { return }
        refreshTask = Task { @MainActor [weak self] in
            await Task.yield()
            guard !Task.isCancelled, let self else { return }
            self.refreshTask = nil
            self.refresh()
        }
    }

    private func refresh() {
        guard let context, let cache else { return }
        do {
            let runs = try context.fetch(FetchDescriptor<AgentRun>(predicate: #Predicate {
                $0.status == "completed" && $0.activityKind != nil && $0.completedAt != nil
            }))
            let attempts = try context.fetch(FetchDescriptor<ReviewAttempt>(predicate: #Predicate {
                $0.mode != "preview" && $0.acked && $0.effectiveGrade != "" && $0.completedAt != nil
            }))
            let sessions = try context.fetch(FetchDescriptor<AgentSession>())
            let knowledge = try context.fetch(FetchDescriptor<Knowledge>())
            generation += 1
            let current = generation
            let rows = withObservationTracking {
                TodayActivity.project(runs: runs, attempts: attempts, sessions: sessions, knowledge: knowledge)
            } onChange: { [weak self] in
                Task { @MainActor in
                    guard let self, self.generation == current else { return }
                    self.scheduleRefresh()
                }
            }
            runIDs = Set(runs.map(\.id)); attemptIDs = Set(attempts.map(\.attemptId))
            membershipChanged = false
#if DEBUG || PERFORMANCE_QA
            cache.sourceProjectionCount += 1
#endif
            if cache.sourceActivities != rows { cache.sourceActivities = rows }
        } catch {
            membershipChanged = true
            NSLog("Activity refresh deferred: %@", String(describing: error))
        }
    }
}
