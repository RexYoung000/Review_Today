import AppKit
import SwiftUI

/// Native port of React Bits DepthCarousel: stacked cards on a depth rail
/// with GSAP-like power3.out snaps, drag, wheel, and keyboard.
struct DepthCarousel<Item: Identifiable, Card: View>: View {
    var items: [Item]
    @Binding var index: Int
    var cardWidth: CGFloat = 520
    var cardHeight: CGFloat = 640
    var radius: CGFloat = 24
    var depth: CGFloat = 220
    var spread: CGFloat = 34
    var tilt: CGFloat = 8
    var tiltDirection: CGFloat = 1
    var perspective: CGFloat = 1400
    var visibleCards: Int = 3
    var falloff: CGFloat = 0.12
    var blur: CGFloat = 2
    @ViewBuilder var card: (Item) -> Card

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway
    @State private var pos: CGFloat = 0
    @State private var dragStart: CGFloat?
    @State private var lastDragX: CGFloat = 0
    @State private var lastDragTime: TimeInterval = 0
    @State private var velocity: CGFloat = 0
    @State private var dragging = false
    @State private var scale: CGFloat = 1
    @State private var wheelMonitor: Any?
    @State private var wheelSnap: DispatchWorkItem?

    var body: some View {
        GeometryReader { geo in
            let peek = spread
            let cardW = min(cardWidth, geo.size.width * 0.52)
            let cardH = min(cardHeight, geo.size.height - 72)

            ZStack {
                ForEach(Array(items.enumerated()), id: \.element.id) { i, item in
                    let slot = slot(for: i, peek: peek)
                    card(item)
                        .frame(width: cardW, height: cardH)
                        .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: radius, style: .continuous)
                                .strokeBorder(runway.cardHighlight, lineWidth: 1)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: radius, style: .continuous)
                                .fill(Color.black.opacity(slot.tint))
                                .allowsHitTesting(false)
                        )
                        .shadow(color: runway.liftShadow, radius: 28, y: 14)
                        .blur(radius: reduceMotion ? 0 : slot.blur)
                        .opacity(slot.opacity)
                        .scaleEffect(slot.scale)
                        .offset(x: slot.tx, y: 0)
                        .rotation3DEffect(
                            .degrees(reduceMotion ? 0 : slot.ry),
                            axis: (x: 0, y: 1, z: 0),
                            perspective: 0.18
                        )
                        .zIndex(slot.z)
                        .allowsHitTesting(slot.opacity > 0.05)
                        .onTapGesture {
                            guard !dragging, abs(CGFloat(i) - pos) > 0.4 else { return }
                            setFocus(i, animate: true)
                        }
                }

                if items.count > 1 {
                    arrow(system: "chevron.left", edge: .leading) { navigateBy(-1) }
                    arrow(system: "chevron.right", edge: .trailing) { navigateBy(1) }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(drag)
            .overlay(alignment: .bottom) { dots }
            .onAppear {
                scale = 1
                pos = CGFloat(index)
                startWheelMonitor()
            }
            .onDisappear { stopWheelMonitor() }
            .onChange(of: index) { _, new in
                if abs(CGFloat(new) - pos) > 0.01, !dragging {
                    tween(to: CGFloat(new))
                }
            }
            .onChange(of: items.count) { _, _ in
                pos = CGFloat(min(index, max(items.count - 1, 0)))
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(String(localized: "知识卡片"))
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 16)
            .onChanged { value in
                if dragStart == nil {
                    guard abs(value.translation.width) > abs(value.translation.height) else { return }
                    dragStart = pos
                    lastDragX = value.translation.width
                    lastDragTime = Date.now.timeIntervalSinceReferenceDate
                    velocity = 0
                    dragging = true
                }
                guard dragStart != nil else { return }
                let now = Date.now.timeIntervalSinceReferenceDate
                let dt = max(now - lastDragTime, 0.001)
                let dx = value.translation.width - lastDragX
                velocity = dx / dt
                lastDragX = value.translation.width
                lastDragTime = now
                let stepPx = max(cardWidth * 0.55 * scale, 40)
                pos = (dragStart ?? 0) - value.translation.width / stepPx
            }
            .onEnded { _ in
                guard dragStart != nil else { return }
                let stepPx = max(cardWidth * 0.55 * scale, 40)
                let projected = pos - (velocity * 0.18) / stepPx
                dragStart = nil
                dragging = false
                setFocus(Int(projected.rounded()), animate: true)
            }
    }

