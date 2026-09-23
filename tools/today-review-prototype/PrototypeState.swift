import Foundation
import Observation

// Presentation-only data. This module imports no service, microphone, database or scheduler.
enum PrototypeToday: String, CaseIterable, Identifiable {
    case empty = "没有知识", unenrolled = "尚未加入", scheduled = "尚未到期"
    case due = "有到期内容", paused = "暂停的轮次", finished = "本轮结束"
    var id: Self { self }
}
enum PrototypePage: String { case today, learning, library, inbox, exam }
enum PrototypePhase: String { case preparation, asking, thinking, saving, feedback, help, explained, paused, summary, saveFailed }
enum PrototypeGoal: String, CaseIterable { case all = "全部到期", minutes = "按时长", count = "按数量" }
enum PrototypeAnswer: String, CaseIterable {
    case correct = "独立答对", difficult = "答对但回忆困难", missing = "遗漏要点", wrong = "核心误解", unclear = "需要澄清"
}
enum PrototypeMode: String { case voice, text }
struct PrototypeQuestion: Identifiable, Equatable {
    let id: Int
    let topic: String
    let question: String
    let answer: String
    let hint: String
    let explanation: String
    let clarification: String
    static let samples: [Self] = [
        .init(id: 1, topic: "检索增强生成", question: "RAG 中，检索和生成分别负责什么？", answer: "检索先找到相关资料，生成再依据资料组织回答。", hint: "想想：哪一步负责找资料，哪一步负责组织回答？", explanation: "检索从已有资料中找到相关证据；生成结合问题与这些证据组织回答。检索到的材料仍可能有误，不能自动当成事实。", clarification: "可以分成两步说：资料从哪里来？最后的回答由哪一步组织？"),
        .init(id: 2, topic: "光合作用", question: "植物进行光合作用，需要什么，又产生什么？", answer: "植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。", hint: "从能量、原料和产物三个方向回忆。", explanation: "植物利用光能，将二氧化碳和水合成有机物，并释放氧气。光提供能量，植物的物质并不是主要来自土壤。", clarification: "不用写化学式，用自己的话说出能量来源、原料和产物就好。"),
        .init(id: 3, topic: "产品指标", question: "为什么不能只看新增用户数，判断产品是否变好了？", answer: "新增只反映进入量，还要结合留存和关键行为，判断用户是否持续获得价值。", hint: "用户第一次来到产品之后，会发生什么？", explanation: "新增用户数说明有多少人进入，不能说明是否留下或获得价值。需要结合留存、关键行为等指标及目标判断。", clarification: "假设新增翻倍，但大部分人第二天就离开了。新增能完整说明体验吗？"),
        .init(id: 4, topic: "间隔复习", question: "为什么复习时先尝试回忆，再看答案？", answer: "先回忆可以练习提取，也能发现真正忘记的内容，而不是把熟悉感当成记住。", hint: "看到答案觉得熟悉，与自己想起来有什么区别？", explanation: "独立回忆练习提取，也暴露缺口；直接读答案容易把熟悉感误当成能独立说出来。", clarification: "比较两种体验：你自己说出答案，与别人说完后你觉得眼熟。"),
        .init(id: 5, topic: "工作记忆", question: "把一段复杂说明拆成几步，为什么更容易理解？", answer: "工作记忆容量有限，分步呈现能减少同时处理的信息，帮助建立联系。", hint: "想想我们一次能同时处理多少信息。", explanation: "工作记忆容量有限。分步呈现降低同时处理的信息量，为理解步骤及它们的联系留出空间。", clarification: "这里问的是分步呈现对理解过程的帮助，不需要背出容量数字。"),
        .init(id: 6, topic: "HTTP 缓存", question: "强缓存和协商缓存，主要区别是什么？", answer: "强缓存有效时直接使用本地内容；协商缓存要向服务器验证，未变化时再复用本地内容。", hint: "两种情况下，都需要向服务器确认吗？", explanation: "强缓存有效时直接复用本地响应；协商缓存向服务器验证资源，未变化时通常收到 304，再使用本地响应。", clarification: "只需要比较是否向服务器验证，以及如何使用本地内容。")
    ]
}
struct PrototypeResult: Identifiable, Equatable {
    let id: UUID
    let question: PrototypeQuestion
    var rawAnswer: String
    var correction: String? = nil
    var grade: String?
    var helped: Bool
    var skipped: Bool
    var correctionCount = 0
    var arrangement: String { grade == "Again" ? "10 分钟后" : grade == "Hard" ? "明天" : grade == nil ? "仍在到期清单" : "3 天后" }
}
struct PrototypeRecord: Identifiable { let id = UUID(); let speaker: String; let text: String }

