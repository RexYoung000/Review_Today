import SwiftUI

struct PrototypeExamPage: View {
    @Bindable var model: PrototypeState
    @Environment(\.runway) private var palette
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack { PrototypeButton(title: "今天", symbol: "chevron.left") { model.page = .today }; Spacer(); PrototypeBadge() }
                VStack(alignment: .leading, spacing: 9) {
                    Text("模拟考").font(.system(size: 32, weight: .bold))
                    Text("换一个角度，看看自己准备得怎么样。").font(.callout).foregroundStyle(.secondary)
                }.padding(.bottom, 6)
                HStack(alignment: .top, spacing: 18) {
                    option("知识测验", eyebrow: "把知识用起来", symbol: "rectangle.stack", detail: "从记住一个概念，\n到独立解释和运用。", topics: "学过的知识 · 理解与应用")
                    option("模拟面试", eyebrow: "把想法说清楚", symbol: "bubble.left.and.bubble.right", detail: "带着目标岗位，\n练习表达与临场回答。", topics: "目标岗位 · 表达与应答")
                }
                RunwayCard(padding: 24) {
                    HStack(alignment: .top, spacing: 20) {
                        Image(systemName: model.examSelection == nil ? "cursorarrow" : "checkmark.circle")
                            .font(.system(size: 22, weight: .light)).frame(width: 30).padding(.top, 3)
                        VStack(alignment: .leading, spacing: 9) {
                            Text(model.examSelection.map { "已选择 · \($0)" } ?? "先选一种练习方式").font(.headline)
                            Text(selectionDetail).font(.callout).foregroundStyle(.secondary).lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                Label("模式预览 · 出题、评分与结果流程尚未开放", systemImage: "info.circle")
                    .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 4)
            }.padding(28).frame(maxWidth: 960).frame(maxWidth: .infinity)
        }
    }
    private var selectionDetail: String {
        switch model.examSelection {
        case "知识测验": "围绕已学内容检验理解，关注能否独立回答、解释与应用。这一页先确认模式选择。"
        case "模拟面试": "围绕岗位与面试情境练习，关注回答的内容、结构与表达。这一页先确认模式选择。"
        default: "想检查知识理解，选知识测验；想练习面试表达，选模拟面试。"
        }
    }
    private func option(_ title: String, eyebrow: String, symbol: String, detail: String, topics: String) -> some View {
        let selected = model.examSelection == title
        return Button { model.examSelection = title } label: {
            RunwayCard(padding: 26) {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(alignment: .top) {
                        Image(systemName: symbol).font(.system(size: 32, weight: .light))
                            .frame(width: 58, height: 64)
                            .background(palette.field.opacity(0.6), in: RoundedRectangle(cornerRadius: 18))
                        Spacer()
                        Image(systemName: selected ? "checkmark.circle.fill" : "circle").font(.system(size: 21, weight: .light))
                            .foregroundStyle(palette.ink.opacity(selected ? 1 : 0.22))
                    }.padding(.bottom, 25)
                    Text(eyebrow).font(.caption).foregroundStyle(.secondary).padding(.bottom, 8)
                    Text(title).font(.system(size: 26, weight: .semibold)).padding(.bottom, 12)
                    Text(detail).font(.callout).foregroundStyle(.secondary).lineSpacing(5).fixedSize(horizontal: false, vertical: true)
                    Text(topics).font(.caption).foregroundStyle(.secondary).padding(.top, 26)
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            .overlay(RoundedRectangle(cornerRadius: Runway.cardRadius).strokeBorder(palette.ink.opacity(selected ? 0.3 : 0), lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: Runway.cardRadius))
        }
        .buttonStyle(InteractionButtonStyle(padding: 0, outline: .rounded(Runway.cardRadius)))
        .modifier(PrototypeKeyboardAction(radius: Runway.cardRadius) { model.examSelection = title })
        .accessibilityLabel(title).accessibilityValue(selected ? "已选择" : "未选择")
        .accessibilityHint(detail.replacingOccurrences(of: "\n", with: ""))
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

struct PrototypeLearningPage: View {
    let item: PrototypeLearningItem
    let back: () -> Void
    let openKnowledge: () -> Void
    @Environment(\.runway) private var palette
    private var question: PrototypeQuestion? { PrototypeQuestion.samples.first { PrototypeLearningItem.sampleID($0.id) == item.id } }
    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack { PrototypeButton(title: "最近学习", symbol: "chevron.left", action: back); Spacer(); PrototypeBadge() }
                    VStack(alignment: .leading, spacing: 12) {
                        Text(item.topics).font(.callout).foregroundStyle(.secondary)
                        Text(item.title).font(.system(size: 30, weight: .bold)).fixedSize(horizontal: false, vertical: true)
                        HStack(spacing: 12) { MetaTag(title: item.mode); Text("\(item.when)学习 · 内容预览").font(.caption).foregroundStyle(.secondary) }
                    }.padding(.bottom, 4)
                    if geometry.size.width >= 820 {
                        HStack(alignment: .top, spacing: 20) { note; nextStep.frame(width: 255) }
                    } else { note; nextStep }
                    Label("合成学习记录 · 正式接回后可在原会话继续", systemImage: "info.circle")
                        .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 4)
                }.padding(28).frame(maxWidth: 960).frame(maxWidth: .infinity)
            }
        }
    }
    private var note: some View {
        RunwayCard(padding: 28) {
            VStack(alignment: .leading, spacing: 23) {
                HStack { Label("上次的摘记", systemImage: "text.book.closed").font(.callout.weight(.medium)); Spacer(); Text("01").font(.system(size: 13, design: .monospaced)).foregroundStyle(.tertiary) }
                Text(question?.answer ?? item.status).font(.system(size: 21, weight: .medium)).lineSpacing(7)
                    .fixedSize(horizontal: false, vertical: true)
                Text(question?.explanation ?? "").font(.callout).foregroundStyle(.secondary).lineSpacing(7)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 9) {
                    Circle().fill(palette.ink.opacity(0.3)).frame(width: 5, height: 5)
                    Text(item.status).font(.caption).foregroundStyle(.secondary)
                }.padding(.top, 4)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
    private var nextStep: some View {
        RunwayCard(padding: 24) {
            VStack(alignment: .leading, spacing: 16) {
                Label("接下来可以想一想", systemImage: "arrow.turn.down.right").font(.callout.weight(.medium))
                Text(question?.question ?? item.status).font(.headline).lineSpacing(6).fixedSize(horizontal: false, vertical: true)
                Text("换个熟悉的例子，用自己的话解释一次。").font(.caption).foregroundStyle(.secondary).lineSpacing(4)
                PrototypeButton(title: "查看知识摘记", symbol: "arrow.up.right", action: openKnowledge).padding(.top, 4)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
