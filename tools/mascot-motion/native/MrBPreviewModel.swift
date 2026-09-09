import AppKit
import SwiftUI

@MainActor @Observable
final class MrBPreviewModel {
    var scene = "逐行消除短样"
    var studyRecording = false
    var studyPaused = false
    var studyTime = 0.0
    var studySeek: Double? = nil
    var studySeekToken = 0
    var studyMesh = false
    var studyFailed = false
    var studyKind: String { scene == "消除 → 盖章连播" ? "continuity_study" : (scene == "逐行消除短样" ? "walk_study" : "stamp_study") }
    var studyDuration: Double { scene == "消除 → 盖章连播" ? 9.4 : (scene == "逐行消除短样" ? 4.6 : 4.8) }
    func replayStudy() { finished = false; studyPaused = false; studyTime = 0; studySeek = nil; token += 1 }
    func seekStudy(_ time: Double) { studyPaused = true; studySeek = min(studyDuration,max(0,time)); studyTime = studySeek!; studySeekToken += 1 }
    var dark = false
    var reduced = false
    var english = false
    var longCopy = false
    var stage = "organize"
    var copyIndex = 0
    var token = 1
    var waiting = true
    var settling = false
    var replied = false
    var details = false
    var status = ""
    var elapsedStart = Date.now
    var modal = false
    var compact = false
    var count = 3
    var finished = false
    var failedResource = false
    var clip = "idle"
    var reviewReason = "complete"
    var gate = MrBSettlementGate()
    var eventID = UUID().uuidString
    var outcomeSaved = false
    var outcome = ""
    var eventLog = ""
    let preferences = UserDefaults.standard // unique preview bundle domain; never the daily app domain
    var seenFull: Bool { preferences.bool(forKey: "seenFull") }
    var lines: [String] { english ? ["Retrieval finds relevant evidence", "Generation explains the evidence", "Check sources and permissions"] : ["检索负责寻找相关资料与来源", "生成依据资料组织清楚的回答", "仍然需要检查来源与访问权限"] }
    var title: String { english ? "Retrieval and generation" : "检索与生成的分工" }
    var copy: String {
        if longCopy { return english ? "Mr. B is carefully organizing the relationships between retrieval, generation, and source verification in these notes." : "Mr. B 正在整理这份资料中检索、生成与来源核验之间的关系" }
        let zh: [String: [String]] = ["organize":["Mr. B 正在整理这份资料", "Mr. B 正在梳理知识之间的关系", "这部分，得仔细看看"],"answer":["Mr. B 正在准备回答", "Mr. B 正在组织这次回答", "让我把这部分说清楚"],"search":["Mr. B 正在查找公开资料", "Mr. B 正在寻找相关来源", "这次的依据，得找仔细"],"verify":["Mr. B 正在核对回答依据", "Mr. B 正在检查资料中的结论", "这部分，得仔细看看"]]
        let en: [String: [String]] = ["organize":["Mr. B is organizing these notes", "Mr. B is connecting the ideas", "This deserves a closer look"],"answer":["Mr. B is preparing a response", "Mr. B is organizing the answer", "Let me make this clear"],"search":["Mr. B is finding public sources", "Mr. B is looking for evidence", "Let's find a reliable source"],"verify":["Mr. B is checking the evidence", "Mr. B is reviewing the claims", "This deserves a closer look"]]
        return (english ? en : zh)[stage]?[copyIndex % 3] ?? (english ? "Mr. B is working on your request" : "Mr. B 正在处理这次请求")
    }
    var showcaseID = UUID()
    var showcasing = false
    @ObservationIgnored private var showcaseFinish: (() -> Void)?
    func playShowcase(onFinish: @escaping () -> Void = {}) {
        guard !showcasing && !reduced && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else { return }
        showcaseID = UUID(); let id = showcaseID; showcasing = true; showcaseFinish = onFinish; enter("待机动作")
        Task {
            try? await Task.sleep(for: .seconds(1))
            for (name, seconds) in [("mr_receive",1.5),("mr_ponder",3.8),("mr_weigh",3.6),("mr_focus",3.2),("mr_peek",4.8),("mr_hide",6.0)] {
                guard showcaseID == id && scene == "待机动作" else { break }
                clip = name; token += 1
                var remaining = seconds + 0.8
                while remaining > 0 && showcaseID == id && scene == "待机动作" && clip == name {
                    try? await Task.sleep(for: .milliseconds(100))
                    if NSApp.isActive { remaining -= 0.1 }
                }
                if clip != name { break }
            }
            guard showcaseID == id else { return }
            showcasing = false; showcaseFinish?(); showcaseFinish = nil
        }
    }
    func stopShowcase() { showcaseID = UUID(); showcasing = false; showcaseFinish?(); showcaseFinish = nil }
    func restart() { token += 1; waiting = true; settling = false; replied = false; copyIndex = 0; status = ""; elapsedStart = .now }
    func respond(reduceMotion: Bool? = nil) {
        let noMotion = reduceMotion ?? reduced
        replied = true; settling = true
        let current = token
        Task { if !noMotion { try? await Task.sleep(for: .milliseconds(240)) }; guard token == current else { return }; waiting = false; settling = false }
    }
    func stop(failed: Bool = false) { waiting = false; settling = false; status = failed ? "这次处理未完成，可以重试。" : "已停止，可以继续或重新提问。" }
    func enter(_ value: String) { modal = false; scene = value; studyPaused = false; studyTime = 0; studySeek = nil; token += 1; finished = false; if value == "等待" { restart() } }
    func save(newEvent: Bool = true, saved: Bool = true, historical: Bool = false) {
        if newEvent { eventID = UUID().uuidString }
        let accepted = gate.accept(id: eventID, saved: saved, foreground: NSApp.isActive, modalBusy: modal, historical: historical)
        outcomeSaved = saved
        outcome = saved ? "已加入知识库 · \(count) 张" : "保存未成功，未播放结算。"
        eventLog = accepted ? "模拟保存成功，展示一次结算。" : "本次事件未触发表演（重复、失败、后台或历史事件）。"
        if accepted { compact = seenFull; token += 1; finished = false; modal = true }
    }
    func replay() { compact = false; finished = false; token += 1; modal = true }
}
