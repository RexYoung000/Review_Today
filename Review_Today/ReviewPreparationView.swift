import SwiftData
import SwiftUI

struct ReviewPreparationView: View {
    @Bindable var controller: ReviewController
    let coordinator: ReviewCoordinator
    let motion: ReviewCompanionState
    let start: (Bool) -> Void
    @Query private var knowledge: [Knowledge]
    @Query private var settings: [AppSettings]
    @Environment(\.runway) private var palette
    private var items: [Knowledge] {
        coordinator.mode == "preview" ? knowledge.filter { coordinator.knowledgeIDs.contains($0.id) } : ReviewQueue.ordered(knowledge, developerMode: settings.first?.developerMode == true)
    }
    private var titles: [String] {
        if let resumable = controller.resumable { return Array(ReviewLedger.queue(resumable).dropFirst(resumable.currentIndex)).map(\.title) }
        return items.map { KnowledgeLexicon.keyword(for: $0, clipped: false) }
    }
    private var count: Int { titles.count }
    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack(spacing: 24) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(controller.resumable != nil ? "接着上次，继续回顾" : coordinator.mode == "preview" ? "先试一题" : "准备一轮复习")
                                .font(.system(size: 30, weight: .bold))
                            Text(coordinator.mode == "preview" ? "这一题不计入正式复习与排期。" : "不用背原话，说出你还记得的部分。")
                                .font(.callout).foregroundStyle(.secondary)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        ReviewCompanion(motion: motion).frame(width: 116, height: 102)
                    }
                    RunwayCard(padding: 24) {
                        HStack(alignment: .top, spacing: 24) {
                            VStack(alignment: .leading, spacing: 12) {
                                Text(coordinator.mode == "preview" ? "试题范围" : controller.resumable == nil ? "当前到期" : "本轮剩余").font(.callout.weight(.medium))
                                HStack(alignment: .firstTextBaseline, spacing: 6) {
                                    Text("\(count)").font(.system(size: 44, weight: .semibold)).monospacedDigit()
                                    Text("个知识点").font(.caption).foregroundStyle(.secondary)
                                }
                                Text(coordinator.mode == "preview" ? "不改变正式排期" : controller.resumable == nil ? "优先回顾逾期内容" : "沿用上次的固定清单").font(.caption).foregroundStyle(.secondary)
                            }.frame(width: 148, alignment: .leading)
                            VStack(alignment: .leading, spacing: 12) {
                                if titles.isEmpty { Text("目前没有可复习的内容。加入复习并到期后，就会出现在这里。").font(.callout).foregroundStyle(.secondary) }
                                ForEach(Array(titles.prefix(6).enumerated()), id: \.offset) { index, title in
                                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                                        Text(String(format: "%02d", index + 1)).font(.caption.monospacedDigit()).foregroundStyle(.tertiary)
                                        Text(title).font(.callout).lineLimit(2)
                                    }
                                }
                                if count > 6 { Text("还有 \(count - 6) 个知识点").font(.caption).foregroundStyle(.secondary) }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    if coordinator.mode != "preview", controller.resumable == nil {
                        RunwayCard(padding: 24) {
                            VStack(alignment: .leading, spacing: 18) {
                                HStack { Text("这一轮，按自己的节奏来").font(.headline); Spacer(); Text("随时可以暂停").font(.caption).foregroundStyle(.secondary) }
                                Picker("本轮目标", selection: $controller.goal) {
                                    Text("全部到期").tag("due"); Text("按时间").tag("minutes"); Text("按数量").tag("count")
                                }.pickerStyle(.segmented).labelsHidden()
                                if controller.goal == "due" {
                                    Label("回顾当前全部 \(count) 个知识点，本轮不插入新内容", systemImage: "checkmark.circle").font(.callout)
                                } else {
                                    Stepper(value: $controller.goalValue, in: 1...100) {
                                        Text(controller.goal == "minutes" ? "\(controller.goalValue) 分钟" : "\(controller.goalValue) 个知识点").font(.callout)
                                    }
                                    Text(controller.goal == "minutes" ? "时间到后，处理完当前题再收尾。" : "这轮最多复习 \(min(count, controller.goalValue)) 个知识点。")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Text("需要时可以问清题目、要一点提示，或请 Mr. B 陪你重新看一遍。").font(.caption).foregroundStyle(.secondary)
                }.padding(.horizontal, 28).padding(.top, 18).padding(.bottom, 24).frame(maxWidth: 880).frame(maxWidth: .infinity)
            }
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 18) {
                    Text("准备好，我们就开始").font(.callout.weight(.medium)); Spacer(minLength: 0)
                    ReviewActionButton(title: controller.resumable == nil ? "用文字开始" : "用文字继续", symbol: "keyboard") { start(false) }.disabled(count == 0)
                    ReviewStartButton(title: controller.resumable == nil ? "开始语音" : "继续语音", enabled: count > 0) { start(true) }
                }
                Text("开始语音后才连接麦克风，音频由阿里云处理。本机保留文字与结果，不保留录音回放。")
                    .font(.caption2).foregroundStyle(.secondary)
            }.padding(.horizontal, 28).padding(.vertical, 20).background(palette.card.opacity(0.55))
        }
    }
}
