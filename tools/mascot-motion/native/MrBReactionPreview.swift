import SwiftUI

struct MrBReactionPreview: View {
    @Bindable var model: MrBPreviewModel
    var reduced: Bool
    private let kinds=["reaction_approve","reaction_encourage","reaction_guide"]
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:18) {
                Text("三种回应，先看动作。").font(.title2.bold())
                Text("同一取景与尺寸 · 无评分、无音效的隔离对照").font(.caption).foregroundStyle(.secondary)
                HStack(spacing:8) {
                    ForEach(Array(kinds.enumerated()),id:\.element) { index,kind in
                        VStack(spacing:8) {
                            MrBMotionView(configuration:.init(kind:kind,token:model.token,dark:model.dark,reduced:reduced,paused:model.studyPaused,seekTime:model.studySeek,seekToken:model.studySeekToken,debugMesh:model.studyMesh,reviewRecording:model.studyRecording),onEvent:{ event in
                                if event == "finished" { model.reactionsCompleted.insert(kind); if model.reactionsCompleted.count==3 { model.finished=true;model.studyPaused=true } }
                            },onTime:{ if index==0 {model.studyTime=$0} })
                                .accessibilityHidden(true).aspectRatio(350.0/340,contentMode:.fit)
                            Text(model.reactionLabels ? ["认可","鼓励","一起再看"][index] : ["A","B","C"][index]).font(.caption).foregroundStyle(.secondary)
                        }.frame(maxWidth:.infinity)
                    }
                }
                HStack {
                    Button("一起重播"){model.replayReactions()}
                    Button(model.studyPaused ? "播放" : "暂停") {if model.finished {model.replayReactions()} else {model.studyPaused.toggle()}}.disabled(reduced)
                    Button {model.seekStudy(model.studyTime-1/30.0)} label:{Image(systemName:"backward.frame")}.help("前一帧").accessibilityLabel("前一帧").disabled(reduced)
                    Button {model.seekStudy(model.studyTime+1/30.0)} label:{Image(systemName:"forward.frame")}.help("后一帧").accessibilityLabel("后一帧").disabled(reduced)
                }
                Slider(value:Binding(get:{model.studyTime},set:{model.seekStudy($0)}),in:0...3.2).disabled(reduced).accessibilityLabel("三段共同时间")
                HStack {Toggle("显示动作含义",isOn:$model.reactionLabels);Toggle("网格／接触",isOn:$model.studyMesh)}.toggleStyle(.checkbox).font(.caption)
                Text(reduced ? "减少动态：显示各自的代表姿态。" : "先尝试分辨动作，再打开含义对照。能否理解情绪仍待视觉验收。").font(.caption).foregroundStyle(.secondary)
                Button("放进答题反馈页"){model.enter("答题反馈")}
            }.padding(24)
        }
    }
}