@MainActor @Observable
final class PrototypeState {
    var today: PrototypeToday = .due
    var page: PrototypePage = .today { didSet { if page != .today { previewGlassEntry = nil } } }
    var dark = false
    var reduced = false
    var longQuestion = false
    var scenario: PrototypeAnswer = .correct
    var simulateSaveFailure = false
    var phase: PrototypePhase = .preparation
    var goal: PrototypeGoal = .all
    var minutes = 5
    var count = 5
    var mode: PrototypeMode = .voice
    var muted = false
    var voiceFailed = false
    var voiceSpeaking = false
    var textExpanded = false
    var text = ""
    var feedback = ""
    var latestTranscript = ""
    var records: [PrototypeRecord] = []
    var results: [PrototypeResult] = []
    var queue: [PrototypeQuestion] = []
    var index = 0
    var elapsedSeconds = 0
    var timeExpired = false
    var summaryReason = "本轮结束"
    var summaryCelebration = false
    // Presentation progress survives a SwiftUI layout rebuild, so resize cannot replay an ending.
    var summaryMotion: String? = nil
    var summaryMotionTime: Double = 0
    var previewGlassEntry: String? = nil
    var windowOpen = false
    var helpShown = false
    var firstGrade: String?
    var reaction: String?
    var motionToken = 0
    var editingResultID: UUID?
    var correcting = false
    var correctionText = ""
    var examSelection: String?
    var enrolledSamples = Set(PrototypeQuestion.samples.map(\.id))
    private var gradedIDs = Set<Int>()
    private var generation = 0
    private var pending: Task<Void, Never>?
    private var clockTask: Task<Void, Never>?
    private var resumePhase: PrototypePhase = .asking
    private var pendingGrade: String?
    private var pendingRaw = ""
    private var currentAttempt = UUID()
    var question: PrototypeQuestion? { queue.indices.contains(index) ? queue[index] : nil }
    var dueQuestions: [PrototypeQuestion] { [.empty, .unenrolled, .scheduled].contains(today) ? [] : PrototypeQuestion.samples.filter { enrolledSamples.contains($0.id) && !gradedIDs.contains($0.id) } }
    var completed: Int { results.filter { !$0.skipped }.count }
    var helped: Int { results.filter(\.helped).count }
    var skipped: Int { results.filter(\.skipped).count }
    var unfinished: Int { max(0, queue.count - results.count) }
    var fullSuccess: Bool { phase == .summary && !results.isEmpty && skipped == 0 && unfinished == 0 && results.allSatisfy { $0.grade != nil } }
    var busy: Bool { phase == .thinking || phase == .saving }
    var canAnswer: Bool { [.asking, .help].contains(phase) && !correcting }
    var listening: Bool { windowOpen && mode == .voice && !textExpanded && !muted && !voiceFailed && !voiceSpeaking && canAnswer }
    var progress: String { "\(min(index + 1, queue.count)) / \(queue.count)" }
    var questionText: String {
        guard let q = question else { return "" }
        return longQuestion ? q.question + "\n\n请结合一个你熟悉的情境解释两者之间的联系，说明各自解决了什么问题，以及只做其中一步可能遗漏什么。你可以分步表达，不需要复述材料原句。" : q.question
    }
    var status: String {
        if phase == .paused { return "已暂停，进度留在这里" }
        if phase == .preparation { return "准备好后，我们再开始" }
        if phase == .summary { return fullSuccess ? "这一轮，已经回顾完了" : "先到这里，也是一种节奏" }
        if correcting { return "正在纠正，推进已暂停" }
        if phase == .saveFailed { return "这次还没有记下，请重试" }
        if phase == .thinking { return "正在核对你的回答" }
        if phase == .saving { return "正在记下这次回忆" }
        if voiceFailed { return "语音暂时不可用，可以用文字继续" }
        if phase == .feedback { return "已经记下，接着下一题" }
        if voiceSpeaking { return "正在讲解，可以随时打断" }
        if phase == .explained { return "一起再看一遍" }
        if phase == .help { return "不着急，我们一起再想想" }
        if mode == .text { return "用自己的话，慢慢说清楚" }
        return muted ? "已静音，准备好再继续" : "我在听，你可以开始回答"
    }

