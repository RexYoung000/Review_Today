import SwiftUI

/// Presentation only. Uses the existing round, results and correction actions unchanged.
struct PrototypeReviewSummary<Correction: View>: View {
    @Bindable var model: PrototypeState
    let close: () -> Void
    @ViewBuilder var correction: () -> Correction
    @Environment(\.runway) private var palette

    private var pendingQuestions: [PrototypeQuestion] {
        let recorded = Set(model.results.map { $0.question.id })
        return model.queue.filter { !recorded.contains($0.id) }
    }

    var body: some View {
        VStack(spacing: 0) {
            GeometryReader { geometry in
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 22) {
                            HStack(alignment: .firstTextBaseline) {
                                Text("本轮小结").font(.system(size: 30, weight: .bold))
                                Spacer(); PrototypeBadge()
                            }
                            if geometry.size.width < 780 {
                                overview
                                HStack(spacing: 12) { metrics }
                            } else {
                                HStack(alignment: .top, spacing: 16) {
                                    overview
                                    LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 12) {
                                        metrics
                                    }.frame(width: 248)
                                }
                            }
                            arrangements
                            if model.correcting {
                                correction().id("summary-correction")
                            }
                        }
                        .padding(24).frame(maxWidth: 1008).frame(maxWidth: .infinity)
                    }
                    .task(id: CorrectionViewport(editing: model.correcting, size: geometry.size)) {
                        guard model.correcting else { return }
                        await Task.yield()
                        guard !Task.isCancelled else { return }
                        proxy.scrollTo("summary-correction", anchor: .bottom)
                    }
                }
            }
            footer
        }
    }

    private var overview: some View {
        RunwayCard(padding: 24) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 0) {
                    Label("这一次回顾", systemImage: "arrow.clockwise")
                        .font(.callout.weight(.medium)).foregroundStyle(.secondary)
                    Spacer(minLength: 18)
                    Text(model.fullSuccess ? "这一轮，回顾完了" : model.summaryReason)
                        .font(.system(size: 26, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                    Text(overviewDetail).font(.callout).foregroundStyle(.secondary).lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true).padding(.top, 9)
                    Spacer(minLength: 18)
                    Text("本轮 \(model.queue.count) 个知识点 · 已处理 \(model.results.count) 个")
                        .font(.caption).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading)
                PrototypeCompanion(model: model).frame(width: model.fullSuccess ? 232 : 142, height: 164)
            }.frame(minHeight: 180)
        }
    }

    private var overviewDetail: String {
        if model.results.isEmpty { return "这一轮还没有留下回答。\n到期的内容，等准备好再回来。" }
        if model.fullSuccess { return "这次的回忆已经记下。\n给记忆一点时间，下次再见。" }
        if model.skipped > 0 || model.unfinished > 0 { return "每一次尝试都算数。\n剩下的内容，仍在到期清单里。" }
        return "这次的回答已经留下。\n还不明确的评价，可以继续核对。"
    }

    @ViewBuilder private var metrics: some View {
        PrototypeMetricCard(title: "已完成", value: model.completed, minimumHeight: 76)
        PrototypeMetricCard(title: "需要帮助", value: model.helped, minimumHeight: 76)
        PrototypeMetricCard(title: "跳过", value: model.skipped, minimumHeight: 76)
        PrototypeMetricCard(title: "未完成", value: model.unfinished, minimumHeight: 76)
    }

    private var arrangements: some View {
        RunwayCard(padding: 20) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("接下来的安排").font(.headline)
                    Spacer()
                    Text("\(model.queue.count) 个知识点").font(.caption).foregroundStyle(.secondary)
                }.padding(.bottom, 12)
                if model.results.isEmpty {
                    Text("本轮还没有记录回答，到期清单保持不变。")
                        .font(.callout).foregroundStyle(.secondary).padding(.bottom, 12)
                }
                ForEach(model.results) { result in
                    arrangementRow(topic: result.question.topic, detail: resultDescription(result),
                                   symbol: resultSymbol(result), arrangement: result.arrangement, correction: result.correction)
                }
                ForEach(pendingQuestions) { question in
                    arrangementRow(topic: question.topic, detail: "尚未作答 · 未评分", symbol: "circle.dashed",
                                   arrangement: "仍在到期清单", correction: nil)
                }
            }
        }
    }

    private func arrangementRow(topic: String, detail: String, symbol: String, arrangement: String, correction: String?) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol).font(.system(size: 15, weight: .medium))
                .frame(width: 34, height: 34)
                .background(palette.field.opacity(0.65), in: RoundedRectangle(cornerRadius: 10))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text(topic).font(.callout.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                if let correction {
                    Text("已纠正：\(correction)").font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
            Text(arrangement).font(.caption.weight(.medium)).fixedSize()
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(palette.field.opacity(0.65), in: Capsule())
                .accessibilityLabel("下次安排：\(arrangement)")
        }.padding(.vertical, 12)
            .accessibilityElement(children: .combine)
    }

    private var footer: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    if let last = model.results.last, !last.rawAnswer.isEmpty {
                        PrototypeButton(title: "纠正最后一次回答", symbol: "pencil") { model.beginCorrection() }
                            .disabled(model.correcting)
                    }
                    if model.results.last?.grade != nil {
                        Menu("调整最后一次评价") {
                            ForEach(["Again", "Hard", "Good", "Easy"], id: \.self) { value in
                                Button(value) { model.changeGrade(value) }
                            }
                        }.menuStyle(.borderlessButton).fixedSize().disabled(model.correcting)
                    }
                    Spacer(minLength: 8)
                    PrototypePrimaryButton(title: "回到今天", action: close)
                }
                Text("原型小结 · 后续日期为示例，不写入正式复习记录。")
                    .font(.caption2).foregroundStyle(.secondary)
            }.padding(.horizontal, 24).padding(.vertical, 14)
                .frame(maxWidth: 1008).frame(maxWidth: .infinity)
        }.background(PaperSurface())
    }

    private func resultSymbol(_ result: PrototypeResult) -> String {
        if result.skipped { return "forward.end" }
        if result.grade == nil { return "questionmark.bubble" }
        if result.helped { return "lightbulb" }
        return result.grade == "Again" ? "arrow.clockwise" : "checkmark"
    }

    private func resultDescription(_ result: PrototypeResult) -> String {
        if result.skipped { return result.grade == nil ? "本次跳过 · 未评分" : result.grade == "Again" ? "答错后跳过 · 保留首次回忆" : "已记录回忆 · 随后跳过" }
        if result.helped { return "借助帮助完成 · 将再次巩固" }
        return result.grade == "Hard" ? "独立答对 · 回忆有些困难" : result.grade == "Easy" ? "手动改判为 Easy" : result.grade == nil ? "评价待澄清" : result.grade == "Again" ? "需要再次巩固" : "独立回忆完成"
    }
}

private struct CorrectionViewport: Equatable {
    let editing: Bool
    let size: CGSize
}
