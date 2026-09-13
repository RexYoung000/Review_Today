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
    var titles: [UUID: String]
    @Binding var index: Int
    var coordinator: ReviewCoordinator
    var onClose: () -> Void
    var onAction: (KnowledgeAction, UUID) -> Void

    @Environment(\.openWindow) private var openWindow
    @Environment(\.runway) private var runway

    var body: some View {
        ZStack {
            runway.scrim
                .ignoresSafeArea()
                .onTapGesture(perform: onClose)

            DepthCarousel(items: deckItems, index: $index, title: {
                titles[$0.id] ?? $0.item.title
            }) { wrapper in
                KnowledgeDepthCard(
                    item: wrapper.item,
                    siblings: items,
                    resolvedTitle: titles[wrapper.id] ?? wrapper.item.title,
                    onClose: onClose,
                    onPreview: {
                        guard let question = KnowledgeLexicon.mainQuestion(for: wrapper.item),
                              KnowledgeLexicon.previewUnavailableReason(for: wrapper.item) == nil
                        else { return }
                        coordinator.startPreview(
                            knowledgeID: wrapper.item.id,
                            questionID: question.id
                        )
                        openWindow(id: "review")
                        onClose()
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
    var item: Knowledge
    var siblings: [Knowledge]
    var resolvedTitle: String
    var onClose: () -> Void
    var onPreview: () -> Void
    var onAction: (KnowledgeAction) -> Void
    @Environment(\.modelContext) private var deletionContext
    @Environment(\.runway) private var runway
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
                titleBlock

                ScrollView(.vertical, showsIndicators: true) {
                    readingContent
                        .padding(.horizontal, Runway.section)
                        .padding(.bottom, Runway.section)
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                }
                .scrollIndicators(.visible)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                footer
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(runway.card)
        }
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
        VStack(alignment: .leading, spacing: 28) {
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
                HStack(alignment: .center, spacing: Runway.space) {
                    Text(item.lifecycle == "soft_deleted" ? "已移到回收站" : "下次 \(item.dueAt.formatted(date: .abbreviated, time: .omitted))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Menu {
                        KnowledgeActionButtons(lifecycle: item.lifecycle, perform: onAction)
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
                            action: onPreview
                        )
                    }
                }
            }
            .padding(.horizontal, Runway.section)
            .padding(.top, 12)
            .padding(.bottom, 32)
        }
    }

    private var detailBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "详解"))
                .font(.caption)
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
                    .font(.body.weight(.medium))
                    .foregroundStyle(runway.ink)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(String(localized: "这张卡还没有可用的主问题。"))
                    .font(.callout)
                    .foregroundStyle(Color.orange)
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field.opacity(0.70), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var memoryBlock: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            Text(String(localized: "判断关键点"))
                .font(.caption)
                .foregroundStyle(.secondary)
            if !orderHint.isEmpty {
                Text(orderHint)
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if cover.isEmpty && mixups.isEmpty && orderHint.isEmpty {
                Text(String(localized: "先说出学习目标里的限定，再用自己的话讲核心含义。"))
                    .font(.callout)
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
                                .font(.callout)
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
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(runway.field.opacity(0.70), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
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
                        .font(.callout)
                        .foregroundStyle(Color.orange)
                } else {
                    Text("“\(evidence)”")
                        .font(.callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(Runway.gap)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(runway.field, in: RoundedRectangle(cornerRadius: Runway.innerRadius, style: .continuous))
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
                    .font(.callout)
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
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .paragraph:
            Text(piece.text)
                .font(.callout)
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
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .frame(width: 126, alignment: .leading)
                    Text(String(text[text.index(after: colon)...]))
                        .font(.callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .frame(minWidth: 180, maxWidth: .infinity, alignment: .leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(String(text[...colon]))
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                    Text(String(text[text.index(after: colon)...]))
                        .font(.callout)
                        .foregroundStyle(runway.copy)
                        .lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        } else {
            Text(text)
                .font(.callout)
                .foregroundStyle(runway.copy)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
