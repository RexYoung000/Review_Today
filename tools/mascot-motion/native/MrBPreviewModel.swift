import AppKit
import SwiftUI

@MainActor @Observable
final class MrBPreviewModel {
    var scene = "答题反应"
    var answerSession=MrBAnswerSession()
    var reactionLabels=false
    var reactionsCompleted=Set<String>()
    func replayReactions(){reactionsCompleted=[];replayStudy()}
    var ingestion = MrBIngestionSession()
    var reviewCount = 3
    func beginIngestion(compact: Bool? = nil) {
        _ = ingestion.begin(count: count, compact: compact ?? preferences.bool(forKey: "seenFullLineStampV1"), foreground: NSApp.isActive)
    }
    func ingestionEvent(_ event: String, reduced: Bool) {
        if event == "failed" { ingestion.resourceFailed = true }
        if event == "ready" { ingestion.resourceFailed = false }
        if event == "finished", ingestion.finish(reduced: reduced) { preferences.set(true, forKey: "seenFullLineStampV1") }
    }
    var studyRecording = false
    var studyPaused = false
    var studyTime = 0.0
    var studySeek: Double? = nil
    var studySeekToken = 0
    var studyMesh = false
    var studyFailed = false
    var isFlow: Bool { scene == "A → B → 盖章" }
    var flowOutcome = "processing"
    var flowPhase = "A"
    var flowSignalToken = 0
    var flowMaxTime = 0.0
    var studyKind: String { isFlow ? "flow_study" : (scene == "消除 → 盖章连播" ? "continuity_study" : (scene == "逐行消除短样" ? "walk_study" : "stamp_study")) }
    var studyDuration: Double { if scene == "答题反应" {return 3.2};return isFlow ? max(0.001,flowMaxTime) : (scene == "消除 → 盖章连播" ? 9.4 : (scene == "逐行消除短样" ? 4.6 : 4.8)) }
    var flowCopy: String {
        if flowOutcome == "failed" { return "整理失败（模拟）· 未保存" }
        if flowOutcome == "cancelled" { return "已取消（模拟）" }
        if flowOutcome == "saved" {
            return flowPhase == "done" ? "卡片已保存（模拟）" : (flowPhase == "stamp" ? "已保存（模拟）· 盖章确认" : "已保存（模拟）· 收好剩余内容")
        }
        return "A · Mr. B 正在整理（模拟）"
    }
    func signalFlow(_ outcome: String) {
        guard isFlow, flowOutcome == "processing", ["saved","failed","cancelled"].contains(outcome) else { return }
        flowOutcome = outcome; flowSignalToken += 1
    }
    func resetFlow() { flowOutcome = "processing"; flowPhase = "A"; flowMaxTime = 0 }
    func replayStudy() { reactionsCompleted=[];resetFlow(); finished = false; studyPaused = false; studyTime = 0; studySeek = nil; token += 1 }
    func trackStudyTime(_ time: Double) { studyTime = time; if isFlow { flowMaxTime = max(flowMaxTime,time) } }
    func seekStudy(_ time: Double) { reactionsCompleted=[];finished = false; studyPaused = true; studySeek = min(isFlow ? flowMaxTime : studyDuration,max(0,time)); studyTime = studySeek!; studySeekToken += 1 }
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
    func enter(_ value: String) { reactionsCompleted=[];resetFlow(); modal = false; scene = value; studyPaused = false; studyTime = 0; studySeek = nil; token += 1; finished = false; if value == "等待" { restart() } }
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

/// Isolated presentation state. Saving is simulated; animation never writes results.
@MainActor @Observable
final class MrBIngestionSession {
    var id = UUID()
    var token = 0
    var signalToken = 0
    var presented = false
    var outcome = "idle"
    var count = 0
    var compact = false
    var finished = false
    var resourceFailed = false
    var showingResult = false
    var resultAvailable: Bool { outcome == "saved" }
    @discardableResult
    func begin(count: Int, compact: Bool, foreground: Bool = true, modalBusy: Bool = false) -> Bool {
        guard count > 0, foreground, !modalBusy, outcome != "processing" else { return false }
        id = UUID(); token += 1; self.count = count; self.compact = compact
        outcome = "processing"; presented = true; finished = false; resourceFailed = false; showingResult = false
        return true
    }
    @discardableResult
    func resolve(id: UUID, outcome: String, historical: Bool = false) -> Bool {
        guard id == self.id, !historical, self.outcome == "processing", ["saved","failed","cancelled"].contains(outcome) else { return false }
        self.outcome = outcome; signalToken += 1
        return true
    }
    func replay() {
        guard resultAvailable else { return }
        compact = false; token += 1; signalToken += 1; presented = true; finished = false; resourceFailed = false
    }
    func finish(reduced: Bool) -> Bool {
        guard !finished else { return false }
        finished = true
        return resultAvailable && presented && !compact && !reduced && !resourceFailed
    }
    func showResult() { guard resultAvailable else { return }; showingResult = true; presented = false }
}

@MainActor @Observable
final class MrBAnswerSession {
    var phase="asking"
    var scenario="good"
    var assessment=""
    var adopted=""
    var kind="reaction_rest"
    var text="检索找到相关资料，生成依据资料组织回答。"
    var token=0
    var run=UUID()
    var fail=false
    var hasFeedback: Bool {phase == "feedback" || phase == "saved"}
    private var pending="good"
    private var pendingFailure=false
    func begin() -> UUID? {
        guard ["asking","failed"].contains(phase),!text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else{return nil}
        run=UUID();pending=scenario;pendingFailure=fail;phase="judging";kind="reaction_rest";token += 1
        return run
    }
    func resolve(id:UUID) {
        guard id==run,phase=="judging" else{return}
        guard !pendingFailure else {phase="failed";return}
        assessment=pending;adopted=pending;phase="feedback"
        kind=["good":"reaction_approve","hard":"reaction_encourage","again":"reaction_guide"][pending] ?? "reaction_guide";token += 1
    }
    func save(){guard phase=="feedback" else{return};phase="saved"}
    func next(){run=UUID();phase="asking";assessment="";adopted="";kind="reaction_rest";token += 1;text=""}
    func label(_ grade:String,en:Bool)->String {en ? (["good":"Recalled smoothly","hard":"Needed some effort","again":"Needs another look"][grade] ?? grade) : (["good":"回忆顺利","hard":"回忆吃力","again":"需要再看"][grade] ?? grade)}
    func headline(english:Bool)->String {english ? (["good":"Yes. The key points are here.","hard":"You found that point again.","again":"Let's look at this part together."][assessment] ?? "") : (["good":"嗯，关键点都在。","hard":"这一点找回来了。","again":"我们再看看这一处。"][assessment] ?? "")}
    func explanation(english:Bool)->String {english ? (["good":"Both roles are covered in this simulated answer.","hard":"This rehearsal represents effortful recall or help from a hint, not an incorrect answer.","again":"This rehearsal represents a missing distinction between finding sources and composing an answer."][assessment] ?? "") : (["good":"这组样例覆盖了检索与生成各自的职责。","hard":"这组样例表示回忆吃力或使用了提示，不代表理解错误。","again":"这组样例需要补充：找资料和组织回答，是不同的工作。"][assessment] ?? "")}
}
