import AppKit
import SwiftUI

@main
struct MrBPreviewApp: App {
    @State private var model = MrBPreviewModel()
    @State private var capture = MrBPreviewCapture()
    init() { precondition(["Rex.Review-Today.MrBPreview","Rex.Review-Today.MrBContactPreview"].contains(Bundle.main.bundleIdentifier ?? "")) }
    var body: some Scene {
        WindowGroup(Bundle.main.bundleIdentifier == "Rex.Review-Today.MrBContactPreview" ? "Mr. B · 接触短样" : "Mr. B · 原生试演") {
            MrBPreviewRoot(model: model)
                .preferredColorScheme(model.dark ? .dark : .light)
                .onChange(of: model.reduced) { _, value in capture.reduced = value }
        }
        .defaultSize(width: 1280, height: 820)
        .windowResizability(.contentMinSize)
        .commands {
            CommandMenu("试演") {
                Button("录制当前单题反馈") { capture.recordAnswer(model:model) }
                Button("录制三种单题回应") { capture.recordReactions(model:model) }
                Button("录制完整入库（手动保存）") { capture.recordIngestion(model:model,compact:false) }
                Button("录制精简入库（手动保存）") { capture.recordIngestion(model:model,compact:true) }
                Button("录制复习完成") { capture.recordReview(model:model) }
                Button("录制 A → B → 盖章（手动触发）") { capture.recordStudy(model:model,scene:"A → B → 盖章") }
                Button("录制消除 → 盖章连播") { capture.recordStudy(model:model,scene:"消除 → 盖章连播") }
                Button("录制逐行消除短样") { capture.recordStudy(model:model,scene:"逐行消除短样") }
                Button("录制2D 盖章短样") { capture.recordStudy(model:model,scene:"2D 盖章短样") }
                Button("逐行消除短样") { model.enter("逐行消除短样") }.keyboardShortcut("8",modifiers:[.command,.option])
                Button("2D 盖章短样") { model.enter("2D 盖章短样") }.keyboardShortcut("9",modifiers:[.command,.option])
                Button("重播短样") { model.replayStudy() }.keyboardShortcut("0",modifiers:[.command,.option])
                Button("标准窗口") { capture.resize(1280,820) }.keyboardShortcut("1",modifiers:[.command,.option])
                Button("最小窗口") { capture.resize(760,620) }.keyboardShortcut("2",modifiers:[.command,.option])
                Toggle("深色",isOn:$model.dark).keyboardShortcut("d",modifiers:[.command,.option])
                Toggle("减少动态",isOn:$model.reduced).keyboardShortcut("m",modifiers:[.command,.option])
                Button("截图") { capture.snapshot() }.keyboardShortcut("s",modifiers:[.command,.option])
                Button("正常速度录屏／停止") { capture.toggleRecording() }.keyboardShortcut("r",modifiers:[.command,.option])
                Button("首段正文") { model.respond(reduceMotion: model.reduced || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion) }.keyboardShortcut("3",modifiers:[.command,.option])
                Button("重新等待") { model.restart() }.keyboardShortcut("4",modifiers:[.command,.option])
                Button("播放完整入库") { model.enter("知识入库"); model.beginIngestion(compact:false) }.keyboardShortcut("5",modifiers:[.command,.option])
                Button("录制六段动作连播") { if !capture.recording { capture.toggleRecording() }; model.playShowcase { capture.recording = false } }.keyboardShortcut("7",modifiers:[.command,.option])
                Button("播放复习结算") { model.enter("复习结算") }.keyboardShortcut("6",modifiers:[.command,.option])
            }
        }
    }
}

