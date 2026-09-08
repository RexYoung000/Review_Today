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
        let c=MrBMotionView.Coordinator(),settings=WKWebViewConfiguration();settings.websiteDataStore = .nonPersistent();settings.userContentController.add(c,name:"mrB")
        let web=MrBPassiveWebView(frame:NSRect(x:0,y:0,width:560,height:400),configuration:settings);web.setValue(false,forKey:"drawsBackground");web.navigationDelegate=c;c.view=web;window.contentView=web
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
        c.visible=false;c.send();web.stopLoading();settings.userContentController.removeScriptMessageHandler(forName:"mrB")
    }
}
