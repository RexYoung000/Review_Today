import SwiftUI

@main
struct KnowledgePaperTransitionTests {
    static func main() {
        var motion = KnowledgePresentationTransition()
        let opening = motion.generation
        let closing = motion.close()
        precondition(!motion.finish(opening), "An opening callback cannot undo a close")
        precondition(motion.phase == .closing)
        precondition(motion.finish(closing) && motion.phase == .finished)
        precondition(!motion.finish(closing), "Close completion may run only once")
        motion.settle()
        precondition(motion.phase == .finished)

        var resized = KnowledgePresentationTransition()
        resized.settle()
        precondition(!resized.finish(0) && resized.phase == .reading)
        let token = resized.close()
        resized.settle()
        precondition(!resized.finish(token) && resized.phase == .finished,
                     "Resizing or Reduce Motion during closing invalidates delayed work")
        let viewport = CGSize(width: 800, height: 600)
        precondition(KnowledgePresentationTransition.visibleSource(nil, in: viewport) == nil)
        precondition(KnowledgePresentationTransition.visibleSource(CGRect(x: 20, y: -30, width: 240, height: 72), in: viewport) == nil)
        let visible = CGRect(x: 20, y: 30, width: 240, height: 72)
        precondition(KnowledgePresentationTransition.visibleSource(visible, in: viewport) == visible)
        for height: CGFloat in [392, 560, 680] {
            func bottom(_ depth: CGFloat) -> CGFloat {
                let p = KnowledgeDeckMetrics.stackPlacement(depth: depth, cardHeight: height, paper: true)
                return p.y + height * p.scale
            }
            precondition(abs(bottom(1) - bottom(0) - 8) < 0.001)
            precondition(abs(bottom(2) - bottom(1) - 8) < 0.001)
        }
        print("PASS: interrupted opening/closing, resize, missing/offscreen anchors, thin deck")
    }
}
