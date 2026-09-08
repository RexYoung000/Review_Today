import AppKit
import SwiftUI

/// A horizontal, reversible reading gesture over a vertically stacked deck.
struct DepthCarousel<Item: Identifiable, Card: View>: View {
    var items: [Item]
    @Binding var index: Int
    var title: (Item) -> String
    @ViewBuilder var card: (Item) -> Card

    @Environment(\.brandReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway
    @Environment(\.colorScheme) private var colorScheme
    @State private var navigation = KnowledgeDeckNavigation<Item.ID>()

    private var ids: [Item.ID] { items.map(\.id) }

    var body: some View {
        GeometryReader { geometry in
            let size = KnowledgeDeckMetrics.cardSize(in: geometry.size)
            let origin = navigation.originIndex ?? KnowledgeDeckNavigation<Item.ID>.clamped(index, count: items.count)
            let frame = CGRect(x: (geometry.size.width - size.width) / 2,
                               y: (geometry.size.height - size.height) / 2 - 18,
                               width: size.width, height: size.height)

            ZStack {
                ForEach(Array(items.enumerated()), id: \.element.id) { itemIndex, item in
                    let depth = KnowledgeDeckNavigation<Item.ID>.wrapped(itemIndex - origin, count: items.count)
                    if depth < 3 {
                    let position = position(for: depth, size: size)
                    deckCard(item, size: size, depth: position.depth, interactive: depth == 0 && navigation.phase == .idle)
                        .scaleEffect(position.scale, anchor: .top)
                        .offset(x: position.x, y: position.y)
                        .opacity(position.opacity)
                        .zIndex(Double(10 - depth))
                    }
                }

                // A separate returning surface keeps two-card decks reversible without
                // moving their visible back card abruptly from below to the left edge.
                if items.count > 1 {
                    let previous = KnowledgeDeckNavigation<Item.ID>.wrapped(origin - 1, count: items.count)
                    let progress = max(0, min(1, -navigation.progress))
                    deckCard(items[previous], size: size, depth: 0, interactive: false)
                        .offset(x: -(size.width + 80) * (1 - progress))
                        .opacity(min(1, progress * 5))
                        .zIndex(20)
                }
            }
            .frame(width: size.width, height: size.height)
            .position(x: frame.midX, y: frame.midY)
            .frame(width: geometry.size.width, height: geometry.size.height)
            .overlayPreferenceValue(KnowledgeDeckDragRegionKey.self) { anchors in
                GeometryReader { regions in
                    KnowledgeDeckInputSurface(
                        cardFrame: frame,
                        dragRegions: anchors.map { regions[$0] },
                        canNavigate: items.count > 1,
                        begin: beginDrag,
                        change: { translation in updateDrag(translation, width: size.width) },
                        end: { translation, velocity in finishDrag(translation, velocity: velocity, width: size.width) },
                        cancel: cancelMotion,
                        step: navigate
                    )
                }
                .allowsHitTesting(false)
            }
            .overlay(alignment: .trailing) {
                if !items.isEmpty {
                    locator(maxHeight: max(80, size.height - 40))
                        .padding(.trailing, max(4, frame.minX - 40))
                }
            }
            .onChange(of: geometry.size) { _, _ in cancelMotion() }
        }
        .onAppear { synchronize() }
        .onChange(of: ids) { _, _ in synchronize() }
        .onChange(of: index) { _, new in
            guard new != navigation.selectedIndex else { return }
            withoutAnimation { navigation.select(new, ids: ids) }
            publishSelection()
        }
        .onChange(of: reduceMotion) { _, _ in cancelMotion() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(String(localized: "知识卡片"))
    }

    private func deckCard(_ item: Item, size: CGSize, depth: CGFloat, interactive: Bool) -> some View {
        card(item)
            .frame(width: size.width, height: size.height)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(Color.black.opacity(Double(depth) * (colorScheme == .dark ? 0.10 : 0.025)))
                .allowsHitTesting(false))
            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(colorScheme == .dark ? Color.white.opacity(0.12) : Color.black.opacity(0.055), lineWidth: 0.75)
                .allowsHitTesting(false))
            .shadow(color: Color.black.opacity(colorScheme == .dark ? 0.32 : 0.10), radius: 3, y: 3)
            .shadow(color: runway.liftShadow, radius: Runway.shadowBlur, y: Runway.shadowY)
            .allowsHitTesting(interactive)
            .accessibilityHidden(!interactive)
            .transformPreference(KnowledgeDeckDragRegionKey.self) { value in
                if !interactive { value = [] }
            }
    }

