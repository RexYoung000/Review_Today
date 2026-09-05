import SwiftData
import SwiftUI

struct ComposerKnowledgePicker: View {
    var onSelect: (Knowledge) -> Void
    @Environment(\.dismiss) private var dismiss
    @Query private var cards: [Knowledge]
    @State private var search = ""

    private var matching: [Knowledge] {
        cards.filter { $0.lifecycle == "active" && (search.isEmpty || ($0.title + $0.learningGoal + $0.theme).localizedCaseInsensitiveContains(search)) }
            .sorted { $0.createdAt > $1.createdAt }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack { Text("引用已有知识卡").font(.headline); Spacer(); Button("完成") { dismiss() } }
            TextField("搜索知识", text: $search).textFieldStyle(.roundedBorder)
            Text("只将引用插入草稿，不发送、不修改知识与复习记录。").font(.caption).foregroundStyle(.secondary)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 4) {
                    if matching.isEmpty { Text("没有匹配的知识卡").foregroundStyle(.secondary).padding(.vertical, 24) }
                    ForEach(matching, id: \.id) { card in
                        Button { onSelect(card) } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(card.title.isEmpty ? card.learningGoal : card.title).font(.body)
                                if !card.theme.isEmpty { Text(card.theme).font(.caption).foregroundStyle(.secondary) }
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(10).contentShape(Rectangle())
                        }.buttonStyle(.plain)
                    }
                }
            }
        }.padding(20).frame(width: 460, height: 420)
    }
}
