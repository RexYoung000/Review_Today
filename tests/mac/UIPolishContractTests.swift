import AppKit
import SwiftUI
import SwiftData

@main
struct UIPolishContractTests {
    @MainActor static func main() throws {
        _ = NSApplication.shared
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 280), styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let host = NSView(frame: NSRect(x: 0, y: 0, width: 480, height: 280))
        let editor = LearningEditor(frame: NSRect(x: 20, y: 20, width: 300, height: 150))
        host.addSubview(editor); window.contentView = host
        editor.allowsUndo = true; editor.isRichText = false
        precondition(!editor.acceptsFirstResponder && !editor.becomeFirstResponder(), "automatic initial focus must be rejected")
        editor.requestFocus()
        precondition(window.firstResponder === editor, "explicit input intent may focus")
        editor.string = "保留原稿"; editor.setSelectedRange(NSRange(location: 1, length: 2))
        let outside = NSEvent.mouseEvent(with: .leftMouseDown, location: NSPoint(x: 450, y: 240), modifierFlags: [], timestamp: 1,
                                        windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1)!
        editor.observeInteraction(outside)
        precondition(window.firstResponder !== editor && editor.string == "保留原稿", "outside click releases focus without changing text")
        precondition(editor.selectedRange() == NSRange(location: 1, length: 2), "focus loss preserves selection data")
        editor.requestFocus(); editor.setEditingEnabled(false)
        precondition(window.firstResponder !== editor && !editor.becomeFirstResponder(), "recording lock cannot advertise editing focus")
        editor.setEditingEnabled(true)
        editor.queueInsertion(EditorInsertion(text: "追加", appendToEnd: true))
        editor.observeInteraction(outside)
        editor.applyPendingInsertion()
        precondition(editor.string == "保留原稿\n追加" && window.firstResponder !== editor, "late insertion may finish but not steal a newer click")
        editor.setEditingEnabled(false)
        editor.queueInsertion(EditorInsertion(text: "听写回填", appendToEnd: true)); editor.applyPendingInsertion()
        precondition(window.firstResponder !== editor)
        editor.setEditingEnabled(true)
        precondition(window.firstResponder === editor, "saved dictation regains focus after the editor unlocks")
        editor.setEditingEnabled(false)
        editor.queueInsertion(EditorInsertion(text: "延迟回填", appendToEnd: true)); editor.applyPendingInsertion()
        editor.observeInteraction(outside); editor.setEditingEnabled(true)
        precondition(window.firstResponder !== editor, "a newer click also wins over deferred unlock focus")
        editor.disposeFocusTracking(); window.close()

        func card(_ title: String, _ goal: String) -> Knowledge {
            Knowledge(learningGoal: goal, knowledgeType: "concept", theme: "RAG", contentLanguage: "zh", questionLanguage: "zh", answerLanguage: "zh", evidenceExcerpt: "", evidenceLocator: "", title: title)
        }
        let cases = [
            ("", "记住 RAG 工作流程的三个主要阶段。", "RAG 工作流程的三个主要阶段。"),
            ("", "说明 RAG 的检索与生成阶段分别做什么。", "RAG 的检索与生成阶段分别做什么。"),
            ("RAG 工作流程的三个", "记住 RAG 工作流程的三个主要阶段。", "RAG 工作流程的三个主要阶段。"),
            ("RAG 的检索与生成阶", "说明 RAG 的检索与生成阶段分别做什么。", "RAG 的检索与生成阶段分别做什么。"),
            ("Embedding model v2.1 与 top-k 检索", "解释术语", "Embedding model v2.1 与 top-k 检索"),
            ("矩阵的阶", "矩阵的阶数与维度", "矩阵的阶")
        ]
        for (title, goal, expected) in cases {
            let item = card(title, goal)
            precondition(KnowledgeLexicon.keyword(for: item) == expected, "full title: \(title)")
            precondition(item.title == title && item.learningGoal == goal, "display fallback cannot mutate knowledge")
        }
        let legacy = card("", "说明 RAG 的检索与生成阶段分别做什么。")
        precondition(KnowledgeLexicon.chipTitle(for: legacy, among: [legacy], theme: "检索增强生成（RAG）") == "检索与生成阶段分别做什么。")
        let prose = "准确性来自可核对的来源。内容仍需判断；省略号……也是原文。"
        precondition(KnowledgeLexicon.parse(prose) == [.paragraph(prose)], "prose, punctuation and ellipses must survive display parsing")
        let introduction = "下面是四项优势："
        precondition(KnowledgeLexicon.parse(introduction + "\n\n1. 准确性。\n2、成本效益。\n- 可核对来源。") == [
            .paragraph(introduction), .numbered(1, "准确性。"), .numbered(2, "成本效益。"), .bullet("可核对来源。")
        ], "an introduction must not acquire a duplicate list number")
        let repeated = Array(repeating: "相同原文段落。", count: 10)
        precondition(KnowledgeLexicon.parse(repeated.joined(separator: "\n\n")) == repeated.map(ExplanationPiece.paragraph), "long and repeated paragraphs must not be dropped")
        for text in ["3.14 是近似值。", "模型 v2.1 和 v3.2 的差异。", "第一步：检索。第二步：生成。", "前言：1. 原文项；2. 原文项。"] {
            precondition(KnowledgeLexicon.parse(text) == [.paragraph(text)], "inline prose must remain intact: \(text)")
        }
        precondition(KnowledgeLexicon.parse("7. 保留原编号。\r\n8) 保留句号。") == [.numbered(7, "保留原编号。"), .numbered(8, "保留句号。")])
        let config = MascotMotionConfiguration(ambient: true, idleClip: .readingAndLooking)
        let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(config)) as! [String: Any]
        precondition(json["idleClip"] as? String == "sidebar_loop")
        precondition(MascotMotionConfiguration().idleClip == .random, "existing ambient entry keeps its scheduler")
        let rect = CGRect(x: 0, y: 0, width: 100, height: 34)
        let pill = InteractionOutline.capsule.shape.path(in: rect)
        for y in stride(from: 0.5, to: 34.0, by: 1) {
            for x in stride(from: 0.5, to: 100.0, by: 1) {
                let point = CGPoint(x: x, y: y)
                precondition(pill.contains(point) == Capsule().path(in: rect).contains(point), "feedback must match the capsule fill at corners")
            }
        }
        print("PASS: initial/explicit/outside/locked/stale focus, protected text and selection, complete legacy titles and explanations without writes, exact capsule geometry, native book configuration")
    }
}
