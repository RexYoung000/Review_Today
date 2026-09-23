import SwiftData
import SwiftUI

struct RecentLearningDetail: View {
    let session: AgentSession
    let back: () -> Void
    let resume: () -> Void
    @Query private var messages: [AgentMessage]
    init(session: AgentSession, back: @escaping () -> Void, resume: @escaping () -> Void) {
        self.session = session; self.back = back; self.resume = resume
        let id = session.id
        _messages = Query(filter: #Predicate<AgentMessage> { $0.sessionID == id }, sort: \AgentMessage.createdAt, order: .reverse)
    }
    private var excerpt: String {
        if !session.summaryText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return session.summaryText }
        return messages.first { $0.role == "assistant" && $0.responseState == "complete" && !$0.content.isEmpty }?.content ?? "这段会话还没有完成的回复，可以回到原会话继续。"
    }
    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack { ReviewActionButton(title: "最近学习", symbol: "chevron.left", action: back); Spacer() }
                    VStack(alignment: .leading, spacing: 12) {
                        if !session.displayTopicTags.isEmpty { Text(session.displayTopicTags.joined(separator: " · ")).font(.callout).foregroundStyle(.secondary) }
                        Text(session.title).font(.system(size: 30, weight: .bold)).fixedSize(horizontal: false, vertical: true)
                        HStack(spacing: 12) {
                            MetaTag(title: LearningWorkspace.modeLabel(session.modePreset))
                            Text(session.updatedAt, format: .dateTime.month().day().hour().minute()).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if geometry.size.width >= 820 {
                        HStack(alignment: .top, spacing: 20) { note; continuation.frame(width: 255) }
                    } else { continuation; note }
                }.padding(28).frame(maxWidth: 960).frame(maxWidth: .infinity)
            }
        }
    }
    private var note: some View {
        RunwayCard(padding: 28) {
            VStack(alignment: .leading, spacing: 22) {
                Label(session.summaryText.isEmpty ? "最近一段回复" : "上次的摘记", systemImage: "text.book.closed").font(.callout.weight(.medium))
                Text(excerpt).font(.body).lineSpacing(7).textSelection(.enabled).fixedSize(horizontal: false, vertical: true).id(excerpt)
                Text("保留原会话内容，可回到对话查看完整记录。").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    private var continuation: some View {
        RunwayCard(padding: 24) {
            VStack(alignment: .leading, spacing: 16) {
                Label("从这里继续", systemImage: "arrow.turn.down.right").font(.callout.weight(.medium))
                TodaySessionStatus(sessionID: session.id).font(.headline).fixedSize(horizontal: false, vertical: true)
                Text("回到原来的对话，继续追问或整理值得记住的内容。").font(.callout).foregroundStyle(.secondary).lineSpacing(5)
                ReviewStartButton(title: "继续学习", action: resume)
            }
        }
    }
}
