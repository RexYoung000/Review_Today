import Foundation

@main struct TodayReviewPrototypeContracts {
    @MainActor static func main() async {
        var checks = 0
        func expect(_ value: @autoclosure () -> Bool, _ message: String) { precondition(value(), message); checks += 1; print("PASS \(message)") }
        func started(_ goal: PrototypeGoal = .all, count: Int = 5) -> PrototypeState {
            let s = PrototypeState(); s.goal = goal; s.count = count; s.prepare(); s.start(.voice); return s
        }
        func correct(_ s: PrototypeState) { s.submitSample(); s.resolve(.correct); s.save() }
        for state in PrototypeToday.allCases {
            let s = PrototypeState(); s.select(state); s.prepare()
            expect(!s.listening, "opening \(state.rawValue) never listens")
            if [.empty, .unenrolled, .scheduled].contains(state) { expect(s.dueQuestions.isEmpty, "\(state.rawValue) has no due candidates") }
            s.close()
        }
        let a = started(.count, count: 2)
        expect(a.queue.count == 2 && a.listening, "fixed queue and explicit voice start")
        a.enrolledSamples.remove(2); expect(a.queue.count == 2, "enrollment does not mutate active queue")
        a.useText(); expect(!a.listening && a.textExpanded, "text input stops simulated listening")
        a.useVoice(); expect(a.listening && !a.textExpanded, "voice resumes only on explicit action")
        a.toggleMute(); expect(!a.listening, "mute stops listening")
        a.toggleMute(); a.clarify(); expect(a.firstGrade == nil && !a.helpShown, "clarification does not grade or hint")
        correct(a); a.save(); expect(a.results.count == 1, "duplicate save ignored")
        a.advance(); a.advance(); expect(a.index == 1 && a.results.count == 1, "repeated next does not skip a question")
        a.skip(); expect(a.phase == .summary && a.skipped == 1 && !a.fullSuccess && !a.summaryCelebration, "skip produces truthful summary without celebration")
        expect(a.summaryMotion == "reaction_encourage", "partial summary offers encouragement instead of a forced static pose or celebration")
        a.summaryMotionTime = 1.2; a.prepare()
        expect(a.summaryMotionTime == 1.2, "presenting summary keeps animation progress")
        a.close(); a.prepare()
        expect(a.summaryMotion == nil && !a.summaryCelebration, "closing interrupts summary motion and reopening cannot replay it")
        expect(a.results.last?.grade == nil, "pure skip never grades")
        a.beginCorrection(); expect(!a.correcting && a.results.last?.grade == nil, "pure skip has no fabricated transcript to correct")
        let b = started(.count, count: 1); b.forgot(); b.hint(); correct(b)
        expect(b.results.first?.grade == "Again" && b.results.first?.helped == true, "hinted correct preserves first failed recall")
        b.advance(); expect(b.fullSuccess, "helped but processed round distinguishes completion from mastery")
        expect(b.summaryMotion == "review_study", "complete round retains the existing Spine ending")
        b.beginCorrection(); b.correctionText = "正确转写"; b.applyCorrection()
        expect(b.summaryMotion == nil, "correction stops the summary animation without replay")
        expect(b.results.count == 1 && b.results[0].grade == "Again" && !b.summaryCelebration, "correction keeps helped grade and interrupts ending")
        let c = started(); c.submit("错误转写"); c.resolve(.wrong); c.skip()
        expect(c.results[0].skipped && c.results[0].grade == "Again", "wrong then skip retains initial grade")
        let d = started(); correct(d); d.advance(); d.submit("第二题的错误转写"); d.resolve(.wrong); d.beginCorrection()
        expect(d.editingResultID == nil, "current uncommitted transcript correction does not target previous result")
        d.correctionText = "第二题的正确转写"; d.applyCorrection()
        expect(d.results.count == 1 && d.firstGrade == nil && d.results[0].correction == nil, "uncommitted correction leaves previous result intact")
        d.close(); expect(d.phase == .paused && !d.listening, "closing pauses active question")
        d.prepare(); expect(d.phase == .paused && !d.listening && d.index == 1, "reopening retains paused queue")
        d.resume(); expect(d.index == 1 && d.results.count == 1, "resume same question without duplicate result")
        let e = started(); e.submitSample(); e.close()
        try? await Task.sleep(for: .milliseconds(1100))
        expect(e.results.isEmpty && e.phase == .paused, "late evaluation cannot change closed round")
        let f = started(); f.submitSample(); f.failVoice()
        try? await Task.sleep(for: .milliseconds(1100))
        expect(f.results.isEmpty && f.textExpanded && !f.listening && f.index == 0, "voice failure preserves question and cannot grade")
        let g = started(); g.simulateSaveFailure = true; correct(g)
        expect(g.results.isEmpty && g.phase == .saveFailed, "failed save cannot advance or count as success")
        g.retrySave(); expect(g.results.count == 1, "save retry writes once")
        let h = started(); h.expireTime(); correct(h)
        expect(h.results.count == 1 && h.phase == .feedback, "time limit handles current answer first")
        h.advance(); expect(h.phase == .summary && h.unfinished == 5 && !h.summaryCelebration, "time limit retains unfinished queue")
        let i = started(.count, count: 1); correct(i); i.advance(); i.beginCorrection(); i.correctionText = "我实际答错了"; i.scenario = .wrong; i.applyCorrection()
        expect(i.results.count == 1 && i.results[0].correctionCount == 1 && i.results[0].grade == "Again", "committed correction updates same attempt")
        let j = started(); j.finish(); expect(j.results.isEmpty && !j.fullSuccess && !j.summaryCelebration, "empty ending never celebrates")
        let k = started(.count, count: 1); k.explain(); k.explanationFollowup(); k.finishExplanation()
        expect(k.results.count == 1 && k.results[0].helped && k.phase == .summary, "explanation can finish without forced retest")
        let l = started(.count, count: 1); l.scenario = .difficult; l.submitSample(); l.resolve(.difficult); l.save(); l.advance()
        expect(l.results[0].grade == "Hard", "explicit recall difficulty maps to Hard")
        l.changeGrade("Easy"); expect(l.results.count == 1 && l.results[0].grade == "Easy", "Easy is manual only")
        let m = started(.count, count: 1); m.submitSample()
        try? await Task.sleep(for: .milliseconds(3100))
        expect(m.phase == .summary && m.results.count == 1 && m.summaryCelebration, "saved correct answer automatically progresses and finishes")
        [a,b,c,d,e,f,g,h,i,j,k,l,m].forEach { $0.close() }
        print("\(checks) prototype state checks passed. No models, microphone, database or FSRS used.")
    }
}
