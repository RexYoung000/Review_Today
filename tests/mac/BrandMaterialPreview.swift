import AppKit
import SwiftData
import SwiftUI

struct BrandMaterialPreviewRoot: View {
    @Bindable private var appearance = AppearanceController.shared
    @State private var coordinator = ReviewCoordinator()
    @State private var trial = true
    @State private var still = false
    @State private var page = 0
    @Environment(\.accessibilityReduceMotion) private var systemReduced
    private var palette: RunwayPalette { trial ? .brandMonochrome(dark: appearance.isDark) : (appearance.isDark ? .dark : .light) }
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                Text("黑白材质对照").font(.callout.weight(.semibold))
                Picker("查看", selection: $page) { Text("界面").tag(0); Text("动效").tag(1); Text("控件").tag(2) }.pickerStyle(.segmented).frame(width: 210)
                Spacer(minLength: 0)
                Toggle("试作版", isOn: $trial)
                Toggle("减少动态效果", isOn: $still)
                Button(appearance.isDark ? "浅色" : "深色") { appearance.setDark(!appearance.isDark, screenPoint: nil, reduceMotion: true) }
            }.toggleStyle(.checkbox).font(.caption).padding(12).background(palette.card)
            Divider()
            Group {
                if page == 0 { ContentView(coordinator: coordinator) }
                else if page == 1 { BrandTrialMotionPanel() }
                else { BrandTrialControls() }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(palette.canvas)
            .environment(\.runway, palette)
            .environment(\.brandMaterialTrial, trial)
            .environment(\.brandTrialStill, still || systemReduced)
        }
        .tint(palette.agent)
        .environment(\.brandMaterialPreview, true)
        .environment(appearance).preferredColorScheme(appearance.isDark ? .dark : .light)
        .onAppear { appearance.applyAppKit() }
    }
}

struct BrandTrialMotionPanel: View {
    @State private var phase = MascotPhase.idle
    @State private var level = 0.65
    @State private var slow = false
    @Environment(\.runway) private var palette
    @Environment(\.brandReduceMotion) private var reduced
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("思考与语音 · 同一套材质").font(.title2.weight(.semibold))
                Text("模拟状态与声量，不开启麦克风，不发送消息。").foregroundStyle(palette.copy)
                HStack(spacing: 20) {
                    VStack {
                        MascotMotion(phase: phase == .thinking ? .thinking : .idle, reduced: reduced, rate: slow ? 0.5 : 1).frame(width: 190, height: 170)
                        HStack { RunMascotIndicator(active: phase == .thinking, reduced: reduced, color: palette.secondaryInformation); Text(phase == .thinking ? "正在思考" : "已停止").font(.caption) }
                    }
                    VStack {
                        MascotMotion(surface: .voice, phase: phase, level: level, reduced: reduced, rate: slow ? 0.5 : 1).frame(maxWidth: .infinity).frame(height: 190)
                        MascotMotion(surface: .voice, phase: phase, level: level, reduced: reduced, rate: slow ? 0.5 : 1).frame(width: 240, height: 90)
                        Text("语音：\(phase.title)").font(.caption)
                    }.frame(maxWidth: .infinity)
                }
                HStack { ForEach(MascotPhase.allCases, id: \.self) { item in Button(item.title) { phase = item }.buttonStyle(InteractionButtonStyle(selected: phase == item)) } }
                HStack { Text("模拟声量"); Slider(value: $level).accessibilityLabel("模拟声量"); Text("\(Int(level * 100))%").monospacedDigit() }
                Toggle("半速观察", isOn: $slow)
                Text("可切换四态、将声量降到零，或开启减少动态效果检查稳定反馈。每次演示最多 20 秒。").font(.caption).foregroundStyle(palette.copy)
            }.padding(28)
        }.foregroundStyle(palette.ink)
        .task(id: phase) { guard phase != .idle else { return }; try? await Task.sleep(for: .seconds(20)); if !Task.isCancelled { phase = .idle } }
    }
}

