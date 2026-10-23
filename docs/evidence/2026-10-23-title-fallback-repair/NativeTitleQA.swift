import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

// Uses actual product title resolution and detail components, with a copied store.
// No service monitor, input route, synchronization or model adapter is constructed.
@main struct NativeTitleQA: App {
    let container: ModelContainer
    let cards: [Knowledge]
    init() {
        let root = Bundle.main.object(forInfoDictionaryKey: "QAStorePath") as! String
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", root, 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "18798", 1)
        precondition(AppRuntime.current.mode == .modelValidation)
        container = try! M1DebugFixture.makeValidationContainer(URL(fileURLWithPath: root))
        cards = try! container.mainContext.fetch(FetchDescriptor<Knowledge>()).sorted {
            if $0.title == "来源核对与适用条件核对" { return true }
            if $1.title == "来源核对与适用条件核对" { return false }
            return $0.title < $1.title
        }
        precondition(cards.count == 5 && cards.allSatisfy { !$0.participatesInReview })
        let titles = KnowledgeLexicon.resolvedTitles(for: cards)
        precondition(titles[cards[0].id] == "来源核对与适用条件核对")
        let report: [[String: String]] = cards.map {
            ["id": $0.id.uuidString, "title": $0.title, "goal": $0.learningGoal,
             "resolved_title": titles[$0.id]!, "version": String($0.version),
             "review": String($0.participatesInReview), "explanation": $0.explanation,
             "evidence": $0.evidenceExcerpt]
        }
        let data = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try! data.write(to: URL(fileURLWithPath: root + "/native-cards.json"))
        if ProcessInfo.processInfo.arguments.contains("--check") { print("PASS: copied five real cards; short title resolved; no service"); exit(0) }
    }
    var body: some Scene {
        WindowGroup("知识卡标题 · 隔离检查") {
            TitleRoot(cards: cards).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

struct TitleRoot: View {
    let cards: [Knowledge]
    @State private var showDetails = false
    @State private var dark = false
    @State private var index = 0
    @State private var coordinator = ReviewCoordinator()
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("留存真实卡片副本 · 只检查标题展示").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark).toggleStyle(.checkbox)
                Button("常规窗口") { resize(1040, 820) }
                Button("紧凑窗口") { resize(760, 680) }
            }.controlSize(.small).padding(12)
            if showDetails {
                KnowledgeDeckOverlay(items: cards, titles: KnowledgeLexicon.resolvedTitles(for: cards),
                    index: $index, coordinator: coordinator, onClose: { showDetails = false }, onAction: { _, _ in })
                    .environment(\.knowledgePaper, true)
            } else {
                List(Array(cards.enumerated()), id: \.element.id) { position, item in
                    Button(KnowledgeLexicon.keyword(for: item, among: cards)) {
                        index = position
                        showDetails = true
                    }.accessibilityIdentifier("actual-card-\(position)")
                }
            }
        }.frame(minWidth: 760, minHeight: 620)
            .background(RunwayPalette.brandMonochrome(dark: dark).canvas)
            .environment(\.runway, RunwayPalette.brandMonochrome(dark: dark))
            .environment(\.colorScheme, dark ? .dark : .light)
            .preferredColorScheme(dark ? .dark : .light)
            .environment(\.brandTrialStill, true)
    }
    private func resize(_ width: CGFloat, _ height: CGFloat) {
        (NSApp.keyWindow ?? NSApp.windows.first { $0.isVisible })?.setContentSize(NSSize(width: width, height: height))
    }
}