    private var dots: some View {
        HStack(spacing: 8) {
            ForEach(items.indices, id: \.self) { i in
                Capsule()
                    .fill(i == index ? runway.ink : Color.primary.opacity(0.22))
                    .frame(width: i == index ? 20 : 7, height: 7)
                    .onTapGesture { setFocus(i, animate: true) }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(runway.card.opacity(0.94), in: Capsule())
        .overlay(Capsule().strokeBorder(runway.hairline, lineWidth: 1))
        .padding(.bottom, 4)
        .opacity(items.count > 1 ? 1 : 0)
    }

    private func arrow(system: String, edge: Alignment, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: system)
                .font(.body.weight(.semibold))
                .foregroundStyle(runway.ink)
                .frame(width: 40, height: 40)
                .background(runway.card.opacity(0.94), in: Circle())
                .shadow(color: runway.liftShadow, radius: 10, y: 4)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: edge)
        .zIndex(3000)
    }

    private func startWheelMonitor() {
        wheelMonitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { event in
            let x = event.hasPreciseScrollingDeltas ? event.scrollingDeltaX : event.scrollingDeltaX * 24
            let y = event.hasPreciseScrollingDeltas ? event.scrollingDeltaY : event.scrollingDeltaY * 24
            if abs(y) >= abs(x) {
                return event
            }
            handleWheel(x)
            return nil
        }
    }

    private func stopWheelMonitor() {
        if let wheelMonitor {
            NSEvent.removeMonitor(wheelMonitor)
        }
        wheelMonitor = nil
        wheelSnap?.cancel()
    }

    private func handleWheel(_ delta: CGFloat) {
        guard items.count > 1 else { return }
        dragging = true
        pos += max(min(delta / (cardWidth * 0.9), 0.6), -0.6)
        wheelSnap?.cancel()
        let work = DispatchWorkItem {
            dragging = false
            setFocus(Int(pos.rounded()), animate: true)
        }
        wheelSnap = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.13, execute: work)
    }

    private func navigateBy(_ step: Int) {
        setFocus(index + step, animate: true)
    }

    private func setFocus(_ raw: Int, animate: Bool) {
        let n = items.count
        guard n > 0 else { return }
        let idx = ((raw % n) + n) % n
        var delta = CGFloat(idx) - pos
        if n > 1 {
            delta = delta.truncatingRemainder(dividingBy: CGFloat(n))
            if delta > CGFloat(n) / 2 { delta -= CGFloat(n) }
            if delta < -CGFloat(n) / 2 { delta += CGFloat(n) }
        }
        tween(to: pos + delta, animate: animate)
        if idx != index { index = idx }
    }

    private func tween(to target: CGFloat, animate: Bool = true) {
        let n = max(items.count, 1)
        if animate && !reduceMotion {
            withAnimation(Runway.depthEase) { pos = target }
        } else {
            pos = target
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + (animate && !reduceMotion ? 0.72 : 0)) {
            var wrapped = pos.truncatingRemainder(dividingBy: CGFloat(n))
            if wrapped < 0 { wrapped += CGFloat(n) }
            pos = wrapped
        }
    }

    private struct Slot {
        var tx: CGFloat
        var ty: CGFloat
        var ry: CGFloat
        var scale: CGFloat
        var opacity: Double
        var blur: CGFloat
        var tint: Double
        var z: Double
    }

    private func slot(for i: Int, peek: CGFloat) -> Slot {
        let n = items.count
        var d = CGFloat(i) - pos
        if n > 1 {
            d = d.truncatingRemainder(dividingBy: CGFloat(n))
            if d < 0 { d += CGFloat(n) }
            if d > CGFloat(n) / 2 { d -= CGFloat(n) }
        }
        let back = max(0, d)
        let shown = abs(d) <= CGFloat(visibleCards) + 0.5
        var opacity = d < 0 ? max(0, 1 + d) : 1
        if !shown { opacity = 0 }
        let brightnessFall = min(max(back * falloff, 0), 0.45)
        let blurPx = blur > 0 ? min(blur, (back / max(1, CGFloat(visibleCards))) * blur) : 0
        return Slot(
            tx: tiltDirection * peek * d,
            ty: 0,
            ry: tiltDirection * tilt * min(max(d, 0), 1),
            scale: max(0.92, 1 - back * 0.025),
            opacity: opacity,
            blur: blurPx,
            tint: brightnessFall,
            z: 2000 - d * 20
        )
    }
}
