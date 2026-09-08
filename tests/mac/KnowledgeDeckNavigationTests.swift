import AppKit
import SwiftUI

@main
struct KnowledgeDeckNavigationTests {
    @MainActor static func main() {
        var deck = KnowledgeDeckNavigation<String>()
        deck.synchronize(ids: ["a", "b", "c", "d"], proposedIndex: 1)
        precondition(deck.selectedID == "b")
        deck.beginDrag()
        deck.updateDrag(translation: -160, width: 800)
        precondition(deck.selectedID == "b" && deck.progress == 0.2, "drag follows the hand before committing selection")
        deck.endDrag(translation: -160, velocity: -200, width: 800)
        precondition(deck.selectedID == "c" && deck.originID == "b", "left swipe raises the next card")
        let oldCompletion = deck.generation
        deck.navigate(-1)
        let latestCompletion = deck.generation
        deck.finish(generation: oldCompletion)
        precondition(deck.selectedID == "b" && deck.phase == .settling, "older animation cannot overwrite a rapid reverse input")
        deck.finish(generation: latestCompletion)
        precondition(deck.originID == "b" && deck.phase == .idle && deck.progress == 0)

        deck.select(0, ids: ["a", "b", "c"])
        deck.navigate(-1)
        precondition(deck.selectedID == "c", "right from first loops to last")
        deck.navigate(1)
        precondition(deck.selectedID == "a", "next from last loops to first")
        deck.beginDrag()
        deck.updateDrag(translation: -160, width: 800)
        deck.updateDrag(translation: 8, width: 800)
        deck.endDrag(translation: 8, velocity: 0, width: 800)
        precondition(deck.selectedID == "a" && deck.progress == 0, "reversing a drag back to its origin cancels it")
        deck.finish(generation: deck.generation)
        deck.beginDrag()
        deck.endDrag(translation: -40, velocity: -950, width: 800)
        precondition(deck.selectedID == "b", "a short deliberate flick advances one card")
        deck.beginDrag()
        deck.endDrag(translation: -40, velocity: 950 * -1, width: 800)
        precondition(deck.selectedID == "c")
        deck.beginDrag()
        deck.endDrag(translation: -40, velocity: 950, width: 800)
        precondition(deck.selectedID == "c", "velocity against the final direction cannot fling a short drag")

        deck.select(1, ids: ["a", "b", "c"])
        deck.beginDrag()
        deck.updateDrag(translation: -80, width: 800)
        deck.synchronize(ids: ["c", "a", "b"], proposedIndex: 1)
        precondition(deck.selectedIndex == 2 && deck.selectedID == "b" && deck.phase == .idle, "reordering preserves identity and cancels stale motion")
        deck.synchronize(ids: ["c", "a"], proposedIndex: 2)
        precondition(deck.selectedID == "a", "deletion selects the nearest surviving position")
        deck.synchronize(ids: [], proposedIndex: 1)
        deck.navigate(1)
        precondition(deck.selectedID == nil && deck.phase == .idle)
        deck.select(99, ids: ["only"])
        deck.beginDrag(); deck.updateDrag(translation: -400, width: 800)
        deck.endDrag(translation: -400, velocity: -1000, width: 800); deck.navigate(-1)
        precondition(deck.selectedID == "only" && deck.progress == 0 && deck.phase == .idle, "single-card input cannot move or animate")
        precondition(KnowledgeDeckMetrics.cardSize(in: CGSize(width: 1100, height: 800)) == CGSize(width: 880, height: 560))
        precondition(KnowledgeDeckMetrics.cardSize(in: CGSize(width: 680, height: 520)) == CGSize(width: 584, height: 408))
        for height: CGFloat in [408, 560] {
            func bottom(_ depth: CGFloat) -> CGFloat {
                let placement = KnowledgeDeckMetrics.stackPlacement(depth: depth)
                return placement.y + height * placement.scale
            }
            precondition(bottom(1) - bottom(0) >= 17.9 && bottom(2) - bottom(1) >= 17.9,
                         "both rear cards must expose a visible bottom edge after top-anchored scaling")
            precondition(bottom(0.5) > bottom(0) && bottom(0.5) < bottom(1),
                         "the next card rises continuously as the top card moves away")
        }

        _ = NSApplication.shared
        let window = DeckTestWindow(contentRect: CGRect(x: -2000, y: -2000, width: 500, height: 400), styleMask: [.titled], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let input = KnowledgeDeckInputView(frame: CGRect(x: 0, y: 0, width: 500, height: 400))
        window.contentView = input
        input.canNavigate = true
        input.cardFrame = CGRect(x: 50, y: 40, width: 360, height: 300)
        input.dragRegions = [CGRect(x: 50, y: 40, width: 360, height: 70)]
        var begins = 0, ends = 0, steps: [Int] = [], moves: [CGFloat] = []
        input.onBegin = { begins += 1 }; input.onEnd = { _, _ in ends += 1 }
        input.onChange = { moves.append($0) }; input.onStep = { steps.append($0) }

        func mouse(_ type: NSEvent.EventType, _ point: CGPoint, _ time: TimeInterval) -> NSEvent {
            NSEvent.mouseEvent(with: type, location: input.convert(point, to: nil), modifierFlags: [], timestamp: time,
                               windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1)!
        }
        _ = input.handle(mouse(.leftMouseDown, CGPoint(x: 200, y: 80), 1))
        precondition(input.handle(mouse(.leftMouseDragged, CGPoint(x: 100, y: 82), 1.1)) == nil)
        precondition(input.handle(mouse(.leftMouseUp, CGPoint(x: 80, y: 82), 1.2)) == nil)
        precondition(begins == 1 && ends == 1 && moves == [-100], "title drag is consumed once with actual following translation")
        _ = input.handle(mouse(.leftMouseDown, CGPoint(x: 200, y: 180), 2))
        precondition(input.handle(mouse(.leftMouseDragged, CGPoint(x: 80, y: 180), 2.1)) != nil)
        _ = input.handle(mouse(.leftMouseUp, CGPoint(x: 80, y: 180), 2.2))
        precondition(begins == 1, "body text selection never starts a deck drag")
        _ = input.handle(mouse(.leftMouseDown, CGPoint(x: 200, y: 80), 3))
        precondition(input.handle(mouse(.leftMouseDragged, CGPoint(x: 202, y: 180), 3.1)) != nil)
        _ = input.handle(mouse(.leftMouseUp, CGPoint(x: 80, y: 180), 3.2))
        precondition(begins == 1, "vertical gesture locks to its original axis")

        func key(_ code: UInt16) -> NSEvent {
            NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 4,
                             windowNumber: window.windowNumber, context: nil, characters: "", charactersIgnoringModifiers: "", isARepeat: false, keyCode: code)!
        }
        precondition(input.handle(key(123)) == nil && input.handle(key(124)) == nil && steps == [-1, 1])
        let text = NSTextView(frame: .zero)
        input.addSubview(text); window.makeFirstResponder(text)
        precondition(input.handle(key(123)) != nil && steps == [-1, 1], "selected text keeps its arrow keys")

        func wheel(_ point: CGPoint, x: CGFloat, y: CGFloat, phase: NSEvent.Phase) -> NSEvent {
            DeckTestWheel(window: window, point: input.convert(point, to: nil), x: x, y: y, phase: phase)
        }
        let cardPoint = CGPoint(x: 200, y: 180)
        precondition(input.handle(wheel(cardPoint, x: 0, y: 30, phase: .began)) != nil)
        precondition(input.handle(wheel(cardPoint, x: 50, y: 1, phase: .changed)) != nil)
        _ = input.handle(wheel(cardPoint, x: 0, y: 0, phase: .ended))
        precondition(begins == 1, "vertical body scrolling never turns into a horizontal card swipe")
        precondition(input.handle(wheel(CGPoint(x: 450, y: 180), x: -100, y: 0, phase: .began)) != nil)
        precondition(begins == 1, "the side locator and surrounding window keep their wheel events")
        precondition(input.handle(wheel(cardPoint, x: -50, y: 0, phase: .began)) == nil)
        precondition(input.handle(wheel(cardPoint, x: -20, y: 0, phase: .changed)) == nil)
        _ = input.handle(wheel(cardPoint, x: 0, y: 0, phase: .ended))
        precondition(begins == 2 && ends == 2 && moves.last == -140, "horizontal card wheel routes one gesture")

        _ = input.handle(wheel(cardPoint, x: -50, y: 0, phase: .began))
        RunLoop.current.run(until: Date().addingTimeInterval(0.20))
        precondition(begins == 3 && ends == 2, "a trackpad pause does not release the gesture")
        _ = input.handle(wheel(cardPoint, x: -20, y: 0, phase: .changed))
        _ = input.handle(wheel(cardPoint, x: 0, y: 0, phase: .ended))
        precondition(begins == 3 && ends == 3, "resuming the same trackpad gesture cannot turn a second card")

        var capturedWheelDeck = KnowledgeDeckNavigation<String>()
        capturedWheelDeck.select(0, ids: ["a", "b", "c"])
        var capturedEnds = 0
        input.onBegin = { capturedWheelDeck.beginDrag() }
        input.onChange = { capturedWheelDeck.updateDrag(translation: $0, width: 360) }
        input.onEnd = { translation, velocity in
            capturedEnds += 1
            capturedWheelDeck.endDrag(translation: translation, velocity: velocity, width: 360)
            capturedWheelDeck.finish(generation: capturedWheelDeck.generation)
        }
        input.onCancel = { capturedWheelDeck.cancelMotion() }
        let outsidePoint = CGPoint(x: 450, y: 180)
        _ = input.handle(wheel(cardPoint, x: -30, y: 0, phase: .began))
        precondition(input.handle(wheel(outsidePoint, x: -30, y: 0, phase: .changed)) == nil)
        precondition(input.handle(wheel(outsidePoint, x: 0, y: 0, phase: .ended)) == nil)
        precondition(capturedWheelDeck.phase == .idle && capturedWheelDeck.selectedID == "b" && capturedEnds == 1,
                     "a captured swipe can finish outside the card and releases navigation")
        _ = input.handle(wheel(cardPoint, x: 30, y: 0, phase: .began))
        _ = input.handle(wheel(cardPoint, x: 30, y: 0, phase: .changed))
        precondition(input.handle(wheel(outsidePoint, x: 0, y: 0, phase: .cancelled)) == nil)
        precondition(capturedWheelDeck.phase == .idle && capturedWheelDeck.selectedID == "b" && capturedEnds == 2,
                     "cancellation outside the card returns to the original selection")
        _ = input.handle(wheel(cardPoint, x: -50, y: 0, phase: .began))
        _ = input.handle(wheel(cardPoint, x: 0, y: 0, phase: .ended))
        precondition(capturedWheelDeck.phase == .idle && capturedWheelDeck.selectedID == "c" && capturedEnds == 3,
                     "a fresh swipe works after an outside cancellation")
        _ = input.handle(wheel(cardPoint, x: -30, y: 0, phase: .began))
        precondition(input.handle(wheel(outsidePoint, x: -30, y: 0, phase: .began)) != nil)
        precondition(capturedWheelDeck.phase == .idle && capturedEnds == 3,
                     "a new gesture outside the card is not captured even after an unfinished swipe")

        var lifecycleDeck = KnowledgeDeckNavigation<String>()
        lifecycleDeck.select(0, ids: ["a", "b"])
        var cancels = 0
        input.onBegin = { lifecycleDeck.beginDrag() }
        input.onChange = { lifecycleDeck.updateDrag(translation: $0, width: 360) }
        input.onEnd = { _, _ in ends += 1 }
        input.onCancel = { cancels += 1; lifecycleDeck.cancelMotion() }
        func startNativeDrag(_ timestamp: TimeInterval) {
            _ = input.handle(mouse(.leftMouseDown, CGPoint(x: 250, y: 80), timestamp))
            _ = input.handle(mouse(.leftMouseDragged, CGPoint(x: 150, y: 80), timestamp + 0.05))
            precondition(lifecycleDeck.phase == .dragging)
        }
        startNativeDrag(10)
        NotificationCenter.default.post(name: NSWindow.didResignKeyNotification, object: window)
        precondition(lifecycleDeck.phase == .idle && lifecycleDeck.progress == 0 && cancels == 1,
                     "losing the key window resets the real deck state after a captured drag")
        _ = input.handle(mouse(.leftMouseDown, CGPoint(x: 200, y: 180), 11))
        _ = input.handle(mouse(.leftMouseUp, CGPoint(x: 100, y: 180), 11.1))
        precondition(ends == 3 && lifecycleDeck.selectedID == "a", "a later body click cannot finish an abandoned drag")
        startNativeDrag(12)
        NotificationCenter.default.post(name: NSApplication.didResignActiveNotification, object: NSApplication.shared)
        precondition(lifecycleDeck.phase == .idle && cancels == 2, "switching applications cancels the captured mouse gesture")
        _ = input.handle(wheel(cardPoint, x: -50, y: 0, phase: []))
        precondition(lifecycleDeck.phase == .dragging)
        NotificationCenter.default.post(name: NSWindow.didResignKeyNotification, object: window)
        RunLoop.current.run(until: Date().addingTimeInterval(0.20))
        precondition(lifecycleDeck.phase == .idle && ends == 3 && cancels == 3,
                     "deactivation cancels the pending wheel completion instead of flipping later")
        startNativeDrag(14)
        input.dispose()
        precondition(lifecycleDeck.phase == .dragging, "teardown does not mutate SwiftUI state synchronously")
        RunLoop.current.run(until: Date().addingTimeInterval(0.02))
        precondition(lifecycleDeck.phase == .idle && cancels == 4, "teardown reconciles the deck on the next main-loop turn")
        input.dispose(); window.close()
        print("PASS: reversible deck selection, following drag, rapid stale-completion rejection, wrap, snapback, flick, data reconciliation, single/empty, dimensions, native title/body/axis/key/text/wheel scope, trackpad pause, key/app loss and deferred teardown cancellation")
    }
}

private final class DeckTestWindow: NSWindow { override var isKeyWindow: Bool { true } }

private final class DeckTestWheel: NSEvent {
    private let target: NSWindow
    private let point: CGPoint
    private let x: CGFloat
    private let y: CGFloat
    private let eventPhase: NSEvent.Phase
    init(window: NSWindow, point: CGPoint, x: CGFloat, y: CGFloat, phase: NSEvent.Phase) {
        target = window; self.point = point; self.x = x; self.y = y; eventPhase = phase
        super.init()
    }
    required init?(coder: NSCoder) { fatalError("not used") }
    override var type: NSEvent.EventType { .scrollWheel }
    override var window: NSWindow? { target }
    override var locationInWindow: NSPoint { point }
    override var scrollingDeltaX: CGFloat { x }
    override var scrollingDeltaY: CGFloat { y }
    override var hasPreciseScrollingDeltas: Bool { true }
    override var phase: NSEvent.Phase { eventPhase }
    override var momentumPhase: NSEvent.Phase { [] }
    override var timestamp: TimeInterval { 5 }
}
