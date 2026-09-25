#if canImport(ReviewTodayContractSupport)
@testable import ReviewTodayContractSupport
#endif
import SwiftUI
import SwiftData

@main struct SettingsPreview: App {
    let container: ModelContainer
    init() {
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "1", 1)
        container = try! ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(isStoredInMemoryOnly: true))
        let c = container.mainContext
        c.insert(AppSettings())
        let source = Source(rawText: "合成资料"); c.insert(source)
        let card = Knowledge(learningGoal: "光合作用", knowledgeType: "concept", theme: "合成样例", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "合成证据", evidenceLocator: "")
        card.reviewEnrollment = "enrolled"; card.source = source; c.insert(card)
        c.insert(FsrsState(knowledgeId: card.id, dueAt: .now))
        let session = AgentSession(title: "合成会话", status: "archived"); c.insert(session)
        let round = ReviewSession(mode: "formal", snapshotJSON: ""); round.endedAt = .now; c.insert(round)
        let attempt = ReviewAttempt(sessionId: round.id, knowledgeId: card.id, knowledgeVersion: 1, questionId: UUID(), mode: "formal")
        attempt.reviewState = "completed"; c.insert(attempt)
        try! c.save()
    }
    var body: some Scene {
        WindowGroup("设置 · 隔离验证") {
            SettingsView().modelContainer(container).runwayAppearance()
                .safeAreaInset(edge: .bottom) { Text("隔离合成数据 · 不连接模型 · 重新打开恢复样例").font(.caption).padding(8) }
        }.defaultSize(width: 900, height: 660)
    }
}
