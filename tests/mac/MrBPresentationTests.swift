import AppKit
import SwiftUI
import WebKit

private struct Failure: Error { var message: String }
@main
struct MrBPresentationTests {
    @MainActor static func main() {
        let app=NSApplication.shared; app.setActivationPolicy(.regular)
        let window=NSWindow(contentRect:NSRect(x:140,y:140,width:560,height:400),styleMask:[.titled,.closable],backing:.buffered,defer:false)
        window.title="Mr. B · 自动化原生验证"; window.makeKeyAndOrderFront(nil); app.activate(ignoringOtherApps:true)
        Task { @MainActor in do {try await checks(window);print("PASS: native Spine bridge, lifecycle, interruption, compact completion, eligibility and event deduplication");exit(0)} catch {fputs("FAIL: \(error)\n",stderr);exit(1)} }
        app.run()
    }
    @MainActor static func checks(_ window:NSWindow) async throws {
        func expect(_ value:Bool,_ message:String) throws {if !value{throw Failure(message:message)}}
        let model=MrBPreviewModel()
        model.restart();model.respond();try expect(model.replied && model.waiting,"Text delayed until animation ended")
        try await Task.sleep(for:.milliseconds(300));try expect(!model.waiting,"Waiting mascot not dismissed")
        model.restart();model.respond();model.restart();try await Task.sleep(for:.milliseconds(300));try expect(model.waiting && !model.replied,"Old response dismissed a newer run")
        model.respond(reduceMotion:true);await Task.yield();try expect(model.replied && !model.waiting,"Reduced response exit delayed")
        for stage in ["organize","answer","search","verify","unknown"] {model.stage=stage;model.copyIndex=0;let first=model.copy;model.copyIndex=1;let second=model.copy;model.copyIndex=2;let third=model.copy;try expect(!first.isEmpty && !second.isEmpty && !third.isEmpty,"Missing copy");if stage=="unknown" {try expect(!first.contains("检索"),"Unknown stage invents search")}}
        var gate=MrBSettlementGate()
        try expect(!gate.accept(id:"failed",saved:false,foreground:true,modalBusy:false),"Failed save presented")
        try expect(gate.accept(id:"failed",saved:true,foreground:true,modalBusy:false),"Successful retry lost")
        try expect(!gate.accept(id:"failed",saved:true,foreground:true,modalBusy:false),"Duplicate presented")
        try expect(!gate.accept(id:"background",saved:true,foreground:false,modalBusy:false),"Background stole focus")
        try expect(!gate.accept(id:"background",saved:true,foreground:true,modalBusy:false),"Background queued a surprise")
        try expect(!gate.accept(id:"history",saved:true,foreground:true,modalBusy:false,historical:true),"History replayed")
        try expect(!gate.accept(id:"modal",saved:true,foreground:true,modalBusy:true),"Nested modal")
        for reason in ["paused","time_limit","preview","failed"] {try expect(!MrBSettlementGate.reviewEligible(formal:true,saved:true,reason:reason,count:3),"Wrong completion badge")}
        try expect(!MrBSettlementGate.reviewEligible(formal:false,saved:true,reason:"complete",count:1),"Preview marked formal")
        try expect(!MrBSettlementGate.reviewEligible(formal:true,saved:false,reason:"complete",count:3),"Failed result badge")
        try expect(!MrBSettlementGate.reviewEligible(formal:true,saved:true,reason:"complete",count:0),"Empty badge")
        try expect(MrBSettlementGate.reviewEligible(formal:true,saved:true,reason:"complete",count:3),"Completion missed")
        let intake=MrBIngestionSession()
        try expect(!intake.begin(count:3,compact:false,foreground:false),"Background opens an ingestion modal")
        try expect(!intake.begin(count:0,compact:false),"Empty ingestion starts")
        try expect(intake.begin(count:3,compact:false),"Full ingestion cannot start")
        let oldID=intake.id
        intake.presented=false
        try expect(intake.resolve(id:oldID,outcome:"saved") && intake.resultAvailable && !intake.presented,"Closing cancels saving or result steals focus")
        try expect(!intake.finish(reduced:false),"Closed presentation consumes first full experience")
        try expect(!intake.resolve(id:oldID,outcome:"failed"),"Duplicate outcome overwrites saved result")
        intake.replay();try expect(intake.resultAvailable && intake.count==3 && intake.presented && !intake.compact,"Replay loses saved result")
        try expect(intake.finish(reduced:false) && !intake.finish(reduced:false),"Full completion is not consumed exactly once")
        for reason in ["failed","cancelled"] {
            try expect(intake.begin(count:2,compact:false),"Retry cannot begin")
            try expect(!intake.resolve(id:oldID,outcome:"saved"),"Old result overwrites newer run")
            try expect(!intake.resolve(id:intake.id,outcome:"saved",historical:true),"History triggers a new result")
            intake.resolve(id:intake.id,outcome:reason)
            try expect(!intake.resultAvailable && !intake.finish(reduced:false),"Unsuccessful run consumes first full experience")
        }
        for (short,reduced,failed) in [(true,false,false),(false,true,false),(false,false,true)] {
            intake.begin(count:4,compact:short);intake.resolve(id:intake.id,outcome:"saved");intake.resourceFailed=failed
            try expect(!intake.finish(reduced:reduced) && intake.resultAvailable,"Fallback loses result or consumes first full")
            intake.showResult();try expect(intake.showingResult && !intake.presented,"Result not immediately accessible")
        }
        let c=MrBMotionView.Coordinator(),settings=WKWebViewConfiguration();settings.websiteDataStore = .nonPersistent();settings.userContentController.add(c,name:"mrB")
        let web=MrBPassiveWebView(frame:NSRect(x:0,y:0,width:560,height:400),configuration:settings);web.setValue(false,forKey:"drawsBackground");web.navigationDelegate=c;c.view=web;window.contentView=web
        c.configuration.kind="walk_study"
        var completions=0;c.onEvent={if $0=="finished"{completions += 1}}
        let url=Bundle.main.url(forResource:"MrBMotion",withExtension:"html")!;let html=try String(contentsOf:url,encoding:.utf8)
        try expect(html.contains("connect-src 'none'"),"Offline restriction missing");web.loadHTMLString(html,baseURL:nil)
        for _ in 0..<200 {if c.ready{break};try await Task.sleep(for:.milliseconds(50))}
        try expect(c.ready,"Spine resource failed")
        func inspect() async throws -> [String:Any] {try await web.evaluateJavaScript("window.mrB.inspect()") as! [String:Any]}
        c.configuration.kind="thinking";c.configuration.token=1;c.send();try await Task.sleep(for:.milliseconds(500))
        var state=try await inspect();try expect((state["clipTime"] as? Double ?? 0) > 0.1,"Clock not advancing")
        c.visible=false;c.send();try await Task.sleep(for:.milliseconds(100));let hidden=try await inspect();try await Task.sleep(for:.milliseconds(200));state=try await inspect()
        try expect(state["frames"] as? Int == hidden["frames"] as? Int,"Hidden still renders")
        c.visible=true;c.configuration.reduced=true;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect();try expect(state["animating"] as? Bool == false,"Reduced still animates")
        c.configuration.reduced=false;c.configuration.kind="mr_hide";c.configuration.token=2;c.send();try await Task.sleep(for:.milliseconds(1200))
        c.configuration.kind="settle";c.send();try await Task.sleep(for:.milliseconds(360));state=try await inspect();try expect(state["done"] as? Bool == true && state["animating"] as? Bool == false,"Mid-book stop did not settle")
        c.configuration.kind="mr_ingest_short";c.configuration.token=3;c.send();let before=completions;for _ in 0..<60 {try await Task.sleep(for:.milliseconds(100));state=try await inspect();if state["done"] as? Bool == true {break}};try expect(state["done"] as? Bool == true,"Compact settlement never ends: \(state)");try expect(completions==before+1,"Completion callback not exactly once")
        c.configuration.dark=true;c.send();try await Task.sleep(for:.milliseconds(200));try expect(completions==before+1,"Theme change replays completion")
        c.configuration.kind="thinking";c.configuration.token=4;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect();try expect(state["done"] as? Bool == false,"New request stuck completed")
        for (kind, duration) in [("walk_study",4.6),("stamp_study",4.8),("continuity_study",9.4)] {
            c.configuration = MrBConfiguration(kind:kind,token:c.configuration.token+1)
            c.send(); try await Task.sleep(for:.milliseconds(400));state=try await inspect()
            try expect((state["runtimeError"] as? String ?? "").isEmpty,"Study runtime failed: \(state)")
            try expect(((state["study"] as? [String:Any])?["paintedPixels"] as? Int ?? 0)>10000,"Study lacks visible mesh pixels: \(state)")
            c.configuration.paused=true;c.send();try await Task.sleep(for:.milliseconds(100));let paused=try await inspect()
            try await Task.sleep(for:.milliseconds(200));state=try await inspect()
            try expect(state["frames"] as? Int == paused["frames"] as? Int,"Paused study still draws")
            c.configuration.seekTime=duration*0.6;c.configuration.seekToken += 1;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
            try expect(abs((state["clipTime"] as? Double ?? 0)-duration*0.6)<0.001,"Study seek failed")
            c.visible=false;c.configuration.paused=false;c.configuration.reviewRecording=true;c.send();try await Task.sleep(for:.milliseconds(180));state=try await inspect()
            try expect((state["clipTime"] as? Double ?? 0)>duration*0.6,"Explicit study capture stopped on background")
            c.configuration.reviewRecording=false;c.send();try await Task.sleep(for:.milliseconds(100));let background=try await inspect()
            try await Task.sleep(for:.milliseconds(150));state=try await inspect()
            try expect(state["frames"] as? Int == background["frames"] as? Int,"Recording failed to restore background pause")
            c.configuration.reviewRecording=true;c.configuration.visible=false;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
            try expect(state["animating"] as? Bool == false,"Recording overrides removed view lifecycle")
            c.configuration.reviewRecording=false;c.configuration.visible=true;c.visible=true;c.configuration.paused=true
            c.configuration.reduced=true;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
            try expect(state["animating"] as? Bool == false,"Reduced study animates")
            c.configuration.reduced=false;c.configuration.paused=false;c.configuration.seekTime=duration-0.2;c.configuration.seekToken += 1
            let countBefore=completions;c.send();for _ in 0..<30 {try await Task.sleep(for:.milliseconds(100));state=try await inspect();if state["done"] as? Bool == true {break}}
            try expect(state["done"] as? Bool == true && completions==countBefore+1,"Study completion not delivered exactly once")
            c.configuration.debugMesh=true;c.send();try await Task.sleep(for:.milliseconds(100));try expect(completions==countBefore+1,"Debug toggle replays completed event")
        }
        c.configuration=MrBConfiguration(kind:"continuity_study",token:100,paused:true)
        for (time, segment) in [(4.6-1.0/30,"walk_study"),(4.6,"stamp_study"),(4.6+1.0/30,"stamp_study"),(4.6-1.0/30,"walk_study")] {
            c.configuration.seekTime=time;c.configuration.seekToken += 1;c.send();try await Task.sleep(for:.milliseconds(120));state=try await inspect()
            let info=state["study"] as? [String:Any],meta=info?["meta"] as? [String:Any]
            try expect(meta?["segment"] as? String == segment,"Native joined seam selects wrong segment")
            try expect(meta?["body"] as? [Double] == [380,154],"Native seam changes Mr. B position")
            try expect((state["runtimeError"] as? String ?? "").isEmpty,"Native seam runtime error")
        }
        model.enter("A → B → 盖章");model.signalFlow("saved");model.signalFlow("failed")
        try expect(model.flowOutcome == "saved", "Preview accepts conflicting outcomes")
        model.replayStudy();try expect(model.flowOutcome == "processing" && model.flowPhase == "A", "Retry retains terminal state")
        model.seekStudy(10);try expect(model.studyTime == 0, "Unplayed flow time can be sought")
        model.trackStudyTime(3.2);model.seekStudy(20);try expect(model.studyTime == 3.2, "Flow seeking goes beyond played history")
        func settleState(_ check: ([String:Any]) -> Bool, _ message: String) async throws -> [String:Any] {
            for _ in 0..<30 { let value=try await inspect();if check(value) { return value };try await Task.sleep(for:.milliseconds(50)) }
            throw Failure(message:message)
        }
        func flowMeta(_ value:[String:Any]) -> [String:Any] { (value["study"] as? [String:Any])?["meta"] as? [String:Any] ?? [:] }
        c.configuration=MrBConfiguration(kind:"flow_study",token:110,paused:true,seekTime:5.31,seekToken:1);c.send()
        state=try await settleState({flowMeta($0)["flowPhase"] as? String == "A"},"Flow A failed to start")
        let bodyBefore=flowMeta(state)["body"] as? [Double],timeBefore=state["clipTime"] as? Double ?? 0
        c.configuration.flowOutcome="saved";c.configuration.flowSignalToken=1;c.send()
        state=try await settleState({flowMeta($0)["flowPhase"] as? String == "B"},"Paused completion did not enter B")
        try expect(flowMeta(state)["body"] as? [Double] == bodyBefore,"A to B jumps while paused")
        try expect(state["clipTime"] as? Double == timeBefore,"Completion advances a paused clock")
        let event=state["flow"] as! [String:Any],stampAt=event["stampAt"] as! Double
        c.configuration.flowOutcome="failed";c.configuration.flowSignalToken=2;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
        try expect((state["flow"] as? [String:Any])?["outcome"] as? String == "saved","Duplicate signal overrides saved")
        c.configuration.seekTime=stampAt+2.3;c.configuration.seekToken += 1;c.send()
        state=try await settleState({flowMeta($0)["imprinted"] as? Bool == true},"Flow stamp missing after contact")
        c.configuration.seekTime=stampAt+4.7;c.configuration.seekToken += 1;c.configuration.paused=false
        let flowCompletions=completions;c.send()
        state=try await settleState({$0["done"] as? Bool == true},"Flow never finishes")
        try expect(completions==flowCompletions+1,"Flow completion not once")
        c.configuration.seekTime=stampAt+4.6;c.configuration.seekToken += 1;c.send()
        try await Task.sleep(for:.milliseconds(350));state=try await inspect()
        try expect(state["done"] as? Bool == true && completions==flowCompletions+1,"Seeking re-emits flow completion")
        for (index,outcome) in ["failed","cancelled"].enumerated() {
            c.configuration=MrBConfiguration(kind:"flow_study",token:120+index,paused:true,seekTime:0.91,seekToken:10+index);c.send()
            _=try await settleState({flowMeta($0)["flowPhase"] as? String == "A"},"Retry does not reset A")
            c.configuration.flowOutcome=outcome;c.configuration.flowSignalToken=10+index;c.configuration.paused=false;c.send()
            state=try await settleState({$0["done"] as? Bool == true && flowMeta($0)["flowPhase"] as? String == outcome},"Flow stop did not settle")
            try expect(completions==flowCompletions+1,"Failure or cancellation emits success")
            try expect(flowMeta(state)["imprinted"] as? Bool != true,"Stopped flow stamped")
        }
        c.configuration=MrBConfiguration(kind:"flow_study",token:130,reduced:true);c.send()
        state=try await settleState({flowMeta($0)["flowPhase"] as? String == "A"},"Reduced processing shows a result")
        try expect(state["animating"] as? Bool == false,"Reduced processing moves")
        c.configuration.flowOutcome="saved";c.configuration.flowSignalToken=30;c.send()
        state=try await settleState({flowMeta($0)["flowPhase"] as? String == "done"},"Reduced success does not show R")
        try expect(state["animating"] as? Bool == false,"Reduced success moves")
        c.configuration.reduced=false;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
        try expect(state["animating"] as? Bool == false,"Turning off Reduce Motion replays successful flow")
        c.configuration=MrBConfiguration(kind:"flow_study",token:140);c.send()
        _=try await settleState({($0["clipTime"] as? Double ?? 0)>0.12 && flowMeta($0)["flowPhase"] as? String == "A"},"A clock not advancing")
        c.visible=false;c.send();try await Task.sleep(for:.milliseconds(100));let flowHidden=try await inspect()
        try await Task.sleep(for:.milliseconds(180));state=try await inspect()
        try expect(state["frames"] as? Int == flowHidden["frames"] as? Int,"Background A still renders")
        c.visible=true;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
        try expect((state["clipTime"] as? Double ?? 0)-(flowHidden["clipTime"] as? Double ?? 0)<0.2,"A catches up background time")
        c.visible=false;c.configuration.reviewRecording=true;c.send()
        let captureBefore=state["clipTime"] as? Double ?? 0
        _=try await settleState({($0["clipTime"] as? Double ?? 0)>captureBefore+0.12},"Explicit flow recording stops in background")
        c.configuration.flowOutcome="failed";c.configuration.flowSignalToken=60;c.send()
        _=try await settleState({$0["done"] as? Bool == true && flowMeta($0)["flowPhase"] as? String == "failed"},"Recorded background failure never settles")
        c.configuration.reviewRecording=false;c.visible=true
        for (index,time) in [0.1,1.29].enumerated() {
            c.configuration=MrBConfiguration(kind:"flow_study",token:150+index,paused:true,seekTime:time,seekToken:40+index);c.send()
            _=try await settleState({flowMeta($0)["flowPhase"] as? String == "A"},"Endpoint test did not enter A")
            c.configuration.flowOutcome="saved";c.configuration.flowSignalToken=50+index;c.send()
            state=try await settleState({flowMeta($0)["flowPhase"] as? String == "B"},"Endpoint test did not enter B")
            let event=state["flow"] as! [String:Any]
            c.configuration.seekTime=(event["stampAt"] as! Double)+4.8;c.configuration.seekToken += 1;c.send()
            _=try await settleState({flowMeta($0)["flowPhase"] as? String == "done"},"Finished flow still reports stamping")
        }
        c.configuration=MrBConfiguration(kind:"flow_study",token:170,paused:true,seekTime:1.31,seekToken:80,compact:true);c.send()
        _=try await settleState({flowMeta($0)["flowPhase"] as? String == "A"},"Compact A missing")
        c.configuration.flowOutcome="saved";c.configuration.flowSignalToken=80;c.send()
        state=try await settleState({flowMeta($0)["flowPhase"] as? String == "B"},"Compact B missing")
        let compactEvent=state["flow"] as! [String:Any]
        c.configuration.seekTime=(compactEvent["stampAt"] as! Double)+3.30;c.configuration.seekToken += 1;c.configuration.paused=false;c.send()
        _=try await settleState({$0["done"] as? Bool == true && flowMeta($0)["flowPhase"] as? String == "done"},"Compact never completes")
        c.configuration=MrBConfiguration(kind:"review_study",token:180,paused:true,seekTime:2.97,seekToken:90);c.send()
        state=try await settleState({($0["study"] as? [String:Any])?["kind"] as? String == "review_study" && abs((($0["study"] as? [String:Any])?["time"] as? Double ?? 0)-2.97)<0.001},"Review seek failed")
        try expect(flowMeta(state)["imprinted"] as? Bool == false,"Review stamps before contact")
        c.configuration.seekTime=3.05;c.configuration.seekToken += 1;c.send()
        _=try await settleState({flowMeta($0)["imprinted"] as? Bool == true},"Review R missing")
        c.configuration.seekTime=6.45;c.configuration.seekToken += 1;c.configuration.paused=false;c.send()
        _=try await settleState({$0["done"] as? Bool == true},"Review never finishes")
        let reviewCompletions=completions;c.configuration.dark.toggle();c.send();try await Task.sleep(for:.milliseconds(100))
        try expect(completions==reviewCompletions,"Theme change repeats review completion")
        c.configuration=MrBConfiguration(kind:"review_study",token:181,reduced:true);c.send()
        _=try await settleState({($0["config"] as? [String:Any])?["token"] as? Int == 181 && $0["done"] as? Bool == true && flowMeta($0)["imprinted"] as? Bool == true},"Reduced review lacks static R")
        c.configuration.reduced=false;c.send();try await Task.sleep(for:.milliseconds(100));state=try await inspect()
        try expect(state["animating"] as? Bool == false,"Turning off reduced motion replays review")
        c.visible=false;c.send();web.stopLoading();settings.userContentController.removeScriptMessageHandler(forName:"mrB")
    }
}
