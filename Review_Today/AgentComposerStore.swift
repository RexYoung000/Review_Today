import Foundation
import SwiftData

enum AgentQuickStart: String, CaseIterable, Identifiable {
    case concept, material, organize, interview
    var id: String { rawValue }
    var title: String {
        switch self { case .concept: "弄懂概念"; case .material: "读懂资料"; case .organize: "梳理知识"; case .interview: "攻克面试题" }
    }
    var symbol: String {
        switch self { case .concept: "lightbulb"; case .material: "doc.text"; case .organize: "point.3.connected.trianglepath.dotted"; case .interview: "bubble.left.and.text.bubble.right" }
    }
    var prompt: String {
        switch self {
        case .concept: "我想弄懂一个概念："
        case .material: "请帮我读懂这份资料："
        case .organize: "请帮我梳理下面的知识和它们的关系："
        case .interview: "请帮我攻克这道面试题，先解释答案，再带我练习："
        }
    }
}

@MainActor
enum AgentComposerStore {
    enum Failure: Error { case blankInput }
    static func settings(_ context: ModelContext) throws -> AppSettings {
        if let row = try context.fetch(FetchDescriptor<AppSettings>()).first { return row }
        let row = AppSettings()
        context.insert(row)
        return row
    }

    static func prepare(_ context: ModelContext) throws -> AppSettings {
        let row = try settings(context)
        if row.agentDraftID == nil {
            row.agentDraftID = UUID()
            row.agentDraftMessageID = UUID()
            row.agentDraftMode = "auto"
            row.agentDraftThinking = row.lastThinkingStrength
        }
        try context.save()
        return row
    }

    /// One local transaction owns first message, Session and outbox. The unsent
    /// landing draft never appears as an empty Session in navigation or memory.
    static func sendFirst(_ text: String, context: ModelContext, save: (() throws -> Void)? = nil) throws -> (AgentSession, AgentMessage) {
        let content = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { throw Failure.blankInput }
        let row = try prepare(context)
        let sid = row.agentDraftID!, mid = row.agentDraftMessageID!
        do {
            let session = AgentSession(id: sid, title: String(content.prefix(28)), modePreset: row.agentDraftMode)
            session.thinkingStrength = row.agentDraftThinking
            let message = AgentMessage(id: mid, clientMessageID: mid, sessionID: sid, role: "user", content: content,
                                       contentType: TodayView.firstURL(in: content) == nil ? "text" : "url")
            context.insert(session); context.insert(message)
            row.agentDraftText = ""
            row.agentDraftID = nil
            row.agentDraftMessageID = nil
            row.agentDraftMode = "auto"
            row.agentDraftThinking = row.lastThinkingStrength
            if let save { try save() } else { try context.save() }
            return (session, message)
        } catch { context.rollback(); throw error }
    }
}
