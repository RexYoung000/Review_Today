import AppKit
import SwiftUI

struct AnswerPreview: View {
    @State private var selected = 0
    @State private var width = 780.0
    @State private var dark = false
    @State private var draft = ""
    @State private var streamed: String?
    @State private var streamTask: Task<Void, Never>?
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Picker("样例", selection: $selected) {
                    ForEach(0..<AnswerReadabilitySamples.examples.count, id: \.self) { i in
                        Text(AnswerReadabilitySamples.examples[i].0).tag(i)
                    }
                }.frame(width: 210)
                Picker("正文宽度", selection: $width) {
                    Text("窄 340").tag(340.0)
                    Text("中 580").tag(580.0)
                    Text("宽 780").tag(780.0)
                }.frame(width: 180)
                Toggle("深色", isOn: $dark)
                Button(streamTask == nil ? "预览流式" : "停止") {
                    if let streamTask { streamTask.cancel(); self.streamTask = nil; return }
                    streamed = ""
                    let text = AnswerReadabilitySamples.examples[selected].1
                    streamTask = Task { @MainActor in
                        for char in text {
                            guard !Task.isCancelled else { return }
                            streamed?.append(char)
                            try? await Task.sleep(for: .milliseconds(12))
                        }
                        streamTask = nil
                    }
                }
            }.padding(14)
            Divider()
            ScrollView {
                LearningAnswerText(content: streamed ?? AnswerReadabilitySamples.examples[selected].1, availableWidth: width)
                    .foregroundStyle(dark ? RunwayPalette.dark.ink : RunwayPalette.light.ink)
                    .frame(width: width).padding(24).frame(maxWidth: .infinity)
            }
            Divider()
            TextField("可在这里输入，检查流式时的焦点", text: $draft).textFieldStyle(.roundedBorder).padding(14)
        }
        .background(dark ? RunwayPalette.dark.canvas : RunwayPalette.light.canvas)
        .environment(\.runway, dark ? .dark : .light)
        .preferredColorScheme(dark ? .dark : .light)
        .onChange(of: selected) { _, _ in streamTask?.cancel(); streamTask = nil; streamed = nil }
        .onDisappear { streamTask?.cancel() }
    }
}

@main
struct AnswerRenderingPreview {
    @MainActor static func main() throws {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出排版验收", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        menu.addItem(editItem)
        application.mainMenu = menu
        if CommandLine.arguments.count > 1 {
            let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            for dark in [false, true] {
                for width in [340.0, 580.0, 780.0] {
                    let palette = dark ? RunwayPalette.dark : .light
                    let view = LearningAnswerText(content: AnswerReadabilitySamples.lesson, availableWidth: width)
                        .foregroundStyle(palette.ink).frame(width: width).padding(24)
                        .background(palette.canvas).environment(\.runway, palette)
                        .environment(\.colorScheme, dark ? .dark : .light)
                    let host = NSHostingView(rootView: view)
                    host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                    let size = host.fittingSize
                    precondition(size.width <= width + 49, "Native content must fit the specified width")
                    host.frame = CGRect(origin: .zero, size: size)
                    host.layoutSubtreeIfNeeded()
                    guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { fatalError("No native bitmap") }
                    host.cacheDisplay(in: host.bounds, to: bitmap)
                    let name = "rag-\(Int(width))-\(dark ? "dark" : "light").png"
                    try bitmap.representation(using: .png, properties: [:])!.write(to: directory.appendingPathComponent(name))
                    print("\(name): \(Int(size.width)) × \(Int(size.height)) pt")
                }
            }
            return
        }
        let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 900, height: 850),
                              styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Review Today · 正文排版验收（固定样例）"
        window.contentView = NSHostingView(rootView: AnswerPreview())
        window.makeKeyAndOrderFront(nil)
        application.activate(ignoringOtherApps: true)
        application.run()
    }
}
