import SwiftData
import SwiftUI
import UserNotifications

struct SessionTagEditor: View {
    @Bindable var session: AgentSession
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Query private var references: [KnowledgeReference]
    @Query private var knowledge: [Knowledge]
    @State private var tagsText: String

    init(session: AgentSession) {
        self.session = session
        _tagsText = State(initialValue: session.displayTopicTags.joined(separator: "，"))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("编辑会话标签").font(.headline)
            TextField("用逗号分隔，最多 5 个", text: $tagsText)
                .textFieldStyle(BrandMaterialTextFieldStyle())
            if !knowledgeTags.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("关联知识标签 · 只读").font(.caption.weight(.semibold))
                    Text(knowledgeTags.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            HStack {
                Button("恢复自动标签") {
                    session.restoreAutomaticTopicTags()
                    tagsText = session.automaticTopicTags.joined(separator: "，")
                    try? modelContext.save()
                }
                .disabled(session.manualTopicTags == nil)
                Spacer()
                Button("取消") { dismiss() }
                Button("保存") {
                    session.setManualTopicTags(parsedTags)
                    try? modelContext.save()
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 380)
    }

    private var parsedTags: [String] {
        tagsText.components(separatedBy: CharacterSet(charactersIn: "，,\n"))
    }

    private var knowledgeTags: [String] {
        let ids = Set(references.filter { $0.sessionID == session.id }.map(\.knowledgeID))
        return Array(Set(knowledge.filter { ids.contains($0.id) }.map(\.theme).filter { !$0.isEmpty })).sorted()
    }
}
