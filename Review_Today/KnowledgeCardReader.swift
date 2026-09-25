import SwiftData
import SwiftUI

private struct KnowledgeDisclosureStyle: DisclosureGroupStyle {
    let hint: LocalizedStringKey
    func makeBody(configuration: Configuration) -> some View {
        Header(configuration: configuration, hint: hint)
    }
    private struct Header: View {
        let configuration: DisclosureGroupStyleConfiguration
        let hint: LocalizedStringKey
        @Environment(\.runway) private var runway
        @Environment(\.brandReduceMotion) private var reduced
        @FocusState private var focused: Bool
        var body: some View {
            VStack(alignment: .leading, spacing: 4) {
                Button(action: toggle) {
                    HStack(spacing: 8) {
                        configuration.label
                        Spacer(minLength: 8)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 10, weight: .semibold))
                            .rotationEffect(.degrees(configuration.isExpanded ? 90 : 0))
                            .accessibilityHidden(true)
                    }
                    .frame(maxWidth: .infinity, minHeight: 24, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(InteractionButtonStyle(selected: configuration.isExpanded, focused: focused, padding: 8))
                .background(runway.ink.opacity(0.04), in: RoundedRectangle(cornerRadius: 9))
                .focusable().focusEffectDisabled().focused($focused)
                .onKeyPress(.space) { toggle(); return .handled }
                .onKeyPress(.return) { toggle(); return .handled }
                .accessibilityValue(Text(configuration.isExpanded ? "已展开" : "已收起"))
                .accessibilityHint(Text(hint))
                if configuration.isExpanded { configuration.content }
            }
        }
        private func toggle() {
            withAnimation(reduced ? nil : .easeOut(duration: 0.16)) { configuration.isExpanded.toggle() }
        }
    }
}

struct KnowledgeDeckOverlay: View {
    var items: [Knowledge]
    var sourceFrame: CGRect? = nil
    var titles: [UUID: String]
    @Binding var index: Int
    var coordinator: ReviewCoordinator
    var onClose: () -> Void
    var onAction: (KnowledgeAction, UUID) -> Void

    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway

    @Environment(\.knowledgePaper) private var paper

    var body: some View {
        if paper {
            KnowledgePaperTransition(sourceFrame: sourceFrame, onClose: onClose) { close in
                deck(close: close)
            }
        } else {
            ZStack {
                runway.scrim.ignoresSafeArea().onTapGesture(perform: onClose)
                deck(close: onClose)
            }
        }
    }

    private func deck(close: @escaping () -> Void) -> some View {
        ZStack {
            Color.clear
                .ignoresSafeArea()

            DepthCarousel(items: deckItems, index: $index, title: {
                titles[$0.id] ?? $0.item.title
            }) { wrapper in
                KnowledgeDepthCard(
                    item: wrapper.item,
                    siblings: items,
                    resolvedTitle: titles[wrapper.id] ?? wrapper.item.title,
                    onClose: close,
                    onPreview: {
                        guard let question = KnowledgeLexicon.mainQuestion(for: wrapper.item),
                              KnowledgeLexicon.previewUnavailableReason(for: wrapper.item) == nil
                        else { return }
                        coordinator.startPreview(
                            knowledgeID: wrapper.item.id,
                            questionID: question.id
                        )
                        openWindow(id: "review")
                        close()
                    },
                    onAction: { onAction($0, wrapper.item.id) }
                )
            }

        }
    }

    private var deckItems: [DeckItem] {
        items.map { DeckItem(id: $0.id, item: $0) }
    }


}

private struct DeckItem: Identifiable {
    var id: UUID
    var item: Knowledge
}

private struct KnowledgeDepthCard: View {
    @Environment(\.modelContext) private var reviewContext
    @State private var reviewError: String?

    var item: Knowledge
    var siblings: [Knowledge]
    var resolvedTitle: String
    var onClose: () -> Void
    var onPreview: () -> Void
    var onAction: (KnowledgeAction) -> Void
    @Environment(\.modelContext) private var deletionContext
    @Environment(\.runway) private var runway
    @Environment(\.knowledgePaper) private var paper
    @Environment(\.knowledgePrototype) private var prototype
    @State private var prototypeEnrollment: Bool?
    @State private var prototypeMessage: String?
    @State private var sourceExpanded = false
    @State private var misconceptionsExpanded = false

