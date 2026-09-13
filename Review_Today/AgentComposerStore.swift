import Foundation
import SwiftData

enum AgentQuickStart: String, CaseIterable, Identifiable {
    case concept, material, organize, explore, compare, interview
    case jobDescription, prerequisites, examples, understanding, connections, learningPath
    var id: String { rawValue }
    var title: String {
        switch self {
        case .concept: String(localized: "弄懂概念")
        case .material: String(localized: "读懂资料")
        case .organize: String(localized: "梳理知识")
        case .explore: String(localized: "探索新主题")
        case .compare: String(localized: "辨析易混点")
        case .interview: String(localized: "攻克面试题")
        case .jobDescription: String(localized: "拆解 JD")
        case .prerequisites: String(localized: "补齐前置知识")
        case .examples: String(localized: "举例理解")
        case .understanding: String(localized: "检查理解")
        case .connections: String(localized: "关联已有知识")
        case .learningPath: String(localized: "规划学习路径")
        }
    }
    var symbol: String {
        switch self {
        case .concept: "lightbulb"
        case .material: "doc.text"
        case .organize: "point.3.connected.trianglepath.dotted"
        case .explore: "safari"
        case .compare: "arrow.left.arrow.right"
        case .interview: "bubble.left.and.text.bubble.right"
        case .jobDescription: "list.clipboard"
        case .prerequisites: "square.stack.3d.up"
        case .examples: "sparkle.magnifyingglass"
        case .understanding: "text.bubble"
        case .connections: "link"
        case .learningPath: "point.topleft.down.to.point.bottomright.curvepath"
        }
    }
    var detail: String {
        switch self {
        case .concept: String(localized: "从直观解释和例子开始，理解一个新概念。")
        case .material: String(localized: "拆解文章或公开链接，讲清重点和难点。")
        case .organize: String(localized: "整理零散内容，理清知识点之间的关系。")
        case .explore: String(localized: "明确学习目标，找到入门路径和合适材料。")
        case .compare: String(localized: "对比相近概念，弄清区别与适用场景。")
        case .interview: String(localized: "先理解答案，再通过独立作答和追问练习。")
        case .jobDescription: String(localized: "拆解岗位要求，找出优先准备的知识和问题。")
        case .prerequisites: String(localized: "找出卡住你的基础知识，从缺口开始补学。")
        case .examples: String(localized: "通过具体场景和反例，把抽象内容讲明白。")
        case .understanding: String(localized: "说说你的理解，找出遗漏与容易混淆的地方。")
        case .connections: String(localized: "联系学过的内容，用类比和差异加深理解。")
        case .learningPath: String(localized: "结合目标与基础，安排循序渐进的学习步骤。")
        }
    }
    var prompt: String {
        switch self {
        case .concept: "我想弄懂一个概念："
        case .material: "请帮我读懂这份资料："
        case .organize: "请帮我梳理下面的知识和它们的关系："
        case .explore: "我想探索一个新主题，请先帮我明确目标和入门方向："
        case .compare: "请帮我比较下面两个容易混淆的概念，说明区别和适用场景："
        case .interview: "请帮我攻克这道面试题，先解释答案，再带我练习："
        case .jobDescription: "请先拆解这份 JD 的能力要求和优先问题，等我选题后再展开学习："
        case .prerequisites: "我学习下面的内容时卡住了，请帮我找出需要补齐的前置知识："
        case .examples: "请用具体例子和一个反例帮我理解："
        case .understanding: "请检查我的理解，指出遗漏或错误，不要直接替我作答："
        case .connections: "请联系我允许使用的已有学习记录或知识卡，帮我理解这个新知识："
        case .learningPath: "请根据我的目标和现有基础，帮我规划学习路径："
        }
    }

    static let initial: [Self] = [.concept, .material, .organize, .explore, .compare, .interview]

    static func refreshed(after current: [Self]) -> [Self] {
        var next = Array(allCases.shuffled().prefix(6))
        if Set(next) == Set(current) { next = Array(allCases.filter { !current.contains($0) }.prefix(6)) }
        return next
    }
}

/// Session-local provenance only. Restored text is protected unless this editor
/// can prove it still owns the untouched template; none of this is model context.
struct QuickStartPrefill {
    private var untouchedTemplate: String?
    private var lastID: String?
    private var lastResult: String?

    mutating func userEdited() { untouchedTemplate = nil }

    mutating func apply(id: String, prompt: String, to text: String) -> String? {
        if lastID == id && lastResult == text { return nil }
        let replace = text.isEmpty || untouchedTemplate == text
        let next = replace ? prompt : text + (text.hasSuffix("\n") ? "" : "\n") + prompt
        untouchedTemplate = replace ? next : nil
        lastID = id
        lastResult = next
        return next
    }
}