    func select(_ state: PrototypeToday) {
        cancelPending(); stopClock(); today = state; page = .today; summaryCelebration = false
        summaryMotion = nil; summaryMotionTime = 0
        phase = .preparation; results = []; records = []; queue = []; index = 0
        gradedIDs = []; enrolledSamples = state == .empty || state == .unenrolled ? [] : Set(PrototypeQuestion.samples.map(\.id))
        feedback = ""; reaction = nil; text = ""; latestTranscript = ""; correcting = false
        goal = .all; count = 5; minutes = 5; timeExpired = false; elapsedSeconds = 0
        if state == .paused || state == .finished {
            queue = Array(PrototypeQuestion.samples.prefix(4))
            results = [sampleResult(0, grade: "Good"), sampleResult(1, grade: "Again", helped: true)]
            index = 2; gradedIDs = [1, 2]
            if state == .paused { phase = .paused; resumePhase = .asking; resetQuestion(); phase = .paused }
            else {
                results.append(sampleResult(2, grade: nil, skipped: true)); index = 3
                phase = .summary; summaryReason = "这次先到这里"
                summaryMotion = "reaction_encourage"
            }
        }
    }
    /// A separate fixture instance: previewing an ending cannot reset the active round.
    static func makeSummaryPreview(dark: Bool = false, reduced: Bool = false) -> PrototypeState {
        let preview = PrototypeState()
        preview.dark = dark; preview.reduced = reduced
        preview.loadSummarySample(complete: false)
        return preview
    }
    func loadSummarySample(complete: Bool) {
        select(.finished)
        if complete {
            results = (0..<queue.count).map { sampleResult($0, grade: $0 == 1 ? "Again" : "Good", helped: $0 == 1) }
            gradedIDs = Set(queue.map(\.id)); index = queue.count
        }
        finish(complete ? "这一轮，回顾完了" : "这次先到这里")
        windowOpen = true
    }
    func replaySummaryMotion() {
        guard phase == .summary, !correcting else { return }
        summaryMotion = fullSuccess ? "review_study" : results.isEmpty ? "reaction_guide" : "reaction_encourage"
        summaryMotionTime = 0; motionToken += 1
    }
    private func sampleResult(_ index: Int, grade: String?, helped: Bool = false, skipped: Bool = false) -> PrototypeResult {
        let q = PrototypeQuestion.samples[index]
        return .init(id: UUID(), question: q, rawAnswer: skipped ? "" : q.answer, grade: grade, helped: helped, skipped: skipped)
    }
    func prepare() { windowOpen = true; if phase != .paused && phase != .summary { phase = .preparation } }
    func newRound() { cancelPending(); phase = .preparation; windowOpen = true; results = []; queue = []; index = 0; reaction = nil }
    func start(_ mode: PrototypeMode) {
        guard phase == .preparation else { return }
        let candidates = dueQuestions
        queue = goal == .count ? Array(candidates.prefix(count)) : candidates
        guard !queue.isEmpty else { feedback = "没有可开始的到期内容。"; return }
        self.mode = mode; textExpanded = mode == .text; muted = false; voiceFailed = false
        results = []; records = []; index = 0; elapsedSeconds = 0; timeExpired = false; windowOpen = true
        resetQuestion(); phase = .asking; today = .due; startClock()
    }
    private func resetQuestion() {
        currentAttempt = UUID(); firstGrade = nil; pendingGrade = nil; helpShown = false
        text = ""; latestTranscript = ""; feedback = ""; reaction = nil; voiceSpeaking = false
        correcting = false; editingResultID = nil; motionToken += 1
        if let question { records.append(.init(speaker: "题目", text: question.question)) }
    }
    func useText() {
        guard phase != .summary && phase != .preparation else { return }
        textExpanded = true; mode = .text; muted = true; voiceSpeaking = false; reaction = nil; motionToken += 1
        if phase == .feedback { cancelPending() }
    }
    func useVoice() { guard !busy && !correcting else { return }; mode = .voice; textExpanded = false; muted = false; voiceFailed = false; voiceSpeaking = false; reaction = nil; motionToken += 1 }
    func toggleMute() { muted.toggle(); voiceSpeaking = false; reaction = nil; motionToken += 1 }
    func inputChanged() { reaction = nil; voiceSpeaking = false; motionToken += 1; if phase == .feedback { cancelPending() } }
    func submitSample() {
        guard canAnswer, let q = question else { return }
        let missing = [1: "检索负责查找相关资料。", 2: "植物需要光，最后会产生氧气。", 3: "还要看用户是否经常打开产品。", 4: "先回忆可以找出忘了的内容。", 5: "拆成几步比较清楚。", 6: "强缓存会使用本地内容。"]
        let wrong = [1: "检索和生成都在直接生成答案。", 2: "植物从土壤中直接吸收现成的有机物。", 3: "只要新增足够多，就能证明用户长期获得了价值。", 4: "看过答案觉得熟悉，就代表能独立回忆。", 5: "工作记忆没有容量限制，分步只是为了排版。", 6: "强缓存每次都必须向服务器重新下载完整内容。"]
        switch scenario {
        case .correct: submit(q.answer)
        case .difficult: submit(q.answer + "刚才回忆起来有点困难。")
        case .missing: submit(missing[q.id] ?? "我只想起了一部分。")
        case .wrong: submit(wrong[q.id] ?? "我把关系说反了。")
        case .unclear: submit("它们就是那样联系的，我懂了。")
        }
    }
    func submit(_ raw: String) {
        guard canAnswer, !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        cancelPending(); reaction = nil; latestTranscript = raw; pendingRaw = raw
        records.append(.init(speaker: mode == .voice ? "你 · 模拟转写" : "你", text: raw))
        phase = .thinking; let token = generation; let outcome = scenario
        pending = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(650))
            guard let self, !Task.isCancelled, token == self.generation else { return }
            self.resolve(outcome)
        }
    }
    // Explicit scenario input is the only evaluator in this prototype; free text is never classified.
    func resolve(_ outcome: PrototypeAnswer) {
        guard phase == .thinking else { return }
        switch outcome {
        case .unclear:
            phase = .asking; feedback = "我还不能确定你的意思，可以把刚才的关键关系再说具体一点吗？"; reaction = "reaction_guide"
        case .missing, .wrong:
            firstGrade = firstGrade ?? "Again"; phase = .help
            feedback = outcome == .missing ? "还差一个关键点。\(question?.hint ?? "")" : "这里有一个关键关系需要调整。可以再想想，或一起看一遍。"
            reaction = "reaction_encourage"
        case .correct, .difficult:
            pendingGrade = firstGrade ?? (helpShown ? "Again" : outcome == .difficult ? "Hard" : "Good")
            phase = .saving; let token = generation
            pending = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(400))
                guard let self, !Task.isCancelled, token == self.generation else { return }
                self.save()
            }
        }
        motionToken += 1
    }
    func save() {
        guard phase == .saving, let question else { return }
        if simulateSaveFailure { phase = .saveFailed; feedback = "模拟保存失败。回答还在，本题尚未计入结果。"; return }
        guard !results.contains(where: { $0.id == currentAttempt }) else { return }
        results.append(.init(id: currentAttempt, question: question, rawAnswer: pendingRaw, grade: pendingGrade, helped: helpShown, skipped: false))
        if pendingGrade != nil { gradedIDs.insert(question.id) }
        phase = .feedback; reaction = "reaction_approve"; motionToken += 1
        feedback = helpShown ? "这次说清楚了。帮助前的回忆表现也保留着，之后再巩固。" : "说清楚了，已经记下这次回忆。"
        records.append(.init(speaker: "反馈", text: feedback)); scheduleNext()
    }
    func retrySave() { guard phase == .saveFailed else { return }; simulateSaveFailure = false; phase = .saving; save() }
    private func scheduleNext() {
        let token = generation
        pending = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(1800))
            guard let self, !Task.isCancelled, token == self.generation, self.phase == .feedback, !self.correcting else { return }
            self.advance()
        }
    }
    func forgot() { guard canAnswer else { return }; firstGrade = firstGrade ?? "Again"; phase = .help; feedback = "一时想不起来也没关系。你想先看提示、听讲解，还是跳过？"; reaction = "reaction_encourage"; motionToken += 1 }
    func thinkAgain() { guard phase == .help else { return }; phase = .asking; feedback = "再给自己一点时间，我在这里。"; reaction = nil; voiceSpeaking = false }
    func hint() {
        guard canAnswer, let question else { return }; firstGrade = firstGrade ?? "Again"; helpShown = true
        phase = .help; feedback = question.hint; reaction = "reaction_guide"; motionToken += 1
        records.append(.init(speaker: "提示", text: feedback))
    }
    func explain() {
        guard canAnswer, let question else { return }; firstGrade = firstGrade ?? "Again"; helpShown = true
        phase = .explained; feedback = question.explanation; voiceSpeaking = mode == .voice && !muted && !voiceFailed
        reaction = "reaction_guide"; motionToken += 1; records.append(.init(speaker: "讲解", text: feedback))
    }
    func clarify() {
        guard canAnswer, let question else { return }; feedback = question.clarification; phase = .asking
        reaction = "reaction_guide"; motionToken += 1; records.append(.init(speaker: "题意澄清 · 不计帮助", text: feedback))
    }
    func finishExplanation() {
        guard phase == .explained, let question else { return }; cancelPending()
        results.append(.init(id: currentAttempt, question: question, rawAnswer: latestTranscript, grade: firstGrade ?? "Again", helped: true, skipped: false))
        gradedIDs.insert(question.id); advance()
    }
    func explanationFollowup() {
        guard phase == .explained else { return }
        voiceSpeaking = mode == .voice && !muted
        feedback = "再换个说法：\(question?.explanation ?? "")"
        records.append(.init(speaker: "相关追问 · 演示回应", text: feedback)); motionToken += 1
    }
    func skip() {
        guard [.asking, .help, .explained].contains(phase), !correcting, let question else { return }; cancelPending()
        results.append(.init(id: currentAttempt, question: question, rawAnswer: latestTranscript, grade: firstGrade, helped: helpShown, skipped: true))
        if firstGrade != nil { gradedIDs.insert(question.id) }; advance()
    }
    func advance() {
        guard results.contains(where: { $0.id == currentAttempt }) else { return }; cancelPending()
        if timeExpired || index + 1 >= queue.count { finish(timeExpired ? "时间到了，这题已经处理好" : "本轮结束"); return }
        index += 1; resetQuestion(); phase = .asking
    }
    func failVoice() {
        guard ![.summary, .preparation].contains(phase) else { return }
        cancelPending(); voiceFailed = true; mode = .text; textExpanded = true; muted = true; voiceSpeaking = false; reaction = nil
        if [.thinking, .saving].contains(phase) { phase = .asking; text = pendingRaw }
        feedback = "连接中断，当前题和已完成进度都还在。用文字继续，或稍后主动重连。"
    }
    func expireTime() { guard ![.preparation, .summary].contains(phase) else { return }; timeExpired = true }
    func pause() {
        guard ![.preparation, .summary, .paused].contains(phase) else { return }
        resumePhase = busy || phase == .saveFailed ? .asking : phase
        if busy { text = pendingRaw }; cancelPending(); stopClock(); phase = .paused
        today = .paused; reaction = nil; voiceSpeaking = false; correcting = false
    }
    func close() {
        pause(); windowOpen = false; reaction = nil; motionToken += 1
        summaryMotion = nil; summaryCelebration = false
    }
    func resume() {
        guard phase == .paused else { return }; windowOpen = true; phase = resumePhase; today = .due; startClock()
        if phase == .feedback { advance() }
    }
    func finish(_ reason: String = "这次先到这里") {
        cancelPending(); stopClock(); phase = .summary; today = .finished; summaryReason = reason
        reaction = nil; voiceSpeaking = false; correcting = false; motionToken += 1
        summaryCelebration = fullSuccess
        summaryMotion = fullSuccess ? "review_study" : results.isEmpty ? "reaction_guide" : "reaction_encourage"
        summaryMotionTime = 0
    }
    func beginCorrection() {
        guard !busy, ![.preparation, .paused].contains(phase), !results.isEmpty || !latestTranscript.isEmpty else { return }
        cancelPending(); reaction = nil; voiceSpeaking = false; correcting = true; muted = true; summaryCelebration = false
        summaryMotion = nil
        mode = .text; textExpanded = true
        let currentUnsubmitted = !latestTranscript.isEmpty && !results.contains(where: { $0.id == currentAttempt }) && phase != .summary
        let result = currentUnsubmitted ? nil : results.last
        if !currentUnsubmitted && (result?.rawAnswer.isEmpty ?? true) { correcting = false; return }
        editingResultID = result?.id; correctionText = result?.correction ?? result?.rawAnswer ?? latestTranscript
    }
    func applyCorrection() {
        guard correcting, !correctionText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        if let id = editingResultID, let i = results.firstIndex(where: { $0.id == id }) {
            results[i].correction = correctionText; results[i].correctionCount += 1
            // A correction revises the same simulated result; it never creates another review.
            if !results[i].helped { results[i].grade = scenario == .correct ? "Good" : scenario == .difficult ? "Hard" : scenario == .unclear ? nil : "Again" }
            if results[i].grade == nil { gradedIDs.remove(results[i].question.id) } else { gradedIDs.insert(results[i].question.id) }
        } else { latestTranscript = correctionText; text = correctionText; if !helpShown { firstGrade = nil }; phase = .asking }
        records.append(.init(speaker: "纠正", text: correctionText)); correcting = false
        feedback = "纠正已记在同一次回答中，没有增加复习次数。"; motionToken += 1
        if phase == .feedback { scheduleNext() }
    }
    func cancelCorrection() { correcting = false; if phase == .feedback { scheduleNext() } }
    func changeGrade(_ grade: String) {
        guard phase == .summary, let i = results.indices.last, results[i].grade != nil else { return }
        results[i].grade = grade
    }
    func setEnrollment(_ id: Int, enabled: Bool) { if enabled { enrolledSamples.insert(id) } else { enrolledSamples.remove(id) }; today = enrolledSamples.isEmpty ? .unenrolled : .scheduled }
    private func cancelPending() { generation += 1; pending?.cancel(); pending = nil; motionToken += 1 }
    private func startClock() {
        stopClock(); clockTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1)); guard !Task.isCancelled, let self else { return }
                if ![.paused, .preparation, .summary].contains(self.phase) { self.elapsedSeconds += 1; if self.goal == .minutes && self.elapsedSeconds >= self.minutes * 60 { self.timeExpired = true } }
            }
        }
    }
    private func stopClock() { clockTask?.cancel(); clockTask = nil }
}