struct MrBAnswerPreview: View {
    @Bindable var model: MrBPreviewModel
    var reduced: Bool
    @FocusState private var focused: Bool
    private var answer: MrBAnswerSession {model.answerSession}
    private var en: Bool {model.english}
    private func submit() {
        guard let id=answer.begin() else{return}
        Task {try? await Task.sleep(for:.milliseconds(650));answer.resolve(id:id)}
    }
    var body: some View {
        @Bindable var answer=model.answerSession
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                Text(en ? "Review a question" : "试着回忆一下").font(.title2.bold())
                Text(en ? "Isolated answer rehearsal · simulated assessment" : "单题反馈布局试演 · 判断与保存均为模拟").font(.caption).foregroundStyle(.secondary)
                Text(en ? "How do retrieval and generation work together?" : "检索和生成分别负责什么？").font(.title2.weight(.semibold)).textSelection(.enabled)
                if answer.phase == "asking" || answer.phase == "failed" {
                    TextField(en ? "Explain it in your own words" : "用自己的话回答",text:$answer.text,axis:.vertical).textFieldStyle(.plain).lineLimit(3...6).padding(16).background(Color.primary.opacity(0.05),in:RoundedRectangle(cornerRadius:14)).focused($focused)
                    Button(en ? "I'm done" : "我答完了",action:submit).disabled(answer.text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty).keyboardShortcut(.return,modifiers:.command)
                } else {
                    Text(answer.text).foregroundStyle(.secondary).textSelection(.enabled)
                }
                if answer.phase == "judging" {Text(en ? "Mr. B is checking this answer" : "Mr. B 正在核对这次回答").foregroundStyle(.secondary)}
                if answer.phase == "failed" {Text(en ? "Assessment failed. Your answer is still here." : "这次没能完成判断，回答还在，可以重试。").foregroundStyle(.secondary)}
                HStack(alignment:.center,spacing:14) {
                    MrBDecoratedMotion(configuration:.init(kind:answer.kind,token:answer.token,dark:model.dark,reduced:reduced,reviewRecording:model.studyRecording),failed:model.failedResource,onEvent:{event in if event == "finished" && answer.hasFeedback {model.finished=true}})
                        .frame(width:190,height:184).accessibilityHidden(true)
                    if answer.hasFeedback {
                        VStack(alignment:.leading,spacing:10) {
                            Text(answer.headline(english:en)).font(.headline)
                            Text(answer.explanation(english:en)).fixedSize(horizontal:false,vertical:true)
                            Text(en ? "Retrieval finds evidence; generation builds an answer from it." : "检索找到相关资料；生成依据这些资料组织回答。")
                                .padding(12).background(Color.primary.opacity(answer.assessment=="again" ? 0.09 : 0.045),in:RoundedRectangle(cornerRadius:10))
                        }.frame(maxWidth:.infinity,alignment:.leading).textSelection(.enabled)
                    } else {Text(en ? "Mr. B's response appears here after assessment." : "判断后，Mr. B 会在这里回应。") .foregroundStyle(.secondary).frame(maxWidth:.infinity,alignment:.leading)}
                }
                if answer.hasFeedback {
                    VStack(alignment:.leading,spacing:4) {
                        Text("\(en ? "Assessment" : "模拟判断")：\(answer.label(answer.assessment,en:en))")
                        if answer.adopted != answer.assessment {Text("\(en ? "Changed to" : "已改为")：\(answer.label(answer.adopted,en:en))")}
                    }.font(.caption).foregroundStyle(.secondary)
                    if answer.phase != "saved" {
                        HStack {
                            Button(en ? "Use this assessment" : "采用这个判断"){answer.save()}
                            Menu(en ? "Change assessment" : "改判") {ForEach(["again","hard","good"],id:\.self) {grade in Button(answer.label(grade,en:en)){answer.adopted=grade}}}
                        }
                    } else {Label(en ? "Saved in this rehearsal" : "已记录本题（模拟）",systemImage:"checkmark.circle").font(.caption)}
                    Button(en ? "Next question" : "下一题（模拟）"){answer.next();focused=true}.disabled(answer.phase != "saved")
                }
                Divider()
                Picker("模拟评估",selection:$answer.scenario){Text("回答顺利").tag("good");Text("费力／提示后").tag("hard");Text("需要再看").tag("again")}.disabled(answer.phase == "judging")
                Button("填入当前样例并试答") {
                    answer.next()
                    answer.text = answer.scenario == "again" ? "检索和生成都在直接生成答案。" : answer.scenario == "hard" ? "提示后想起来了：检索找资料，生成依据资料组织回答。" : "检索找到相关资料，生成依据资料组织回答。"
                    submit()
                }.disabled(answer.phase == "judging")
                HStack {Toggle("模拟判断失败",isOn:$answer.fail);Toggle("模拟动画失败",isOn:$model.failedResource)}.toggleStyle(.checkbox).font(.caption)
                Button("重新试答"){answer.next();focused=true}
                Text("先选择模拟评估再提交；不会根据输入调用模型或写入复习记录。三个动作不循环，采用与改判不重播。").font(.caption).foregroundStyle(.secondary)
            }.padding(24).frame(maxWidth:760).frame(maxWidth:.infinity)
        }
    }
}
