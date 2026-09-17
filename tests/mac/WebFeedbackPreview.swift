import AppKit
import SwiftUI

struct WebFeedbackPreview: View {
    @State private var run = AgentRun(id: UUID(), sessionID: UUID())
    @State private var dark = false
    @State private var reduced = false
    @State private var narrow = false
    @State private var draft = ""
    @State private var phase = 0
    @State private var opened = ""
    private let stages = ["正在理解本轮意图", "正在检索公开资料", "正在读取网页正文", "正在核验回答依据", "正在准备回答"]
    private let answer = """
    **Harness** 是模型周围负责工具、上下文和执行流程的支撑系统。

    普通概念直接解释；需要核验时，先读取最相关资料，依据足够即可回答。

    ## 参考资料
    - [Python 官方教程：for 语句与列表遍历](https://docs.python.org/3/tutorial/controlflow.html#for-statements)
    - [一条较长的来源名称，用来检查窄窗口中文与 English 混排、折行及链接点击区域](https://docs.python.org/3/tutorial/)

    段落中的 [Python 文档](https://docs.python.org/3/) 同样可点击。文本 **加粗** 和 `代码` 保留。
    """
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("A011 隔离原生验证 · 阶段由按钮模拟").font(.caption).foregroundStyle(.secondary)
            HStack {
                Toggle("深色", isOn: $dark)
                Toggle("减少动态效果", isOn: $reduced)
                Toggle("窄窗", isOn: $narrow)
                Button("切换阶段") { phase = (phase + 1) % stages.count; run.userSummary = stages[phase] }
                Button(run.status == "running" ? "停止" : "开始") {
                    if run.status == "running" { run.elapsedMS = Int(Date.now.timeIntervalSince(run.startedAt!) * 1000); run.status = "stopped" }
                    else { run.startedAt = .now; run.status = "running"; run.userSummary = stages[phase] }
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    RunPhaseLine(run: run, reducedOverride: reduced)
                    RunDetails(run: run, reducedOverride: reduced) { Text("网页工具详细日志（隔离验证样例）").font(.caption) }
                    LearningAnswerText(content: answer, availableWidth: narrow ? 340 : 680)
                }.frame(width: narrow ? 340 : 680, alignment: .leading).padding(16)
                    .frame(maxWidth: .infinity)
            }
            Text(opened.isEmpty ? "点击来源后显示实际打开的 URL" : opened).font(.caption).textSelection(.enabled)
            TextField("输入内容，检查切换阶段是否抢焦点", text: $draft).textFieldStyle(.roundedBorder)
        }.padding(18)
            .foregroundStyle(dark ? RunwayPalette.dark.ink : RunwayPalette.light.ink)
            .background(dark ? RunwayPalette.dark.canvas : RunwayPalette.light.canvas)
            .environment(\.runway, dark ? .dark : .light)
            .preferredColorScheme(dark ? .dark : .light)
            .environment(\.openURL, OpenURLAction { url in opened = url.absoluteString; return .systemAction })
            .onAppear { run.status = "running"; run.startedAt = .now; run.userSummary = stages[phase] }
    }
}

@main
struct WebFeedbackPreviewApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let menu = NSMenu(), item = NSMenuItem(), submenu = NSMenu()
        submenu.addItem(withTitle: "退出验证", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = submenu; menu.addItem(item)
        let editItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit; menu.addItem(editItem); app.mainMenu = menu
        let window = NSWindow(contentRect: CGRect(x: 160, y: 130, width: 850, height: 740), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Review Today · 网页与运行反馈验证"
        window.contentView = NSHostingView(rootView: WebFeedbackPreview())
        window.makeKeyAndOrderFront(nil); app.activate(ignoringOtherApps: true); app.run()
    }
}
