import AppKit
import SwiftUI
import SwiftData

@MainActor @Observable
final class NavigationQA {
    var status = "就绪：测试使用独立数据库，不连接学习服务"
    var running = false
    let directory: URL
    let dataset: String
    init() {
        directory = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PerformanceDirectory") as! String)
        dataset = Bundle.main.object(forInfoDictionaryKey: "PerformanceDataset") as! String
    }
    func exportInteractions() {
        do {
            let record: [String: Any] = ["dataset": dataset, "navigation_and_menus": NavigationPerformance.rows,
                "activations": NavigationPerformance.activationRows,
                "boundary": "handler/activation notification to native draw; excludes OS input delivery and scanout"]
            try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
                .write(to: directory.appendingPathComponent("interactions.json"), options: .atomic)
            status = "菜单与窗口恢复记录已保存"
        } catch { status = "保存交互记录失败：\(error)" }
    }
    func runMenus() {
        guard !running else { return }
        running = true
        Task { @MainActor in
            NotificationCenter.default.post(name: NavigationPerformance.navigate, object: "learning")
            try? await Task.sleep(for: .seconds(1))
            NavigationPerformance.rows = []
            for title in ["添加材料", "学习方式", "思考强度"] {
                for index in 0..<31 {
                    status = "菜单绘制诊断：\(title) \(index + 1)/31（每条记录前台状态）"
                    let count = NavigationPerformance.completed
                    NotificationCenter.default.post(name: NavigationPerformance.menu, object: title, userInfo: ["open": true])
                    let started = ProcessInfo.processInfo.systemUptime
                    while NavigationPerformance.completed == count && ProcessInfo.processInfo.systemUptime - started < 10 {
                        try? await Task.sleep(for: .milliseconds(20))
                    }
                    NotificationCenter.default.post(name: NavigationPerformance.menu, object: title, userInfo: ["open": false])
                    guard NavigationPerformance.completed != count else {
                        status = "菜单绘制超时；保留已有交互记录"; exportInteractions(); running = false; return
                    }
                    try? await Task.sleep(for: .milliseconds(200))
                }
            }
            exportInteractions(); running = false
        }
    }
    func run(foregroundRequired: Bool = true) {
        guard !running else { return }
        running = true
        NSApp.activate(ignoringOtherApps: true)
        NSApp.windows.first(where: { $0.canBecomeMain })?.makeKeyAndOrderFront(nil)
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(300))
            guard NSApp.isActive || !foregroundRequired else { status = "请激活本窗口后再采样"; running = false; return }
            NavigationPerformance.rows = []
            for index in 0..<62 {
                status = "原生绘制采样 \(index + 1)/62"
                let count = NavigationPerformance.completed
                NotificationCenter.default.post(name: NavigationPerformance.navigate, object: index.isMultiple(of: 2) ? "today" : "learning")
                let started = ProcessInfo.processInfo.systemUptime
                while NavigationPerformance.completed == count && ProcessInfo.processInfo.systemUptime - started < 120 {
                    try? await Task.sleep(for: .milliseconds(20))
                }
                if NavigationPerformance.completed == count { status = "未收到目标页面绘制，采样中止"; running = false; return }
                try? await Task.sleep(for: .milliseconds(200))
            }
            do {
                let record: [String: Any] = ["dataset": dataset, "boundary": "selection handler to AppKit draw; not physical scanout",
                    "warmup_rows": 2, "foreground_required": foregroundRequired, "rows": NavigationPerformance.rows]
                let data = try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
                try data.write(to: directory.appendingPathComponent(foregroundRequired ? "navigation.json" : "navigation-background.json"), options: .atomic)
                status = "完成：60 条热切换记录已保存"
            } catch { status = "保存测量失败：\(error)" }
            running = false
        }
    }
}

@main
struct NavigationPerformanceQAApp: App {
    let container: ModelContainer
    @State private var qa = NavigationQA()
    @State private var coordinator = ReviewCoordinator()
    init() {
        precondition(AppRuntime.current.isPreview && !AppRuntime.current.allowsSending)
        let directory = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "PerformanceDirectory") as! String)
        let stress = Bundle.main.object(forInfoDictionaryKey: "PerformanceDataset") as! String == "stress"
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            container = try M1DebugFixture.makeValidationContainer(directory)
            let c = container.mainContext
            if try c.fetchCount(FetchDescriptor<AppSettings>()) == 0 {
                c.insert(AppSettings())
                var sessions: [AgentSession] = []
                for index in 0..<(stress ? 300 : 3) {
                    let s = AgentSession(title: "隔离会话 \(index + 1)"); c.insert(s); sessions.append(s)
                }
                for index in 0..<(stress ? 1000 : 8) {
                    c.insert(Knowledge(learningGoal: "解释概念 \(index)", knowledgeType: "concept", theme: "性能验收",
                        contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "隔离样例",
                        evidenceLocator: "fixture", title: "知识 \(index)", explanation: "相同的固定样例，不是用户数据。"))
                }
                if stress {
                    for index in 0..<10000 {
                        c.insert(AgentMessage(sessionID: sessions[index % sessions.count].id, role: index.isMultiple(of: 2) ? "user" : "assistant",
                            content: "固定历史消息 \(index)：保留输入、响应与会话归属。", deliveryStatus: "completed"))
                    }
                    for index in 0..<5000 {
                        let run = AgentRun(id: UUID(), sessionID: sessions[index % sessions.count].id)
                        run.status = "completed"; run.activityKind = "knowledge_answer"
                        run.completedAt = Calendar.current.date(byAdding: .day, value: -(index % 360), to: .now)
                        c.insert(run)
                    }
                }
                try c.save()
            }
        } catch { fatalError("Isolated performance fixture failed: \(error)") }
    }
    var body: some Scene {
        WindowGroup("Review Today · 性能隔离验收", id: "main") {
            ContentView(coordinator: coordinator).modelContainer(container).runwayAppearance()
                .background(ActivationPaintProbe().allowsHitTesting(false).accessibilityHidden(true))
                .safeAreaInset(edge: .bottom) {
                    HStack { Text(qa.status); Spacer(); Button("运行 30 轮切页采样") { qa.run() }.disabled(qa.running) }
                        .font(.caption).padding(6)
                }
        }.windowStyle(.hiddenTitleBar).defaultSize(width: 1280, height: 820).windowResizability(.contentMinSize)
        .commands {
            CommandMenu("性能验收") {
                Button("保存菜单与窗口恢复记录") { qa.exportInteractions() }.disabled(qa.running)
                Button("运行菜单绘制诊断（含前台标记）") { qa.runMenus() }.disabled(qa.running)
                Button("运行后台绘制诊断（不作前台验收）") { qa.run(foregroundRequired: false) }.disabled(qa.running)
                Button("运行 30 轮切页采样") { qa.run() }.keyboardShortcut("r", modifiers: [.command, .option]).disabled(qa.running)
            }
        }
    }
}