    private struct CardPosition {
        var x: CGFloat = 0
        var y: CGFloat = 0
        var scale: CGFloat = 1
        var opacity: Double = 1
        var depth: CGFloat = 0
    }

    private func position(for depth: Int, size: CGSize) -> CardPosition {
        let progress = navigation.progress
        if progress >= 0 {
            if depth == 0 {
                return CardPosition(x: -(size.width + 80) * progress, opacity: Double(1 - max(0, progress - 0.8) * 5))
            }
            let remainingDepth = CGFloat(depth) - progress
            let placement = KnowledgeDeckMetrics.stackPlacement(depth: remainingDepth, cardHeight: size.height)
            return CardPosition(y: placement.y, scale: placement.scale, depth: remainingDepth)
        }
        let depth = CGFloat(depth) - progress
        let placement = KnowledgeDeckMetrics.stackPlacement(depth: depth, cardHeight: size.height)
        return CardPosition(y: placement.y, scale: placement.scale,
                            opacity: Double(max(0, 3 - depth)), depth: depth)
    }

    private func locator(maxHeight: CGFloat) -> some View {
        VStack(spacing: 10) {
            ScrollViewReader { reader in
                ScrollView(.vertical) {
                    VStack(spacing: 2) {
                        ForEach(Array(items.enumerated()), id: \.element.id) { i, item in
                            Button { jump(to: i) } label: {
                                Capsule()
                                    .fill(i == index ? runway.ink : runway.ink.opacity(0.24))
                                    .frame(width: 5, height: i == index ? 22 : 7)
                                    .frame(width: 28, height: 28)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(InteractionButtonStyle(padding: 0, outline: .capsule))
                            .help(title(item))
                            .accessibilityLabel(title(item))
                            .accessibilityValue("\(i + 1) / \(items.count)")
                            .accessibilityAddTraits(i == index ? [.isSelected] : [])
                            .id(item.id)
                        }
                    }
                }
                .scrollIndicators(.hidden)
                .frame(width: 30, height: min(maxHeight - 32, CGFloat(items.count) * 30))
                .onAppear { scrollLocator(reader) }
                .onChange(of: index) { _, _ in scrollLocator(reader) }
                .onChange(of: ids) { _, _ in scrollLocator(reader) }
            }
            Text("\(min(index + 1, items.count)) / \(items.count)")
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(runway.copy)
                .fixedSize()
                .accessibilityLabel("第 \(min(index + 1, items.count)) 张，共 \(items.count) 张")
        }
        .padding(.vertical, 10)
        .frame(minWidth: 38)
    }

    private func scrollLocator(_ reader: ScrollViewProxy) {
        guard items.indices.contains(index) else { return }
        reader.scrollTo(items[index].id, anchor: .center)
    }

    private func synchronize() {
        withoutAnimation { navigation.synchronize(ids: ids, proposedIndex: index) }
        publishSelection()
    }

    private func publishSelection() {
        let selected = navigation.selectedIndex ?? 0
        if index != selected { index = selected }
    }

    private func cancelMotion() {
        withoutAnimation { navigation.cancelMotion() }
        publishSelection()
    }

    private func beginDrag() { withoutAnimation { navigation.beginDrag() } }

    private func updateDrag(_ translation: CGFloat, width: CGFloat) {
        guard !reduceMotion else { return }
        withoutAnimation { navigation.updateDrag(translation: translation, width: width) }
    }

    private func finishDrag(_ translation: CGFloat, velocity: CGFloat, width: CGFloat) {
        settle {
            navigation.endDrag(translation: translation, velocity: velocity, width: width)
        }
    }

    private func navigate(_ direction: Int) {
        withoutAnimation { navigation.cancelMotion() }
        settle { navigation.navigate(direction) }
    }

    private func jump(to target: Int) {
        withoutAnimation { navigation.select(target, ids: ids) }
        publishSelection()
    }

    private func settle(_ change: () -> Void) {
        if reduceMotion {
            withoutAnimation {
                change()
                navigation.finish(generation: navigation.generation)
            }
        } else {
            withAnimation(.easeOut(duration: 0.30)) { change() }
            let generation = navigation.generation
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.31) {
                withoutAnimation { navigation.finish(generation: generation) }
            }
        }
        publishSelection()
    }

    private func withoutAnimation(_ change: () -> Void) {
        var transaction = Transaction()
        transaction.disablesAnimations = true
        withTransaction(transaction, change)
    }
}