@MainActor
enum AgentComposerStore {
    enum Failure: Error { case blankInput, inactiveSession }
    static func settings(_ context: ModelContext) throws -> AppSettings {
        if let row = try context.fetch(FetchDescriptor<AppSettings>()).first { return row }
        let row = AppSettings()
        context.insert(row)
        return row
    }

    static func prepare(_ context: ModelContext) throws -> AppSettings {
        let row = try settings(context)
        guard row.agentDraftID == nil else { return row }
        let previous = (row.agentDraftMessageID, row.agentDraftMode, row.agentDraftThinking)
        row.agentDraftID = UUID()
        row.agentDraftMessageID = UUID()
        row.agentDraftMode = "auto"
        row.agentDraftThinking = row.lastThinkingStrength
        do { try context.save() }
        catch {
            // An unsuccessful initialization must remain eligible for retry.
            row.agentDraftID = nil
            row.agentDraftMessageID = previous.0
            row.agentDraftMode = previous.1
            row.agentDraftThinking = previous.2
            throw error
        }
        return row
    }

    /// Explicit creation is local only; unsent text belongs to its session.
    static func createSession(context: ModelContext, save: (() throws -> Void)? = nil) throws -> AgentSession {
        let row = try settings(context)
        let session = AgentSession(title: "新会话")
        session.thinkingStrength = row.lastThinkingStrength
        context.insert(session)
        do {
            if let save { try save() } else { try context.save() }
            return session
        } catch { context.processPendingChanges(); context.rollback(); throw error }
    }

    static func sendInitial(_ text: String, in session: AgentSession, context: ModelContext,
                            runtime: AppRuntime? = nil, save: (() throws -> Void)? = nil) throws -> AgentMessage {
        try (runtime ?? .current).requireSending()
        let content = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { throw Failure.blankInput }
        guard session.status == "active" else { throw Failure.inactiveSession }
        let snapshot = (session.composerDraft, session.title, session.updatedAt)
        let message = AgentMessage(sessionID: session.id, role: "user", content: content,
                                   contentType: TodayView.firstURL(in: content) == nil ? "text" : "url")
        message.clientMessageID = message.id
        context.insert(message)
        session.composerDraft = ""
        if ["新会话", "新学习 Session"].contains(session.title) { session.title = String(content.prefix(28)) }
        session.updatedAt = .now
        do {
            if let save { try save() } else { try context.save() }
            return message
        } catch {
            context.processPendingChanges(); context.rollback()
            session.composerDraft = snapshot.0; session.title = snapshot.1; session.updatedAt = snapshot.2
            throw error
        }
    }

    @discardableResult
    static func preserveLandingDraft(context: ModelContext, save: (() throws -> Void)? = nil) throws -> AgentSession? {
        let row = try settings(context)
        guard !row.agentDraftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let snapshot = (row.agentDraftText, row.agentDraftID, row.agentDraftMessageID)
        let session = AgentSession(id: row.agentDraftID ?? UUID(), title: "新会话", modePreset: row.agentDraftMode)
        session.composerDraft = row.agentDraftText
        session.thinkingStrength = row.agentDraftThinking
        context.insert(session)
        row.agentDraftText = ""; row.agentDraftID = nil; row.agentDraftMessageID = nil
        do {
            if let save { try save() } else { try context.save() }
            return session
        } catch {
            context.processPendingChanges(); context.rollback()
            row.agentDraftText = snapshot.0; row.agentDraftID = snapshot.1; row.agentDraftMessageID = snapshot.2
            throw error
        }
    }

    /// One local transaction owns first message, Session and outbox. The unsent
    /// landing-page fallback creates a session only when no explicit session exists.
    static func sendFirst(_ text: String, context: ModelContext, runtime: AppRuntime? = nil, save: (() throws -> Void)? = nil) throws -> (AgentSession, AgentMessage) {
        try (runtime ?? .current).requireSending()
        let content = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { throw Failure.blankInput }
        let row = try prepare(context)
        let sid = row.agentDraftID!, mid = row.agentDraftMessageID!
        let draftSnapshot = (row.agentDraftText, row.agentDraftMode, row.agentDraftThinking)
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
        } catch {
            context.processPendingChanges(); context.rollback()
            // SwiftData may leave an already-observed model at its failed values.
            // Restore the visible draft as well as rolling back the persisted graph.
            row.agentDraftID = sid; row.agentDraftMessageID = mid
            row.agentDraftText = draftSnapshot.0; row.agentDraftMode = draftSnapshot.1; row.agentDraftThinking = draftSnapshot.2
            throw error
        }
    }
}

extension Notification.Name {
    static let prepareNewConversation = Notification.Name("reviewToday.prepareNewConversation")
}