struct BrandTrialControls: View {
    @Environment(\.runway) private var p
    @State private var selected = false
    @State private var input = ""
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Text("框体、标签与知识卡").font(.title2.weight(.semibold))
                HStack(spacing: 24) {
                    BrandMark(size: 56)
                    ForEach([CoachPose.idle, .working, .waitYou], id: \.self) { pose in CoachMark(pose: pose, size: 56) }
                    Text("已确认 Logo 与旧角色入口").foregroundStyle(p.copy)
                }
                HStack { Button("选择项目") { selected.toggle() }.buttonStyle(InteractionButtonStyle(selected: selected)); Button("不可用") {}.disabled(true); RunwayPrimaryButton(title: "主要操作", action: {}) }
                TextField("点击检查输入焦点", text: $input).textFieldStyle(BrandMaterialTextFieldStyle())
                RunwayCard {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("RAG：检索与生成的边界").font(.headline)
                        Text("检索让模型获得相关资料，但还需要检查来源、权限和引用是否准确。").foregroundStyle(p.copy)
                        Text("知识整理").font(.caption).foregroundStyle(p.information).padding(6).background(p.decorativeAccent.opacity(0.1), in: Capsule())
                        HStack { ForEach(1..<5) { n in RoundedRectangle(cornerRadius: 3).fill(p.history.opacity(Double(n)*0.2)).frame(width: 26,height: 26) }; Text("历史进度").font(.caption).foregroundStyle(p.copy) }
                    }
                }
                LearningAnswerText(content: "> 普通引用、选中与活动反馈统一使用黑白明暗。\n\n- 已完成内容使用文字与形状表达。\n- 错误和警告保留语义色。", availableWidth: 640)
                HStack { Label("需要注意", systemImage: "exclamationmark.triangle").foregroundStyle(.orange); Label("删除", systemImage: "trash").foregroundStyle(.red) }
            }.frame(maxWidth: 720, alignment: .leading).padding(28).frame(maxWidth: .infinity)
        }.foregroundStyle(p.ink)
    }
}

@main
struct BrandMaterialPreviewApp: App {
    private let container: ModelContainer
    init() {
        setenv("REVIEW_TODAY_M1_UI_FIXTURE", "learning", 1)
        unsetenv("REVIEW_TODAY_NATIVE_TEST_DIR")
        precondition(Bundle.main.bundleIdentifier == "Rex.Review-Today.BrandMaterialPreview")
        precondition(AppRuntime.current.isPreview && !AppRuntime.current.allowsSending)
        do {
            container = try M1DebugFixture.makeContainer(mode: "learning")
            let context = container.mainContext
            let sessions = try context.fetch(FetchDescriptor<AgentSession>())
            if let lesson = sessions.first(where: { $0.title.contains("讲解中") }) {
                let id = lesson.id
                let messages = try context.fetch(FetchDescriptor<AgentMessage>(predicate: #Predicate { $0.sessionID == id }))
                messages.first(where: { $0.role == "assistant" })?.content = AnswerReadabilitySamples.lesson
                lesson.title = "RAG：理解检索与生成的边界"
                try context.save()
            }
        } catch { fatalError("Cannot create isolated brand preview: \(error)") }
    }
    var body: some Scene {
        WindowGroup("Review Today · 黑白材质对照") { BrandMaterialPreviewRoot().modelContainer(container) }
            .defaultSize(width: 1280,height: 820).windowResizability(.contentMinSize)
            .commands { CommandMenu("小样") {
                Button("默认窗口") { resize(1280,820) }.keyboardShortcut("1",modifiers:[.command,.option])
                Button("紧凑窗口") { resize(760,660) }.keyboardShortcut("2",modifiers:[.command,.option])
                Button("保存当前页面截图") { saveSnapshot() }.keyboardShortcut("s",modifiers:[.command,.option])
            } }
    }
    private func saveSnapshot() {
        guard let view = (NSApp.keyWindow ?? NSApp.windows.first(where: \.isVisible))?.contentView,
              let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { return }
        // This internal preview exports its own view; it never captures other apps.
        guard let projectRoot = Bundle.main.object(forInfoDictionaryKey: "PreviewProjectRoot") as? String else { return }
        let root = URL(fileURLWithPath: projectRoot)
        let folder = root.appendingPathComponent("brand/refresh-2026-09/monochrome-ui/evidence")
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try data.write(to: folder.appendingPathComponent("native-\(Int(Date().timeIntervalSince1970)).png"))
        } catch { NSLog("Preview snapshot failed: %@", String(describing: error)) }
    }
    private func resize(_ w: CGFloat,_ h: CGFloat) {
        guard let win = NSApp.keyWindow ?? NSApp.windows.first(where: \.isVisible) else { return }
        win.setContentSize(NSSize(width:w,height:h));win.center()
    }
}
