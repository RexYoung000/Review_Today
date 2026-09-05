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
