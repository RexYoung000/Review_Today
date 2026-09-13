import AppKit
import SwiftUI

/// A fixed calendar grid needs no per-cell SwiftUI layout negotiation. Native
/// buttons retain normal accessibility, keyboard activation and tooltips.
struct ActivityDayGrid: NSViewRepresentable {
    let days: [TodayActivitySnapshot.Day]
    let size: CGFloat
    let spacing: CGFloat
    let colors: [NSColor]
    let border: NSColor
    var select: (Date) -> Void
    func makeNSView(context: Context) -> Grid { Grid() }
    func updateNSView(_ view: Grid, context: Context) {
        view.update(days: days, size: size, spacing: spacing, colors: colors, border: border, select: select)
    }
    final class Grid: NSView {
        override var isFlipped: Bool { true }
        private(set) var buttons: [DayButton] = []
        func update(days: [TodayActivitySnapshot.Day], size: CGFloat, spacing: CGFloat,
                    colors: [NSColor], border: NSColor, select: @escaping (Date) -> Void) {
            while buttons.count > days.count { buttons.removeLast().removeFromSuperview() }
            while buttons.count < days.count {
                let button = DayButton(); buttons.append(button); addSubview(button)
            }
            for (index, day) in days.enumerated() {
                let button = buttons[index]
                button.frame = NSRect(x: CGFloat(index / 7) * (size + spacing), y: CGFloat(index % 7) * (size + spacing), width: size, height: size)
                button.fill = day.future ? .clear : colors[day.level]
                button.border = day.future ? border.withAlphaComponent(border.alphaComponent * 0.35) : .clear
                button.isEnabled = day.count > 0
                button.toolTip = day.help
                button.setAccessibilityLabel(day.help)
                button.onSelect = { select(day.date) }
                button.needsDisplay = true
            }
        }
    }
    final class DayButton: NSButton {
        var fill = NSColor.clear
        var border = NSColor.clear
        var onSelect: (() -> Void)?
        override init(frame: NSRect) {
            super.init(frame: frame)
            title = ""; isBordered = false; setButtonType(.momentaryChange)
            target = self; action = #selector(activateDay)
            focusRingType = .exterior
            setAccessibilityElement(true)
            setAccessibilityRole(.button)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
        @objc private func activateDay() { guard isEnabled else { return }; onSelect?() }
        override func draw(_ dirtyRect: NSRect) {
            let path = NSBezierPath(roundedRect: bounds, xRadius: 4, yRadius: 4)
            fill.setFill(); path.fill()
            if border.alphaComponent > 0 {
                border.setStroke(); path.lineWidth = 1; path.stroke()
            }
        }
        override var focusRingMaskBounds: NSRect { bounds }
        override func drawFocusRingMask() { NSBezierPath(roundedRect: bounds, xRadius: 4, yRadius: 4).fill() }
    }
}
