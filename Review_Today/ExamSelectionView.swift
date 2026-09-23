import SwiftUI

struct ExamSelectionView: View {
    let back: () -> Void
    @State private var selection: String?
    @Environment(\.runway) private var palette
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack { ReviewActionButton(title: "今天", symbol: "chevron.left", action: back); Spacer() }
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
                        Image(systemName: selection == nil ? "cursorarrow" : "checkmark.circle")
                            .font(.system(size: 22, weight: .light)).frame(width: 30).padding(.top, 3)
                        VStack(alignment: .leading, spacing: 9) {
                            Text(selection.map { "已选择 · \($0)" } ?? "先选一种练习方式").font(.headline)
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
        switch selection {
        case "知识测验": "围绕已学内容检验理解，关注能否独立回答、解释与应用。考试流程尚未开放。"
        case "模拟面试": "围绕岗位与面试情境练习，关注回答的内容、结构与表达。考试流程尚未开放。"
        default: "想检查知识理解，选知识测验；想练习面试表达，选模拟面试。"
        }
    }
    private func option(_ title: String, eyebrow: String, symbol: String, detail: String, topics: String) -> some View {
        let selected = selection == title
        return Button { selection = title } label: {
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
        .modifier(ReviewKeyboardAction(radius: Runway.cardRadius) { selection = title })
        .accessibilityLabel(title).accessibilityValue(selected ? "已选择" : "未选择")
        .accessibilityHint(detail.replacingOccurrences(of: "\n", with: ""))
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
