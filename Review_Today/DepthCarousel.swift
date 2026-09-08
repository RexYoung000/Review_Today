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
    @Environment(\.controlActiveState) private var controlState
    @State private var navigation = KnowledgeDeckNavigation<Item.ID>()
    @State private var locatorHover: Int?
    @State private var scrubbing = false
    @State private var reveal = 1.0

    private var ids: [Item.ID] { items.map(\.id) }

    var body: some View {
        GeometryReader { geometry in
            let size = KnowledgeDeckMetrics.cardSize(in: geometry.size)
            let origin = navigation.originIndex ?? KnowledgeDeckNavigation<Item.ID>.clamped(index, count: items.count)
            let frame = CGRect(x: (geometry.size.width - size.width) / 2,
                               y: (geometry.size.height - size.height) / 2 - 18,
                               width: size.width, height: size.height)

            ZStack {
                ForEach(0..<min(3, items.count), id: \.self) { depth in
                    let itemIndex = KnowledgeDeckNavigation<Item.ID>.wrapped(origin + depth, count: items.count)
                    let position = position(for: depth, size: size)
                    deckCard(items[itemIndex], size: size, depth: position.depth,
                             interactive: depth == 0 && navigation.phase == .idle,
                             contentVisible: depth == 0 || navigation.progress > 0)
                        .scaleEffect(position.scale, anchor: .top)
                        .offset(x: position.x, y: position.y)
                        .opacity(position.opacity * (depth == 0 ? reveal : 1))
                        .zIndex(Double(10 - depth))
                }

                // A separate returning surface keeps two-card decks reversible without
                // moving their visible back card abruptly from below to the left edge.
                if items.count > 1 && navigation.progress < 0 {
                    let previous = KnowledgeDeckNavigation<Item.ID>.wrapped(origin - 1, count: items.count)
                    let progress = max(0, min(1, -navigation.progress))
                    deckCard(items[previous], size: size, depth: 0, interactive: false)
                        .offset(x: -(size.width + 80) * (1 - progress))
                        .opacity(movingCardOpacity(distance: 1 - progress))
                        .zIndex(20)
                }
            }
            .frame(width: size.width, height: size.height)
            .position(x: frame.midX, y: frame.midY)
            .frame(width: geometry.size.width, height: geometry.size.height)
            // Offset does not change layout bounds. Clip the entire moving deck,
            // including its shadows, at the library pane rather than at a card.
            .clipped()
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
                        .padding(.trailing, max(2, frame.minX - 46))
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
        .onChange(of: controlState) { _, state in if state != .key { cancelMotion() } }
        .onDisappear { cancelMotion() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(String(localized: "知识卡片"))
    }

    private func deckCard(_ item: Item, size: CGSize, depth: CGFloat, interactive: Bool, contentVisible: Bool = true) -> some View {
        Group {
            if contentVisible {
                card(item).id(item.id)
                    .background { if interactive && DeckRenderMetrics.enabled { DeckRenderProbe(id: AnyHashable(item.id)) } }
            }
            else { runway.card }
        }
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
                return CardPosition(x: -(size.width + 80) * progress,
                                    opacity: movingCardOpacity(distance: progress))
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

    private func movingCardOpacity(distance: CGFloat) -> Double {
        // Keep a short exploratory drag solid, then fade gently throughout the
        // departure. The returning card uses the same curve in reverse.
        let fraction = max(0, min(1, (distance - 0.08) / 0.92))
        return Double(1 - fraction * fraction * (3 - 2 * fraction))
    }

    private func locator(maxHeight: CGFloat) -> some View {
        let trackHeight = max(44, min(440, maxHeight - 32))
        let position = KnowledgeLocator.y(index: index, height: trackHeight - 20, count: items.count)
        return VStack(alignment: .leading, spacing: 10) {
            Text("\(items.count)").font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(runway.copy).frame(width: 44)
                .accessibilityLabel("共 \(items.count) 张知识卡")
            ZStack(alignment: .topLeading) {
                Capsule().fill(runway.ink.opacity(0.18)).frame(width: 6, height: trackHeight - 12).offset(x: 7, y: 6)
                Capsule().fill(runway.ink).frame(width: scrubbing ? 10 : 8, height: 20).offset(x: scrubbing ? 5 : 6, y: position)
                Text("\(min(index + 1, items.count))").font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(runway.ink).frame(width: 26, height: 20).offset(x: 18, y: position)
            }
            .frame(width: 44, height: trackHeight)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                scrubbing = true
                locatorHover = nil
                jump(to: KnowledgeLocator.index(y: value.location.y - 10, height: trackHeight - 20, count: items.count))
            }.onEnded { value in
                jump(to: KnowledgeLocator.index(y: value.location.y - 10, height: trackHeight - 20, count: items.count))
                scrubbing = false
                if !reduceMotion && abs(value.translation.height) < 3 {
                    reveal = 0.65
                    withAnimation(.easeOut(duration: 0.12)) { reveal = 1 }
                }
            })
            .onContinuousHover { phase in
                switch phase {
                case .active(let point): if !scrubbing { locatorHover = KnowledgeLocator.index(y: point.y - 10, height: trackHeight - 20, count: items.count) }
                case .ended: locatorHover = nil
                }
            }
            .overlay(alignment: .leading) {
                if let candidate = locatorHover, items.indices.contains(candidate) {
                    Text("\(candidate + 1) · " + title(items[candidate]))
                        .font(.caption).foregroundStyle(runway.ink).fixedSize(horizontal: false, vertical: true)
                        .padding(10).frame(width: 220, alignment: .leading)
                        .background(runway.card, in: RoundedRectangle(cornerRadius: 10))
                        .shadow(color: runway.liftShadow, radius: 10, y: 3)
                        .offset(x: -226).allowsHitTesting(false)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("知识卡定位")
            .accessibilityValue("第 \(min(index + 1, items.count)) 张，共 \(items.count) 张" + (items.indices.contains(index) ? "，" + title(items[index]) : ""))
            .accessibilityAdjustableAction { direction in jump(to: min(items.count - 1, max(0, index + (direction == .increment ? 1 : -1)))) }
        }.frame(width: 44)
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
        scrubbing = false; locatorHover = nil; reveal = 1
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
        guard items.indices.contains(target) else { return }
        if navigation.selectedIndex == target && navigation.phase == .idle { return }
        DeckRenderMetrics.begin(items[target].id)
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
