import SwiftUI

struct PrototypeReviewPreparation: View {
    @Bindable var model: PrototypeState
    @Environment(\.runway) private var palette
    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack(spacing: 24) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("准备复习").font(.system(size: 30, weight: .bold))
                            Text("先试着想起来，再慢慢巩固。").font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        PrototypeCompanion(model: model).frame(width: 116, height: 102).accessibilityHidden(true)
                    }
                    RunwayCard(padding: 24) {
                        HStack(alignment: .top, spacing: 28) {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("当前到期").font(.callout.weight(.medium)).foregroundStyle(.secondary)
                                HStack(alignment: .firstTextBaseline, spacing: 7) {
                                    Text("\(model.dueQuestions.count)").font(.system(size: 44, weight: .semibold)).monospacedDigit()
                                    Text("个知识点").font(.caption).foregroundStyle(.secondary)
                                }
                                Text("按到期顺序\n跨主题回顾").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                            }.frame(width: 148, alignment: .leading)
                            if model.dueQuestions.isEmpty {
                                Text("目前没有到期内容，先回到今天看看其他安排。").font(.callout).foregroundStyle(.secondary).padding(.top, 22)
                            } else {
                                LazyVGrid(columns: [.init(.flexible(), alignment: .leading), .init(.flexible(), alignment: .leading)], alignment: .leading, spacing: 14) {
                                    ForEach(Array(model.dueQuestions.enumerated()), id: \.element.id) { index, question in
                                        HStack(spacing: 9) {
                                            Text(String(format: "%02d", index + 1)).font(.system(size: 11, design: .monospaced)).foregroundStyle(.tertiary)
                                            Text(question.topic).font(.callout).lineLimit(2)
                                        }.frame(maxWidth: .infinity, minHeight: 30, alignment: .leading)
                                    }
                                }.padding(.top, 2)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                    RunwayCard(padding: 24) {
                        VStack(alignment: .leading, spacing: 18) {
                            HStack { Text("这一轮，按自己的节奏来").font(.headline); Spacer(); Text("随时可以暂停").font(.caption).foregroundStyle(.secondary) }
                            Picker("本轮目标", selection: $model.goal) {
                                ForEach(PrototypeGoal.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                            }.labelsHidden().pickerStyle(.segmented)
                            HStack(alignment: .center, spacing: 20) {
                                if model.goal == .minutes {
                                    Stepper(value: $model.minutes, in: 1...60) { Text("\(model.minutes) 分钟").font(.headline).monospacedDigit() }.frame(width: 150)
                                    Spacer(minLength: 0)
                                    Text("时间到后，完成当前题再收尾").font(.caption).foregroundStyle(.secondary)
                                } else if model.goal == .count {
                                    Stepper(value: $model.count, in: 1...30) { Text("\(model.count) 个知识点").font(.headline).monospacedDigit() }.frame(width: 150)
                                    Spacer(minLength: 0)
                                    Text("本轮最多 \(min(model.count, model.dueQuestions.count)) 个，按到期顺序选取").font(.caption).foregroundStyle(.secondary)
                                } else {
                                    Label("回顾当前全部 \(model.dueQuestions.count) 个到期知识点", systemImage: "checkmark.circle").font(.callout)
                                    Spacer(minLength: 0)
                                    Text("本轮不插入新内容").font(.caption).foregroundStyle(.secondary)
                                }
                            }.frame(minHeight: 30)
                        }
                    }
                    Label("不用背原话，说出自己的理解。需要时，Mr. B 会陪你一起回顾。", systemImage: "bubble.left")
                        .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 4)
                }.padding(.horizontal, 28).padding(.top, 14).padding(.bottom, 24).frame(maxWidth: 880).frame(maxWidth: .infinity)
            }
            HStack(spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("准备好，我们就开始").font(.callout.weight(.medium))
                    Text("原型演示 · 不连接麦克风、不播放声音").font(.caption2).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                PrototypeButton(title: "用文字开始", symbol: "keyboard") { model.start(.text) }.disabled(model.dueQuestions.isEmpty)
                PrototypePrimaryButton(title: "开始语音", enabled: !model.dueQuestions.isEmpty) { model.start(.voice) }
            }.padding(.horizontal, 28).padding(.vertical, 22)
                .background(palette.card.opacity(0.55))
        }
    }
}