    private var mainQuestion: Question? { KnowledgeLexicon.mainQuestion(for: item) }
    private var spec: AgentAPI.ScoringSpec? { KnowledgeLexicon.scoring(for: item) }
    private var previewUnavailableReason: String? { KnowledgeLexicon.previewUnavailableReason(for: item) }
    private var cover: [String] {
        spec?.mustCover.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } ?? []
    }
    private var mixups: [String] {
        spec?.commonMisconceptions.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } ?? []
    }
    private var orderHint: String {
        spec?.orderRules.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
    private var pieces: [ExplanationPiece] { KnowledgeLexicon.explanationPieces(for: item) }

    var body: some View {
        GeometryReader { _ in
            VStack(alignment: .leading, spacing: 0) {
                if paper { paperHeader } else { titleBlock }

                ScrollView(.vertical, showsIndicators: true) {
                    readingContent
                        .padding(.horizontal, Runway.section)
                        .padding(.bottom, Runway.section)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                }
                .scrollIndicators(.visible)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                if paper { paperFooter } else { footer }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(runway.card)
        }
        .alert("原型操作", isPresented: Binding(get: { prototypeMessage != nil }, set: { if !$0 { prototypeMessage = nil } })) {
            Button("知道了") { prototypeMessage = nil }
        } message: { Text(prototypeMessage ?? "") }
    }

    private var paperHeader: some View {
        HStack(spacing: 12) {
            Text(KnowledgeLexicon.displayTheme(for: item))
                .font(.caption).foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle()).knowledgeDeckDragSurface()
            Button(action: onClose) {
                Image(systemName: "xmark").font(.system(size: 12, weight: .medium))
                    .frame(width: 28, height: 28).foregroundStyle(.secondary)
            }
            .buttonStyle(InteractionButtonStyle(padding: 0, outline: .capsule))
            .accessibilityLabel("关闭知识详情").keyboardShortcut(.cancelAction)
        }
        .padding(.horizontal, 24).padding(.top, 16).padding(.bottom, 12)
    }

    private var titleBlock: some View {
        HStack(alignment: .top, spacing: Runway.gap) {
            VStack(alignment: .leading, spacing: Runway.space) {
                Text(KnowledgeLexicon.displayTheme(for: item))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(resolvedTitle)
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(runway.ink)
                    .lineSpacing(2)
                    .lineLimit(2)
                    .help(resolvedTitle)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .knowledgeDeckDragSurface()
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.body.weight(.medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(InteractionButtonStyle(padding: 0, outline: .capsule))
            .help("关闭知识详情").accessibilityLabel("关闭知识详情")
            .keyboardShortcut(.cancelAction)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Runway.section)
        .padding(.top, Runway.section)
        .padding(.bottom, Runway.section)
    }

    private var readingContent: some View {
        VStack(alignment: .leading, spacing: paper ? 24 : 28) {
            if paper {
                Text(resolvedTitle).font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(runway.ink).lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
                    .contentShape(Rectangle()).knowledgeDeckDragSurface()
                    .accessibilityAddTraits(.isHeader)
            }
            questionBlock
            detailBlock
            memoryBlock
            sourceBlock
        }
    }

    private var footer: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: Runway.space) {
                if let previewUnavailableReason {
                    Label(previewUnavailableReason, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(Color.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if item.lifecycle == "active" {
                    Toggle("已学过，参与间隔复习", isOn: Binding(get: { enrolled }, set: { enabled in
                        if prototype { prototypeEnrollment = enabled; return }
                        let before = (item.reviewEnrollment, item.studiedAt, item.dueAt)
                        item.setReviewParticipation(enabled)
                        do { try reviewContext.save(); reviewError = nil }
                        catch { reviewContext.rollback(); item.reviewEnrollment = before.0; item.studiedAt = before.1; item.dueAt = before.2; reviewError = "复习设置未保存，请重试。" }
                    })).toggleStyle(.checkbox)
                    if let reviewError { Text(reviewError).font(.caption).foregroundStyle(.orange) }
                }
                HStack(alignment: .center, spacing: Runway.space) {
                    Text(item.lifecycle == "soft_deleted" ? "已移到回收站" : !enrolled ? "仅保存资料 · 未参与复习" : "下次 \(item.dueAt.formatted(date: .abbreviated, time: .omitted))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Menu {
                        KnowledgeActionButtons(lifecycle: item.lifecycle, perform: performAction)
                    } label: {
                        Image(systemName: "ellipsis")
                            .font(.body.weight(.medium))
                            .foregroundStyle(.secondary)
                            .frame(width: 28, height: 28)
                    }
                    .menuStyle(.borderlessButton)
                    if item.lifecycle != "soft_deleted" {
                        RunwayPrimaryButton(
                            title: String(localized: "试一题"),
                            enabled: previewUnavailableReason == nil,
                            action: preview
                        )
                    }
                }
            }
            .padding(.horizontal, Runway.section)
            .padding(.top, 12)
            .padding(.bottom, 32)
        }
    }


    private var enrolled: Bool { prototypeEnrollment ?? item.participatesInReview }

    private func preview() {
        if prototype { prototypeMessage = "这里会打开独立复习窗口。本原型不出题、不调用模型、不写正式复习成绩。" }
        else { onPreview() }
    }
    private func performAction(_ action: KnowledgeAction) {
        if prototype { prototypeMessage = "模拟操作：" + action.title + "。正式知识不会改变。" }
        else { onAction(action) }
    }
    private var enrollmentControl: some View {
        VStack(alignment: .leading, spacing: 4) {
            if item.lifecycle == "active" {
                Toggle("已学过，参与间隔复习", isOn: Binding(get: { enrolled }, set: { enabled in
                    if prototype { prototypeEnrollment = enabled; return }
                    let before = (item.reviewEnrollment, item.studiedAt, item.dueAt)
                    item.setReviewParticipation(enabled)
                    do { try reviewContext.save(); reviewError = nil }
                    catch {
                        reviewContext.rollback()
                        item.reviewEnrollment = before.0; item.studiedAt = before.1; item.dueAt = before.2
                        reviewError = "复习设置未保存，请重试。"
                    }
                })).toggleStyle(.checkbox).font(.system(size: 12))
            }
            Text(item.lifecycle == "soft_deleted" ? "已移到回收站" : !enrolled ? "仅保存资料 · 未参与复习" : "下次 \(item.dueAt.formatted(date: .abbreviated, time: .omitted))")
                .font(.caption).foregroundStyle(.secondary)
            if let reviewError { Text(reviewError).font(.caption).foregroundStyle(.orange) }
        }
    }
    private var paperActions: some View {
        HStack(spacing: 12) {
            Menu {
                KnowledgeActionButtons(lifecycle: item.lifecycle, perform: performAction)
            } label: {
                Image(systemName: "ellipsis").frame(width: 28, height: 28)
            }.menuStyle(.borderlessButton).fixedSize().accessibilityLabel("知识管理")
            if item.lifecycle != "soft_deleted" {
                RunwayPrimaryButton(title: "试一题", enabled: previewUnavailableReason == nil, action: preview)
            }
        }
    }
    private var paperFooter: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 16) {
                enrollmentControl
                Spacer(minLength: 16)
                paperActions
            }.frame(minWidth: 512)
            VStack(alignment: .leading, spacing: 10) {
                enrollmentControl
                HStack { Spacer(); paperActions }
            }
        }
        .safeAreaInset(edge: .top, spacing: 6) {
            if let previewUnavailableReason {
                Text(previewUnavailableReason).font(.caption).foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, 24).padding(.vertical, 16)
        .background(runway.card)
    }

    private var detailBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "详解"))
                .font(paper ? .system(size: 12, weight: .semibold) : .caption)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(pieces.enumerated()), id: \.offset) { _, piece in
                    explanationRow(piece)
                }
            }
        }
    }

    private var questionBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "主问题"))
                .font(.caption)
                .foregroundStyle(.secondary)
            if let mainQuestion {
                Text(mainQuestion.promptText)
                    .font(paper ? .system(size: 15, weight: .medium) : .body.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(String(localized: "这张卡还没有可用的主问题。"))
                    .font(paper ? .system(size: 15) : .callout)
                    .foregroundStyle(Color.orange)
            }
        }
        .padding(paper ? 16 : 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field.opacity(paper ? 0.35 : 0.70), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var memoryBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "判断关键点"))
                .font(paper ? .system(size: 12, weight: .semibold) : .caption)
                .foregroundStyle(.secondary)
            if !orderHint.isEmpty {
                Text(orderHint)
                    .font(paper ? .system(size: 15) : .callout)
                    .foregroundStyle(runway.copy)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if cover.isEmpty && mixups.isEmpty && orderHint.isEmpty {
                Text(String(localized: "先说出学习目标里的限定，再用自己的话讲核心含义。"))
                    .font(paper ? .system(size: 15) : .callout)
                    .foregroundStyle(runway.copy)
            }
            ForEach(Array(cover.enumerated()), id: \.offset) { _, line in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text("•").foregroundStyle(runway.copy).frame(width: 8).accessibilityHidden(true)
                    memoryRow(line)
                }
            }
            if !mixups.isEmpty {
                DisclosureGroup(isExpanded: $misconceptionsExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(Array(mixups.enumerated()), id: \.offset) { index, line in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text("\(index + 1).").monospacedDigit().foregroundStyle(.secondary).frame(minWidth: 18, alignment: .leading)
                                Text(line)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                                .font(paper ? .system(size: 15) : .callout)
                                .foregroundStyle(runway.copy)
                                .lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, Runway.space)
                } label: {
                    HStack(spacing: 6) {
                        Text(String(localized: "常见误区"))
                        Text("\(mixups.count)").monospacedDigit()
                    }
                    .font(.caption)
                    .foregroundStyle(runway.copy)
                }
                .disclosureGroupStyle(KnowledgeDisclosureStyle(hint: "展开或收起常见误区"))
                .padding(.top, Runway.space)
            }
        }
        .padding(paper ? 0 : 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field.opacity(paper ? 0 : 0.70), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var sourceBlock: some View {
        DisclosureGroup(isExpanded: $sourceExpanded) {
            VStack(alignment: .leading, spacing: Runway.gap) {
                HStack {
                    if let locator = sourceLocator {
                        Link(String(localized: "打开来源"), destination: locator)
                            .font(.caption)
                    } else {
                        Text(String(localized: "来自你提交的原文"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }
                let evidence = item.evidenceExcerpt.trimmingCharacters(in: .whitespacesAndNewlines)
                if evidence.isEmpty {
                    Text(String(localized: "没有可核对的原文证据。"))
                        .font(paper ? .system(size: 15) : .callout)
                        .foregroundStyle(Color.orange)
                } else {
                    Text("“\(evidence)”")
                        .font(paper ? .system(size: 15) : .callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(Runway.gap)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(runway.field.opacity(paper ? 0 : 1), in: RoundedRectangle(cornerRadius: Runway.innerRadius, style: .continuous))
                }
            }
            .padding(.top, Runway.space)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: Runway.space) {
                Text(String(localized: "来源证据"))
                if let origin = item.originSessionID, (try? SessionDeletion.contains(origin, context: deletionContext)) == true {
                    Text("原会话已删除").foregroundStyle(.secondary)
                }
            }
            .font(.caption)
            .foregroundStyle(runway.copy)
        }
        .disclosureGroupStyle(KnowledgeDisclosureStyle(hint: "展开或收起来源证据"))
        .tint(runway.ink)
    }

    private var sourceLocator: URL? {
        let locator = item.evidenceLocator.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: locator),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme)
        else { return nil }
        return url
    }

    @ViewBuilder
    private func explanationRow(_ piece: ExplanationPiece) -> some View {
        switch piece.kind {
        case .numbered(let number):
            IconLeadRow {
                Text("\(number)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(width: 18, height: 20)
            } content: {
                Text(piece.text)
                    .font(paper ? .system(size: 15) : .callout)
                    .foregroundStyle(runway.copy)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .bullet:
            IconLeadRow {
                Circle()
                    .fill(runway.copy)
                    .frame(width: 6, height: 6)
                    .padding(.top, 7)
            } content: {
                Text(piece.text)
                    .font(paper ? .system(size: 15) : .callout)
                    .foregroundStyle(runway.copy)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .paragraph:
            Text(piece.text)
                .font(paper ? .system(size: 15) : .callout)
                .foregroundStyle(runway.copy)
                .lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func memoryRow(_ text: String) -> some View {
        // Keep the stored wording intact. Only short, explicit labels get their
        // own column; unstructured prose remains a normal wrapping paragraph.
        if let colon = text.firstIndex(of: "："),
           text[..<colon].count <= 16, !text[..<colon].contains("\n") {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: Runway.gap) {
                    Text(String(text[...colon]))
                        .font(paper ? .system(size: 15, weight: .medium) : .callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .frame(width: 126, alignment: .leading)
                    Text(String(text[text.index(after: colon)...]))
                        .font(paper ? .system(size: 15) : .callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .frame(minWidth: 180, maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(String(text[...colon]))
                        .font(paper ? .system(size: 15, weight: .medium) : .callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                    Text(String(text[text.index(after: colon)...]))
                        .font(paper ? .system(size: 15) : .callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        } else {
            Text(text)
                .font(paper ? .system(size: 15) : .callout)
                .foregroundStyle(runway.copy)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
