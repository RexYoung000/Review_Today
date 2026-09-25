import Foundation

/// Logical selection and presentation origin are separate so an older animation
/// completion can never overwrite a newer key press, drag, or data update.
struct KnowledgeDeckNavigation<ID: Hashable> {
    enum Phase { case idle, dragging, settling }
    private(set) var ids: [ID] = []
    private(set) var selectedID: ID?
    private(set) var originID: ID?
    private(set) var phase: Phase = .idle
    private(set) var progress: CGFloat = 0
    private(set) var generation = 0

    var selectedIndex: Int? { selectedID.flatMap { ids.firstIndex(of: $0) } }
    var originIndex: Int? { originID.flatMap { ids.firstIndex(of: $0) } }

    static func wrapped(_ index: Int, count: Int) -> Int {
        guard count > 0 else { return 0 }
        return ((index % count) + count) % count
    }

    static func clamped(_ index: Int, count: Int) -> Int { min(max(index, 0), max(count - 1, 0)) }

    mutating func synchronize(ids newIDs: [ID], proposedIndex: Int) {
        let oldIndex = selectedIndex ?? proposedIndex
        ids = newIDs
        if let selectedID, newIDs.contains(selectedID) {
            self.selectedID = selectedID
        } else {
            selectedID = newIDs.isEmpty ? nil : newIDs[Self.clamped(oldIndex, count: newIDs.count)]
        }
        cancelMotion()
    }

    mutating func select(_ index: Int, ids newIDs: [ID]) {
        ids = newIDs
        selectedID = ids.isEmpty ? nil : ids[Self.clamped(index, count: ids.count)]
        cancelMotion()
    }

    mutating func cancelMotion() {
        generation += 1
        originID = selectedID
        progress = 0
        phase = .idle
    }

    mutating func beginDrag() {
        guard ids.count > 1 else { return }
        cancelMotion()
        phase = .dragging
    }

    mutating func updateDrag(translation: CGFloat, width: CGFloat) {
        guard phase == .dragging, width > 0 else { return }
        progress = max(-0.999, min(0.999, -translation / width))
    }

    mutating func endDrag(translation: CGFloat, velocity: CGFloat, width: CGFloat) {
        guard phase == .dragging, ids.count > 1, let originIndex else { return }
        let enoughDistance = abs(translation) >= min(120, max(40, width * 0.20))
        let flick = abs(translation) >= 24 && abs(velocity) >= 700 && translation * velocity > 0
        let step = enoughDistance || flick ? (translation < 0 ? 1 : -1) : 0
        selectedID = ids[Self.wrapped(originIndex + step, count: ids.count)]
        progress = CGFloat(step)
        phase = .settling
        generation += 1
    }

    mutating func navigate(_ direction: Int) {
        guard ids.count > 1, let selectedIndex else { return }
        let step = direction < 0 ? -1 : 1
        originID = selectedID
        selectedID = ids[Self.wrapped(selectedIndex + step, count: ids.count)]
        progress = CGFloat(step)
        phase = .settling
        generation += 1
    }

    mutating func finish(generation expected: Int) {
        guard generation == expected else { return }
        originID = selectedID
        progress = 0
        phase = .idle
    }
}

enum KnowledgeDeckMetrics {
    static func stackPlacement(depth: CGFloat, cardHeight: CGFloat, paper: Bool = false) -> (y: CGFloat, scale: CGFloat) {
        // Compensate for top-anchored scaling so each rear card exposes the same
        // 24 pt bottom edge in both short and tall windows.
        (y: depth * (cardHeight * (paper ? 0.015 : 0.025) + (paper ? 8 : 24)), scale: 1 - depth * (paper ? 0.015 : 0.025))
    }

    static func cardSize(in available: CGSize) -> CGSize {
        CGSize(width: max(1, min(760, available.width - 96)),
               height: max(1, min(680, available.height - 128)))
    }
}