struct MrBPreviewRoot: View {
    @Bindable var model: MrBPreviewModel
    @Environment(\.accessibilityReduceMotion) private var systemReduced
    @FocusState private var inputFocused: Bool
    @State private var input = ""
    private var reduced: Bool { model.reduced || systemReduced }
    private var paper: Color { model.dark ? Color(white:0.12) : Color(white:0.97) }
    var body: some View {
        HStack(spacing:0) {
            VStack(alignment:.leading,spacing:16) {
                Text("Mr. B").font(.title2.bold()); Text("Bread · 认真一点点").font(.caption).foregroundStyle(.secondary)
                Divider().padding(.vertical,8)
                ScrollView { ForEach(["答题反应","答题反馈","A → B → 盖章","逐行消除短样","2D 盖章短样","消除 → 盖章连播","等待","知识入库","复习结算","待机动作"],id:\.self) { scene in
                    Button { model.enter(scene) } label: {
                        Text(scene).frame(maxWidth:.infinity,alignment:.leading).padding(10)
                            .background(model.scene == scene ? Color.primary.opacity(0.08) : .clear,in:RoundedRectangle(cornerRadius:10))
                    }.buttonStyle(.plain)
                }}
                Spacer()
                Text("隔离原生试演\n真实 Spine · 模拟事件\n不连接模型或日常数据").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
            }.padding(20).frame(width:170).background(paper)
            Divider()
            VStack(spacing:0) {
                HStack {
                    Text(model.scene).font(.headline); Spacer()
                    Toggle("深色",isOn:$model.dark)
                    Toggle("减少动态",isOn:$model.reduced)
                    Toggle("English",isOn:$model.english)
                }.toggleStyle(.checkbox).font(.caption).padding(18)
                Divider()
                Group {
                    switch model.scene {
                    case "逐行消除短样", "2D 盖章短样", "消除 → 盖章连播", "A → B → 盖章": study
                    case "答题反应": MrBReactionPreview(model:model,reduced:reduced)
                    case "答题反馈": MrBAnswerPreview(model:model,reduced:reduced)
                    case "知识入库": knowledge
                    case "复习结算": review
                    case "待机动作": idle
                    default: conversation
                    }
                }.frame(maxWidth:.infinity,maxHeight:.infinity)
            }
        }.frame(minWidth:760,minHeight:620).background(paper)
            .sheet(isPresented:$model.ingestion.presented,onDismiss:{inputFocused=true}) { settlement }
            .onChange(of:model.reviewReason) { _,_ in model.token += 1 }
            .onChange(of:model.reviewCount) { _,_ in model.token += 1 }
            .onChange(of:model.stage) { _,_ in model.copyIndex=0 }
            .task(id:"\(model.token)-\(model.stage)") {
                while !Task.isCancelled && model.waiting && model.scene == "等待" {
                    try? await Task.sleep(for:.seconds(6)); guard !Task.isCancelled else { return }
                    if NSApp.isActive && !reduced && model.waiting { withAnimation(.easeInOut(duration:0.18)){model.copyIndex += 1} }
                }
            }
    }
    private func motion(_ kind: String, width:CGFloat, height:CGFloat, event:@escaping(String)->Void = {_ in}) -> some View {
        MrBDecoratedMotion(configuration:.init(kind:kind,stage:model.stage,token:model.token,dark:model.dark,reduced:reduced,lines:model.lines,count:model.count,title:model.title,language:model.english ? "en" : "zh",framing:model.scene == "待机动作" ? "ambient" : "presence",reviewRecording:model.studyRecording),failed:model.failedResource,onEvent:event)
            .frame(width:width,height:height)
    }
    private var study: some View {
        VStack(alignment:.leading,spacing:16) {
            Text(model.isFlow ? "整理中，直到内容收好。" : model.scene == "消除 → 盖章连播" ? "同一张纸，收好再盖章。" : (model.scene == "逐行消除短样" ? "一步一条，把内容收好。" : "拿出来，认真盖一下。"))
                .font(.title2.bold())
            Text("逐行踏步与 2D 取放短样 · 动作视觉已验收").font(.caption).foregroundStyle(.secondary)
            if model.isFlow {
                Text(model.flowCopy).font(.callout).accessibilityIdentifier("flow-status")
                HStack {
                    Button("完成并保存（模拟）") { model.signalFlow("saved") }
                    Button("失败") { model.signalFlow("failed") }
                    Button("取消") { model.signalFlow("cancelled") }
                }.font(.caption).disabled(model.flowOutcome != "processing")
            }
            GeometryReader { geometry in
                ZStack {
                    MrBMotionView(configuration:.init(kind:model.studyKind,token:model.token,dark:model.dark,reduced:reduced,language:model.english ? "en" : "zh",paused:model.studyPaused,seekTime:model.studySeek,seekToken:model.studySeekToken,debugMesh:model.studyMesh,reviewRecording:model.studyRecording,flowOutcome:model.flowOutcome,flowSignalToken:model.flowSignalToken),onEvent:{ event in
                        if event == "failed" { model.studyFailed = true }
                        if event == "ready" { model.studyFailed = false }
                        if event == "finished" || event == "flowStopped" { model.finished = true; model.studyPaused = true; if !model.isFlow { model.studyTime = model.studyDuration } }
                        if event.hasPrefix("flow:") { model.flowPhase = String(event.dropFirst(5)); if model.flowPhase == "done" { model.finished = true; model.studyPaused = true } }
                    },onTime:{ time in model.trackStudyTime(time) })
                    .accessibilityHidden(true)
                    if model.studyFailed { Text("短样加载失败，请重新打开试演。").foregroundStyle(.secondary) }
                }.frame(width:geometry.size.width,height:geometry.size.height)
            }.frame(minHeight:220)
            HStack {
                Button { model.replayStudy() } label: { Label(model.isFlow ? "重新开始" : "重播",systemImage:"arrow.counterclockwise") }
                Button { if model.isFlow ? model.finished : model.studyTime >= model.studyDuration { model.replayStudy() } else { model.studyPaused.toggle() } } label: { Label(model.studyPaused ? "播放" : "暂停",systemImage:model.studyPaused ? "play.fill" : "pause.fill") }.disabled(reduced)
                Button { model.seekStudy(model.studyTime-1.0/30) } label: { Image(systemName:"backward.frame") }.help("前一帧").accessibilityLabel("前一帧").disabled(reduced)
                Button { model.seekStudy(model.studyTime+1.0/30) } label: { Image(systemName:"forward.frame") }.help("后一帧").accessibilityLabel("后一帧").disabled(reduced)
                Spacer()
                Toggle("网格／接触",isOn:$model.studyMesh).toggleStyle(.checkbox)
            }.font(.caption)
            HStack {
                Slider(value:Binding(get:{model.studyTime},set:{model.seekStudy($0)}),in:0...model.studyDuration).accessibilityLabel("短样时间位置").disabled(reduced)
                Text(model.isFlow ? String(format:"%.2f s",model.studyTime) : String(format:"%.2f / %.1f s",model.studyTime,model.studyDuration)).font(.caption.monospacedDigit()).frame(width:105,alignment:.trailing)
            }
            Text(model.isFlow ? (reduced ? "减少动态：整理中静止，成功直接显示结果。" : "时间条仅用于回看已播放片段，不表示任务进度。完成信号为模拟。") : (reduced ? "减少动态：直接显示消字／盖章后的静态结果。" : "暂停后可逐帧检查；网格与橙色接触标记只用于制作检查。")).font(.caption).foregroundStyle(.secondary)
        }.padding(24)
    }
    private var conversation: some View {
        VStack(spacing:0) {
            ScrollView {
                VStack(alignment:.leading,spacing:22) {
                    HStack { Spacer(minLength:60); Text(model.english ? "Help me understand how retrieval and generation work together." : "帮我梳理一下，检索和生成分别负责什么？")
                        .padding(16).background(Color.primary.opacity(0.06),in:RoundedRectangle(cornerRadius:18)).textSelection(.enabled) }
                    if model.waiting {
                        HStack(alignment:.center,spacing:12) {
                            motion(model.settling ? "settle" : "thinking",width:104,height:96)
                                .opacity(model.settling ? 0 : 1).animation(reduced ? nil : .easeOut(duration:0.24),value:model.settling)
                            VStack(alignment:.leading,spacing:8) {
                                Text(model.copy).font(.system(size:15,weight:.medium)).fixedSize(horizontal:false,vertical:true)
                                    .id(model.copy).transition(.opacity)
                                detailsButton
                            }.frame(maxWidth:.infinity,alignment:.leading)
                        }.accessibilityElement(children:.contain)
                    }
                    if model.replied {
                        VStack(alignment:.leading,spacing:14) {
                            Text(model.english ? "Retrieval supplies evidence; generation turns it into an answer." : "检索负责找依据，生成负责把依据组织成回答。")
                                .font(.title3.weight(.semibold))
                            Text(model.english ? "Retrieval selects relevant sources that you can access. Generation uses those sources to explain the answer. Finding a document does not guarantee that the resulting claim is correct." : "检索从资料中找到与你的问题相关、且你有权访问的内容。生成依据这些内容组织解释。找到资料，并不意味着生成的结论就一定正确。")
                            Text(model.english ? "For example, retrieval finds the relevant product manual; generation explains the steps based on that manual." : "例如，回答产品使用问题时，先检索对应版本的说明书，再依据说明书解释具体步骤。两部分都需要检查来源和准确性。")
                        }.lineSpacing(6).textSelection(.enabled)
                        if !model.waiting { detailsButton }
                    }
                    if !model.status.isEmpty { Text(model.status).foregroundStyle(.secondary); Button("重试") {model.restart()} }
                    if model.details { VStack(alignment:.leading,spacing:8) {
                        Text("本次模拟阶段：\(model.stage)")
                        Text("耗时只在此处展示；阶段由试演控制，不调用模型。")
                        TimelineView(.periodic(from:.now,by:1)){t in Text("\(max(0,Int(t.date.timeIntervalSince(model.elapsedStart)))) 秒")}
                    }.font(.caption).foregroundStyle(.secondary).padding(14).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:12)) }
                }.padding(28).frame(maxWidth:820).frame(maxWidth:.infinity)
            }
            HStack { TextField(model.english ? "Ask Mr. B…" : "继续向 Mr. B 提问……",text:$input).textFieldStyle(.plain).focused($inputFocused); Button {model.stop()} label:{Image(systemName:"stop.circle")}.help("停止") }.padding(18).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:18)).padding(.horizontal,24).padding(.bottom,18)
            Divider()
            VStack(alignment:.leading,spacing:10) {
                HStack {
                    Button("重新等待"){model.restart()}; Button("首段正文"){model.respond(reduceMotion: model.reduced || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)}; Button("停止"){model.stop()}; Button("失败"){model.stop(failed:true)}
                    Spacer(); Toggle("长文案",isOn:$model.longCopy).toggleStyle(.checkbox)
                }
                HStack { Picker("模拟阶段",selection:$model.stage) { Text("整理资料").tag("organize");Text("准备回答").tag("answer");Text("公开检索").tag("search");Text("核对依据").tag("verify") }.frame(maxWidth:260)
                    Text("每 6 秒同义渐换；正文不等待动画").font(.caption).foregroundStyle(.secondary)
                }
            }.padding(16)
        }
    }
    private var detailsButton: some View { Button {model.details.toggle()} label:{Label(model.english ? "View progress" : "查看进展",systemImage:model.details ? "chevron.down" : "chevron.right").font(.caption).foregroundStyle(.secondary).padding(.vertical,5).frame(maxWidth:.infinity,alignment:.leading).contentShape(Rectangle())}.buttonStyle(.plain).accessibilityValue(model.details ? "已展开" : "已收起") }
    private var knowledge: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                Text(model.english ? "From notes to knowledge" : "把这份资料，整理成知识").font(.title2.bold())
                Text("新版结算流程 · 隔离模拟，不连接模型或日常数据").font(.caption).foregroundStyle(.secondary)
                Text(model.lines.joined(separator:"\n\n")).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(24).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:18))
                if model.ingestion.outcome != "idle" {
                    Text(ingestionTitle).font(.headline)
                    if model.ingestion.resultAvailable {
                        Text("已保存 \(model.ingestion.count) 张知识卡片（模拟）")
                        HStack { Button("查看知识") { model.ingestion.showResult() }; Button("完整重播") { model.ingestion.replay() } }
                    }
                    if model.ingestion.outcome == "processing" { ingestionSignals }
                }
                if model.ingestion.showingResult {
                    VStack(alignment:.leading,spacing:10) {
                        Text("入库结果 · 隔离样例").font(.headline)
                        ForEach(0..<model.ingestion.count,id:\.self) { i in Label("知识卡片 \(i+1)",systemImage:"rectangle.on.rectangle").padding(.vertical,4) }
                    }.frame(maxWidth:.infinity,alignment:.leading).padding(20).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:16))
                }
                Divider()
                Stepper("本次 \(model.count) 张（模拟）",value:$model.count,in:1...25).disabled(model.ingestion.outcome == "processing")
                HStack {
                    Button("开始整理") { model.beginIngestion() }
                    Button("试演完整版") { model.beginIngestion(compact:false) }
                    Button("试演精简版") { model.beginIngestion(compact:true) }
                }.disabled(model.ingestion.outcome == "processing")
                HStack {
                    Button("重复同一成功信号") { model.ingestion.resolve(id:model.ingestion.id,outcome:"saved") }
                    Button("历史成功信号") { model.ingestion.resolve(id:model.ingestion.id,outcome:"saved",historical:true) }
                    Button("重置首次展示") { model.preferences.removeObject(forKey:"seenFullLineStampV1") }
                }.font(.caption)
                Toggle("模拟动画资源失败",isOn:$model.failedResource).toggleStyle(.checkbox)
                Text("首次默认完整，完整成功演出结束后默认精简；关闭演出不取消整理，保存结果不等待动画。").font(.caption).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth:760).frame(maxWidth:.infinity)
        }
    }
    private var ingestionTitle: String {
        switch model.ingestion.outcome {
        case "saved": return model.english ? "Knowledge saved" : "已加入知识库"
        case "failed": return model.english ? "Could not save" : "保存未成功"
        case "cancelled": return model.english ? "Cancelled" : "已取消整理"
        default: return model.english ? "Mr. B is organizing these notes" : "Mr. B 正在整理这份资料"
        }
    }
    private var ingestionSignals: some View {
        HStack {
            Button("完成并保存（模拟）") { model.ingestion.resolve(id:model.ingestion.id,outcome:"saved") }
            Button("保存失败") { model.ingestion.resolve(id:model.ingestion.id,outcome:"failed") }
            Button("取消整理") { model.ingestion.resolve(id:model.ingestion.id,outcome:"cancelled") }
        }.font(.caption).disabled(model.studyRecording && model.studyPaused)
    }
    private var settlement: some View {
        let runToken = model.ingestion.token
        return VStack(spacing:14) {
            HStack(alignment:.top) {
                VStack(alignment:.leading,spacing:6) {
                    Text(ingestionTitle).font(.title2.bold())
                    Text(model.ingestion.resultAvailable ? (model.english ? "Organized and ready to review." : "整理好了。这部分，值得记住。") : (model.english ? "Your result will appear here." : "把内容收好，再交给你。")).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.ingestion.presented=false } label:{Image(systemName:"xmark").frame(width:28,height:28)}.buttonStyle(.plain).help("关闭演出").keyboardShortcut(.cancelAction)
            }
            MrBDecoratedMotion(configuration:.init(kind:"flow_study",token:model.ingestion.token,dark:model.dark,reduced:reduced,paused:model.studyRecording && model.studyPaused,reviewRecording:model.studyRecording,compact:model.ingestion.compact,flowOutcome:model.ingestion.outcome,flowSignalToken:model.ingestion.signalToken),failed:model.failedResource,onEvent:{ if model.ingestion.token == runToken { model.ingestionEvent($0,reduced:reduced) } })
                .frame(width:504,height:270)
            Text(model.ingestion.compact ? "精简收尾 · 模拟事件" : "完整演出 · 模拟事件").font(.caption).foregroundStyle(.secondary)
            VStack(spacing:14) {
            if model.ingestion.outcome == "processing" { ingestionSignals }
            if model.ingestion.resultAvailable {
                HStack { Label("\(model.ingestion.count) 张知识卡片",systemImage:"rectangle.stack"); Spacer(); Button("完整重播") {model.ingestion.replay()} }.font(.caption)
                HStack { Button(model.english ? "View knowledge" : "查看知识") {model.ingestion.showResult()}; Spacer(); Button(model.english ? "Done" : "完成"){model.ingestion.presented=false}.keyboardShortcut(.defaultAction) }
            } else if model.ingestion.outcome != "processing" {
                HStack { Text("结果未保存，可重新整理。").font(.caption).foregroundStyle(.secondary); Spacer(); Button("重试") {model.beginIngestion(compact:model.ingestion.compact)} }
            }
            }.frame(height:66,alignment:.top)
        }.frame(width:504).padding(28).background(paper)
    }
    private var review: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:18) {
                Text(model.english ? "This review session" : "今天这一轮").font(.title.bold())
                Text("新版复习结算 · 隔离模拟").font(.caption).foregroundStyle(.secondary)
                let eligible = MrBSettlementGate.reviewEligible(formal:true,saved:model.reviewReason != "failed",reason:model.reviewReason,count:model.reviewCount)
                if eligible {
                    motion("review_study",width:480,height:253) { event in if event == "finished" {model.finished=true} }
                    Text(model.english ? "Session complete" : "本轮完成").font(.headline)
                } else {
                    Text(model.reviewCount == 0 ? "本轮没有复习结果。" : model.reviewReason == "paused" ? "已暂停。完成的题目已保存。" : model.reviewReason == "time_limit" ? "本轮时间到了，已完成的题目已保存。" : model.reviewReason == "preview" ? "试一题已结束，不计入正式复习。" : "本题尚未保存，可以重试。").foregroundStyle(.secondary)
                }
                if model.reviewCount > 0 { ForEach(Array([("检索与生成的职责","这次回忆顺利"),("引用与结论的关系","仍需要再练习"),("资料的访问权限","回忆有些吃力")].prefix(model.reviewCount)),id:\.0){row in HStack {Text(row.0);Spacer();Text(row.1).foregroundStyle(.secondary)}.padding(.vertical,9) } }
                Button("关闭总结"){model.enter("等待")}
                Divider()
                Picker("模拟结束原因",selection:$model.reviewReason){Text("全部完成").tag("complete");Text("暂停").tag("paused");Text("时间到").tag("time_limit");Text("试一题").tag("preview");Text("保存失败").tag("failed")}
                Stepper("模拟结果 \(model.reviewCount) 条",value:$model.reviewCount,in:0...3)
                Button("重播本轮"){model.finished=false;model.token += 1}.disabled(!eligible)
                Text("结果与关闭始终可用，演出不改变复习记录。").font(.caption).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth:720).frame(maxWidth:.infinity)
        }
    }
    private var idle: some View {
        VStack(spacing:22) {
            Spacer()
            motion(model.clip,width:260,height:270)
            Text("外表严肃，偶尔藏不住小心思。").font(.headline)
            Spacer()
            Picker("动作",selection:$model.clip){Text("低频混合待机").tag("idle");Text("偷瞄装认真").tag("mr_peek");Text("藏书露角").tag("mr_hide");Text("接到任务").tag("mr_receive");Text("歪身琢磨").tag("mr_ponder");Text("左右权衡").tag("mr_weigh");Text("重新集中").tag("mr_focus");Text("原有阅读").tag("idle_book")}.frame(maxWidth:340)
            HStack { Button("重播动作"){model.stopShowcase();model.token += 1}; Button(model.showcasing ? "停止连播" : "六段动作连播") { if model.showcasing {model.stopShowcase()} else {model.playShowcase()} }.disabled(reduced) }
            Text("原有四类待机保留，新片段之间至少两个原有片段。").font(.caption).foregroundStyle(.secondary)
        }.padding(24)
    }
}

struct MrBDecoratedMotion: View {
    var configuration: MrBConfiguration
    var failed: Bool
    var onEvent:(String)->Void
    @State private var unavailable = false
    var body: some View {
        ZStack {
            MrBMotionView(configuration:configuration,simulateFailure:failed){event in unavailable=event == "failed";onEvent(event)}.id(failed)
                .accessibilityHidden(true)
            if unavailable { VStack(spacing:10){Image(systemName:"rectangle.stack").font(.largeTitle);Text(unavailableCopy).font(.caption)}.foregroundStyle(.secondary) }
        }
    }
    private var unavailableCopy: String {
        if configuration.kind.hasPrefix("reaction_") { return "动画暂不可用，题目与反馈仍可使用" }
        guard configuration.kind == "flow_study" else { return "动画暂不可用，结果已保留" }
        switch configuration.flowOutcome {
        case "saved": return "动画暂不可用，结果已保留"
        case "failed", "cancelled": return "动画暂不可用，请查看处理结果"
        default: return "动画暂不可用，整理状态仍会更新"
        }
    }
}
