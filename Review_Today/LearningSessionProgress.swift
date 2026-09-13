import SwiftData
import SwiftUI

struct LearningChecklist: View {
    let session: AgentSession?
    let tasks: [LearningTask]
    var onSelectMessage: (UUID?) -> Void
    @Environment(\.modelContext) private var modelContext
    @ViewBuilder
    var body: some View {
        if let session = session,
           let task = tasks.last(where: { $0.learningPlanJSON != nil }),
           let plan = ConversationProcessor.object(task.learningPlanJSON),
           let steps = plan["steps"] as? [[String: Any]], !steps.isEmpty {
            let current = steps.first { $0["id"] as? String == plan["current_step_id"] as? String }
            VStack(alignment: .leading, spacing: 8) {
                Button {
                    session.learningChecklistExpanded.toggle()
                    try? modelContext.save()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: session.learningChecklistExpanded ? "chevron.down" : "chevron.right")
                        Text(task.status == "completed" ? "本次学习已结束" : "学习安排").fontWeight(.medium)
                        Text(current?["title"] as? String ?? plan["goal"] as? String ?? "").foregroundStyle(.secondary).lineLimit(1)
                        Spacer(minLength: 0)
                    }.font(.callout).padding(.vertical, 5).contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityValue(session.learningChecklistExpanded ? "已展开" : "已收起")
                if session.learningChecklistExpanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                                let state = step["state"] as? String ?? "pending"
                                let understanding = step["understanding"] as? String ?? "unknown"
                                let label = understanding == "verified" ? "已验证" : understanding == "self_reported" ? "自述理解" : state == "skipped" ? "跳过检查" : state == "explained" ? "已讲解" : "待学习"
                                Button {
                                    if let raw = (step["message_ids"] as? [String])?.first { onSelectMessage(UUID(uuidString: raw)) }
                                } label: {
                                    HStack(alignment: .firstTextBaseline, spacing: 9) {
                                        Text("\(index + 1)").monospacedDigit().foregroundStyle(.secondary).frame(width: 18)
                                        Text(step["title"] as? String ?? "学习步骤").lineLimit(2)
                                        Spacer(minLength: 8)
                                        Text(label).font(.caption).foregroundStyle(.secondary)
                                    }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 5).contentShape(Rectangle())
                                }.buttonStyle(.plain)
                                    .disabled((step["message_ids"] as? [String] ?? []).isEmpty)
                                    .help("查看对应内容，不会改变理解状态")
                            }
                        }
                    }.frame(height: min(CGFloat(steps.count) * 38, 160))
                    Text("点击步骤回看内容；要调整安排，直接告诉我。").font(.caption2).foregroundStyle(.secondary)
                }
            }.padding(.bottom, 10)
        }
    }

}

struct LearningOutcome: View {
    let task: LearningTask
    let tasks: [LearningTask]
    @Environment(\.runway) private var runway
    @ViewBuilder
    var body: some View {
        if let outcome = ConversationProcessor.object(task.learningOutcomeJSON) {
            let verified = outcome["verified"] as? [String] ?? []
            let explained = outcome["explained"] as? [String] ?? []
            VStack(alignment: .leading, spacing: 8) {
                Text("本次学习小结").font(.headline)
                if !verified.isEmpty { Text("已验证：" + verified.joined(separator: "、")) }
                if !explained.isEmpty { Text("已讲解，仍可练习：" + explained.joined(separator: "、")) }
                if verified.isEmpty && explained.isEmpty { Text(task.understanding == "verified" ? "本次理解检查已通过。" : "内容已整理交付，尚未验证理解。") }
                Text(task.memoryCommitted || tasks.contains(where: { $0.memoryCommitted && $0.draftTargetID == task.id.uuidString.lowercased() }) ? "已加入知识库" : "学习成果已保留在会话中；入库由你决定。")
                    .font(.caption).foregroundStyle(.secondary)
            }.font(.callout).frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 12)
                .overlay(alignment: .top) { Rectangle().fill(runway.hairline).frame(height: 1) }
        }
    }

}
