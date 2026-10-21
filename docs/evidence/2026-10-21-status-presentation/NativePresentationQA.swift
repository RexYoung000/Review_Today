import AppKit
import SwiftUI
import SwiftData
@testable import ReviewTodayContractSupport

// Component verification only: no service monitor, synchronizer or input route.
@main struct NativePresentationQA: App {
    let container: ModelContainer
    let cards: [Knowledge]
    let reply: String
    init() {
        let root = Bundle.main.object(forInfoDictionaryKey: "QAStorePath") as! String
        setenv("REVIEW_TODAY_NATIVE_TEST_DIR", root, 1)
        setenv("REVIEW_TODAY_NATIVE_TEST_PORT", "18799", 1)
        precondition(AppRuntime.current.mode == .modelValidation)
        container = try! M1DebugFixture.makeValidationContainer(URL(fileURLWithPath: root))
        cards = try! container.mainContext.fetch(FetchDescriptor<Knowledge>()).sorted { $0.title < $1.title }
        precondition(cards.count == 4 && cards.allSatisfy { !$0.participatesInReview })
        reply = try! String(contentsOfFile: root + "/corrected-reply.txt", encoding: .utf8)
        if ProcessInfo.processInfo.arguments.contains("--check") {
            print("PASS: isolated native disk loads four actual cards and corrected reply; no service started")
            exit(0)
        }
    }
    var body: some Scene {
        WindowGroup("保存结果与来源标签 · 离线展示复验") {
            PresentationRoot(cards: cards, reply: reply).modelContainer(container).runwayAppearance()
        }.defaultSize(width: 1040, height: 820)
    }
}

struct PresentationRoot: View {
    let cards: [Knowledge]
    let reply: String
    @State private var showDetails = false
    @State private var dark = false
    @State private var paper = true
    @State private var index = 0
    @State private var coordinator = ReviewCoordinator()
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("离线组件复验 · 留存真实数据 · 无模型或网页调用").font(.caption)
                Spacer()
                Toggle("深色", isOn: $dark).toggleStyle(.checkbox)
                Toggle("纸面详情", isOn: $paper).toggleStyle(.checkbox)
                Button("常规窗口") { resize(1040, 820) }
                Button("紧凑窗口") { resize(760, 680) }
            }.controlSize(.small).padding(12)
            if showDetails {
                KnowledgeDeckOverlay(items: cards, titles: Dictionary(uniqueKeysWithValues: cards.map { ($0.id, $0.title) }),
                    index: $index, coordinator: coordinator, onClose: { showDetails = false }, onAction: { _, _ in })
                    .environment(\.knowledgePaper, paper)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        Text("刚才这次一共保存了几张知识卡，分别叫什么？").font(.body).foregroundStyle(.secondary)
                        LearningAnswerText(content: reply)
                        Button("查看知识卡来源") { showDetails = true }
                    }.padding(32).frame(maxWidth: 780, alignment: .leading).frame(maxWidth: .infinity, alignment: .leading)
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
