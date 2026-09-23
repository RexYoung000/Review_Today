import SwiftUI

struct ReviewSummaryView<Records: View>: View {
    let summary: ReviewRoundSummary
    let motion: ReviewCompanionState
    let close: () -> Void
    @ViewBuilder let records: () -> Records
    @Environment(\.runway) private var palette
    var body: some View {
        VStack(spacing: 0) {
            GeometryReader { geometry in
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        HStack { Text(summary.preview ? "试题小结" : "本轮小结").font(.system(size: 30, weight: .bold)); Spacer() }
                        if geometry.size.width < 830 {
                            overview
                            HStack(spacing: 12) { metrics }
                        } else {
                            HStack(alignment: .top, spacing: 16) {
                                overview
                                LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 12) { metrics }.frame(width: 248)
                            }
                        }
                        RunwayCard(padding: 22) {
                            VStack(alignment: .leading, spacing: 12) {
                                HStack { Text("接下来的安排").font(.headline); Spacer(); Text("\(summary.rows.count) 个知识点").font(.caption).foregroundStyle(.secondary) }
                                if summary.rows.isEmpty { Text("当前没有到期内容，可以回到今天继续学习。").font(.callout).foregroundStyle(.secondary).padding(.vertical, 12) }
                                ForEach(summary.rows) { row in
                                    HStack(alignment: .top, spacing: 13) {
                                        Image(systemName: row.symbol).font(.system(size: 19, weight: .light))
                                            .frame(width: 34, height: 38).background(palette.field.opacity(0.5), in: RoundedRectangle(cornerRadius: 11))
                                        VStack(alignment: .leading, spacing: 6) {
                                            Text(row.entry.title).font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
                                            Text(row.detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                                        }.frame(maxWidth: .infinity, alignment: .leading)
                                        Text(arrangement(row)).font(.caption).foregroundStyle(.secondary)
                                            .padding(.horizontal, 10).padding(.vertical, 7)
                                            .background(palette.field.opacity(0.5), in: Capsule())
                                    }.padding(.vertical, 9)
                                }
                            }
                        }
                        records()
                    }.padding(24).frame(maxWidth: 1008).frame(maxWidth: .infinity)
                }
            }
            HStack(spacing: 18) {
                Text(summary.preview ? "试题结果不计入正式排期。" : "结果已保存在本机。可展开记录纠正转写或调整本次评价。")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 12)
                ReviewStartButton(title: "回到今天", action: close)
            }.padding(.horizontal, 28).padding(.vertical, 20).background(palette.card.opacity(0.55))
        }
    }
    private var overview: some View {
        RunwayCard(padding: 24) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 0) {
                    Label("这一次回顾", systemImage: "arrow.clockwise").font(.callout.weight(.medium)).foregroundStyle(.secondary)
                    Spacer(minLength: 18)
                    Text(summary.title).font(.system(size: 26, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                    Text(summary.full ? "这次的回忆已经记下。给记忆一点时间，下次再见。" : "每一次尝试都算数。跳过和未完成的内容，保留原有复习安排。")
                        .font(.callout).foregroundStyle(.secondary).lineSpacing(4).fixedSize(horizontal: false, vertical: true).padding(.top, 9)
                    Spacer(minLength: 18)
                    Text("本轮 \(summary.rows.count) 个知识点 · 已处理 \(summary.completed + summary.skipped) 个").font(.caption).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading)
                ReviewCompanion(motion: motion, count: summary.completed).frame(width: summary.full ? 210 : 142, height: 164)
            }.frame(minHeight: 180)
        }
    }
    @ViewBuilder private var metrics: some View {
        ReviewMetricCard(title: "已完成", value: summary.completed)
        ReviewMetricCard(title: "其中需帮助", value: summary.helped)
        ReviewMetricCard(title: "跳过", value: summary.skipped)
        ReviewMetricCard(title: "未完成", value: summary.unfinished)
    }
    private func arrangement(_ row: ReviewRoundSummary.Row) -> String {
        if summary.preview { return "不计入排期" }
        if let date = row.dueAt { return date.formatted(.dateTime.month().day().hour().minute()) }
        return "排期未改动"
    }
}
