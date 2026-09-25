import SwiftData
import SwiftUI

private enum SettingsPage: String, CaseIterable, Identifiable {
    case general = "通用", review = "复习与提醒", data = "数据管理", advanced = "高级"
    var id: String { rawValue }
    var symbol: String {
        switch self { case .general: "slider.horizontal.3"; case .review: "clock.arrow.circlepath"; case .data: "externaldrive"; case .advanced: "wrench.and.screwdriver" }
    }
    var subtitle: String {
        switch self {
        case .general: "让 Review Today 更适合你的使用习惯。"
        case .review: "安排下一次回顾，让学过的留得更久。"
        case .data: "管理这台设备上的学习内容与复习记录。"
        case .advanced: "查看运行情况与开发工具。"
        }
    }
}

struct SettingsView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.runway) private var runway
    @Environment(\.brandReduceMotion) private var reduced
    @Query private var rows: [AppSettings]
    @State private var page: SettingsPage = .general
    @State private var error: String?
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 28) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("设置").font(.system(size: 22, weight: .bold))
                    Text("Review Today").font(.caption).foregroundStyle(.secondary)
                }.padding(.horizontal, 12)
                VStack(spacing: 6) {
                    ForEach(SettingsPage.allCases) { item in
                        Button {
                            withAnimation(reduced ? nil : .easeOut(duration: 0.12)) { page = item }
                        } label: {
                            HStack(spacing: 10) {
                                Image(systemName: item.symbol).frame(width: 20)
                                Text(item.rawValue).fontWeight(page == item ? .semibold : .regular)
                                Spacer(minLength: 0)
                            }.font(.system(size: 14)).padding(.horizontal, 12).frame(height: 42)
                        }.buttonStyle(InteractionButtonStyle(selected: page == item, padding: 0))
                            .accessibilityAddTraits(page == item ? .isSelected : [])
                    }
                }
                Spacer()
                Text("把理解留住。 ").font(.caption).foregroundStyle(.secondary).padding(.horizontal, 12)
            }.padding(20).frame(width: 208).background(runway.field.opacity(0.48))
            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(page.rawValue).font(.system(size: 25, weight: .bold)).accessibilityAddTraits(.isHeader)
                    Text(page.subtitle).font(.callout).foregroundStyle(.secondary)
                }.padding(28).frame(maxWidth: .infinity, alignment: .leading)
                if let settings = rows.first {
                    ScrollView {
                        SettingsPageContent(settings: settings, page: page)
                            .padding(.horizontal, 28).padding(.bottom, 28)
                            .frame(maxWidth: 680, alignment: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }.id(page).transition(.opacity)
                } else { ProgressView().task { seed() }; Spacer() }
                if let error { Text(error).font(.callout).foregroundStyle(.red).padding(28) }
            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(runway.card)
        }.frame(minWidth: 780, idealWidth: 900, minHeight: 580, idealHeight: 660)
            .foregroundStyle(runway.ink)
    }
    private func seed() {
        guard rows.isEmpty else { return }
        context.insert(AppSettings())
        do { try context.save() } catch { context.rollback(); self.error = "设置暂时无法载入，请重新打开。" }
    }
}

