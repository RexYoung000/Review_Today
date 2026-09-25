import SwiftUI

private struct KnowledgePaperKey: EnvironmentKey { static let defaultValue = false }
private struct KnowledgePrototypeKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    var knowledgePaper: Bool {
        get { self[KnowledgePaperKey.self] }
        set { self[KnowledgePaperKey.self] = newValue }
    }
    var knowledgePrototype: Bool {
        get { self[KnowledgePrototypeKey.self] }
        set { self[KnowledgePrototypeKey.self] = newValue }
    }
}

enum KnowledgeReaderAnchorID: Hashable { case item(UUID), viewport }
struct KnowledgeReaderAnchors: PreferenceKey {
    static let defaultValue: [KnowledgeReaderAnchorID: Anchor<CGRect>] = [:]
    static func reduce(value: inout [KnowledgeReaderAnchorID: Anchor<CGRect>], nextValue: () -> [KnowledgeReaderAnchorID: Anchor<CGRect>]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

/// Completion tokens prevent an interrupted opening from reviving a closed reader.
struct KnowledgePresentationTransition {
    enum Phase { case opening, reading, closing, finished }
    private(set) var phase: Phase = .opening
    private(set) var generation = 0
    mutating func close() -> Int {
        generation += 1; phase = .closing; return generation
    }
    mutating func finish(_ token: Int) -> Bool {
        guard token == generation else { return false }
        switch phase {
        case .opening: phase = .reading
        case .closing: phase = .finished
        default: return false
        }
        return true
    }
    mutating func settle() {
        generation += 1
        phase = (phase == .closing || phase == .finished) ? .finished : .reading
    }
    static func visibleSource(_ frame: CGRect?, in size: CGSize) -> CGRect? {
        guard let frame, frame.width > 1, frame.height > 1,
              CGRect(origin: .zero, size: size).contains(frame) else { return nil }
        return frame
    }
}

/// Only the paper shell changes bounds. Reading text retains its final layout.
struct KnowledgePaperTransition<Content: View>: View {
    var sourceFrame: CGRect?
    var onClose: () -> Void
    @ViewBuilder var content: (@escaping () -> Void) -> Content
    @Environment(\.runway) private var runway
    @Environment(\.colorScheme) private var scheme
    @Environment(\.brandReduceMotion) private var reduced
    @Environment(\.controlActiveState) private var active
    @State private var motion = KnowledgePresentationTransition()
    @State private var progress: CGFloat = 0
    @State private var anchor: CGRect?

    var body: some View {
        GeometryReader { geo in
            let size = KnowledgeDeckMetrics.cardSize(in: geo.size)
            let target = CGRect(x: (geo.size.width - size.width) / 2,
                                y: (geo.size.height - size.height) / 2 - 8,
                                width: size.width, height: size.height)
            let origin = anchor ?? KnowledgePresentationTransition.visibleSource(sourceFrame, in: geo.size)
            ZStack {
                Color.black.opacity((scheme == .dark ? 0.32 : 0.12) * Double(progress))
                    .contentShape(Rectangle())
                    .onTapGesture { dismiss(in: geo.size) }
                content { dismiss(in: geo.size) }
                    .modifier(PaperContentsReveal(progress: progress, morphing: origin != nil))
                    .allowsHitTesting(motion.phase == .reading)
                    .accessibilityHidden(motion.phase != .reading)
                if motion.phase != .reading, let origin {
                    PaperMorph(start: origin,
                               end: target, progress: progress,
                               color: runway.card, shadow: runway.liftShadow)
                        .allowsHitTesting(false).accessibilityHidden(true)
                }
                // Escape works even before the reader's own controls are ready.
                Button("关闭知识详情") { dismiss(in: geo.size) }
                    .keyboardShortcut(.cancelAction).hidden().accessibilityHidden(true)
            }
            .clipped()
            .onAppear {
                anchor = KnowledgePresentationTransition.visibleSource(sourceFrame, in: geo.size)
                if reduced { progress = 1; motion.settle() }
                else {
                    let token = motion.generation
                    withAnimation(.easeOut(duration: anchor == nil ? 0.16 : 0.28)) { progress = 1 }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) { _ = motion.finish(token) }
                }
            }
            .onChange(of: geo.size) { _, _ in settle() }
        }
        .onChange(of: reduced) { _, _ in settle() }
        .onChange(of: active) { _, value in if value != .key { settle() } }
        .onDisappear { motion.settle() }
    }

    private func dismiss(in size: CGSize) {
        guard motion.phase != .closing && motion.phase != .finished else { return }
        anchor = KnowledgePresentationTransition.visibleSource(sourceFrame, in: size)
        let token = motion.close()
        if reduced { _ = motion.finish(token); onClose(); return }
        withAnimation(.easeInOut(duration: anchor == nil ? 0.12 : 0.22)) { progress = 0 }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.22) {
            if motion.finish(token) { onClose() }
        }
    }
    private func settle() {
        motion.settle(); progress = 1
        if motion.phase == .finished { onClose() }
    }
}

private struct PaperMorph: View, Animatable {
    var start: CGRect
    var end: CGRect
    var progress: CGFloat
    var color: Color
    var shadow: Color
    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }
    var body: some View {
        let t = max(0, min(1, progress))
        let width = start.width + (end.width - start.width) * t
        let height = start.height + (end.height - start.height) * t
        RoundedRectangle(cornerRadius: 16 + 8 * t, style: .continuous)
            .fill(color)
            .shadow(color: shadow.opacity(0.45), radius: 8, y: 3)
            .frame(width: width, height: height)
            .position(x: start.midX + (end.midX - start.midX) * t,
                      y: start.midY + (end.midY - start.midY) * t)
            .opacity(Double(1 - max(0, min(1, (t - 0.60) / 0.40))))
    }
}

private struct PaperContentsReveal: AnimatableModifier {
    var progress: CGFloat
    var morphing: Bool
    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }
    func body(content: Content) -> some View {
        content.opacity(Double(max(0, min(1, morphing ? (progress - 0.60) / 0.40 : progress))))
    }
}