private struct SettingsPageContent: View {
    @Bindable var settings: AppSettings
    let page: SettingsPage
    @Environment(\.modelContext) private var context
    @Environment(\.runway) private var runway
    @Environment(\.openWindow) private var openWindow
    @State private var impact: LocalResetImpact?
    @State private var error: String?
    @State private var success: String?
    @State private var archived = false
    @State private var logs = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            switch page {
            case .general:
                group("外观与语言") {
                    row("外观", "切换浅色与深色，沿用应用的纸面质感。") { AnimatedThemeToggler() }
                    row("复习语言", "选择复习时使用的语言。") {
                        Picker("复习语言", selection: $settings.reviewLanguageOverride) {
                            Text("系统默认").tag("system"); Text("中文").tag("zh"); Text("目标语言").tag("target")
                        }.labelsHidden().frame(width: 132)
                    }
                }
            case .review:
                group("复习安排") {
                    row("默认目标", "每轮开始前仍可以调整。") {
                        Picker("默认复习目标", selection: $settings.reviewGoal) {
                            Text("全部到期").tag("due"); Text("按时长").tag("minutes"); Text("按数量").tag("count")
                        }.labelsHidden().frame(width: 132)
                    }
                    if settings.reviewGoal != "due" {
                        row(settings.reviewGoal == "minutes" ? "复习时长" : "知识点数量", "时间结束后，处理完当前题再收尾。") {
                            Stepper(value: $settings.reviewGoalValue, in: 1...100) {
                                Text("\(settings.reviewGoalValue) \(settings.reviewGoal == "minutes" ? "分钟" : "个")").monospacedDigit()
                            }.frame(width: 125)
                        }
                    }
                }
                group("提醒") {
                    row("每日提醒", "通知是否允许由 macOS 系统设置管理。") {
                        DatePicker("每日提醒时间", selection: reminderBinding, displayedComponents: .hourAndMinute).labelsHidden().fixedSize()
                    }
                }
            case .data:
                group("会话") {
                    row("已归档聊天", "查看、恢复或删除已归档的会话。") {
                        Button("管理…") { archived = true }.buttonStyle(.bordered)
                    }
                }
                group("重新开始") {
                    resetRow(.progress, "保留资料与知识卡，清除作答记录和排期。已参与的知识可立即重新复习。")
                    resetRow(.all, "清除本实例的会话、资料、知识卡、待处理和复习记录。")
                }
                Text("模型、API Key 和偏好设置会保留。独立测试实例、手工备份及模型供应商保留的记录不在本次清理范围内。")
                    .font(.caption).foregroundStyle(.secondary).lineSpacing(3)
                if !LocalDataReset.cleanupJobs(settings).isEmpty || SessionDeletion.pendingCount(settings.sessionDeletionsJSON) > 0 {
                    Label("有临时文件或后台副本待清理，服务连接后会自动重试。", systemImage: "clock")
                        .font(.callout).foregroundStyle(.secondary)
                    Button("重试后台清理") {
                        Task { await SessionDeletion.cleanPending(context: context); await LocalDataReset.cleanPending(context: context) }
                    }.buttonStyle(.bordered)
                }
            case .advanced:
                group("开发工具") {
                    row("开发模式", "显示运行详情和测试工具。") {
                        Toggle("开发模式", isOn: $settings.developerMode).labelsHidden().toggleStyle(.switch)
                    }
                    if settings.developerMode {
                        row("Agent 运行记录", "检查任务的处理状态。") { Button("查看…") { logs = true }.buttonStyle(.bordered) }
#if DEBUG
                        row("已确认动效", "查看原生动效演示。") { Button("打开") { openWindow(id: "mascot-motion-preview") }.buttonStyle(.bordered) }
                        row("吉祥物实验", "独立的动画 POC 窗口。") { Button("打开") { openWindow(id: "mascot-animation-poc") }.buttonStyle(.bordered) }
#endif
                    }
                }
            }
            if let success { Label(success, systemImage: "checkmark.circle").font(.callout).foregroundStyle(runway.ink) }
            if let error { Label(error, systemImage: "exclamationmark.circle").font(.callout).foregroundStyle(.red).textSelection(.enabled) }
        }
        .sheet(item: $impact) { approved in
            LocalResetConfirmation(impact: approved) {
                do {
                    try LocalDataReset.perform(approved, context: context)
                    success = approved.kind == .progress ? "复习进度已重置，知识内容已保留。" : "本机学习数据已清除。"
                    error = nil; impact = nil
                } catch { self.error = error.localizedDescription; impact = nil }
            }
        }
        .sheet(isPresented: $archived) { NavigationStack { ArchivedConversations().toolbar { ToolbarItem { Button("完成") { archived = false } } } }.frame(minWidth: 680, minHeight: 500) }
        .sheet(isPresented: $logs) { NavigationStack { AgentRunLogView().toolbar { ToolbarItem { Button("完成") { logs = false } } } }.frame(minWidth: 680, minHeight: 500) }
    }
    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(.secondary).padding(.leading, 4)
            VStack(spacing: 4, content: content).padding(8)
                .background(runway.field.opacity(0.5), in: RoundedRectangle(cornerRadius: 18))
        }
    }
    private func row<Control: View>(_ title: String, _ detail: String, @ViewBuilder control: () -> Control) -> some View {
        HStack(alignment: .center, spacing: 20) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.system(size: 14, weight: .semibold))
                Text(detail).font(.system(size: 12)).foregroundStyle(.secondary).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
            }.frame(maxWidth: .infinity, alignment: .leading)
            control().controlSize(.regular)
        }.padding(14).frame(minHeight: 68)
    }
    private func resetRow(_ kind: LocalResetKind, _ detail: String) -> some View {
        row(kind.title, detail) {
            Button(kind == .progress ? "重置…" : "清空…", role: .destructive) {
                do { try LocalDataReset.ensureIdle(context); impact = try LocalDataReset.impact(kind, context: context); error = nil; success = nil }
                catch { self.error = error.localizedDescription }
            }.buttonStyle(.bordered).foregroundStyle(.red)
        }
    }
    private var reminderBinding: Binding<Date> {
        Binding(get: { Calendar.current.date(from: DateComponents(hour: settings.dailyReminderMinutes / 60, minute: settings.dailyReminderMinutes % 60)) ?? .now },
                set: { let p = Calendar.current.dateComponents([.hour, .minute], from: $0); settings.dailyReminderMinutes = (p.hour ?? 21) * 60 + (p.minute ?? 0) })
    }
}

private struct LocalResetConfirmation: View {
    let impact: LocalResetImpact
    let confirm: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var typed = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(impact.kind.title).font(.system(size: 22, weight: .bold))
            Text(impact.kind == .progress ? "将删除 \(impact.attempts) 条作答和 \(impact.rounds) 轮复习记录，并重置记忆排期。" : "将清除 \(impact.sessions) 个会话、\(impact.knowledge) 张知识卡，以及所有资料、待处理、作答和复习记录。")
                .fixedSize(horizontal: false, vertical: true).lineSpacing(4)
            Text(impact.kind == .progress ? "保留知识内容、聊天和复习参与状态；已参与的知识可立即重新复习。" : "模型、API Key 和偏好设置保留。")
                .font(.callout).foregroundStyle(.secondary)
            Text("此操作无法在 App 内撤销。打开的复习窗口将关闭。")
                .font(.callout).foregroundStyle(.secondary)
            if impact.kind == .all {
                TextField("输入“清空”以确认", text: $typed).textFieldStyle(.roundedBorder).accessibilityLabel("输入清空以确认")
            }
            HStack {
                Spacer()
                Button("取消", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button(impact.kind == .progress ? "确认重置" : "确认清空", role: .destructive, action: confirm)
                    .foregroundStyle(.red)
                    .disabled(impact.kind == .all && typed != "清空")
            }.controlSize(.large)
        }.padding(28).frame(width: 470)
    }
}
