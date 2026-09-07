import AppKit
import SwiftUI

/// Real AppKit window controls inside the sidebar; the surrounding space drags the window.
struct SidebarWindowControls: NSViewRepresentable {
    func makeNSView(context: Context) -> Controls { Controls() }
    func updateNSView(_ view: Controls, context: Context) {}

    final class Controls: NSView {
        private var buttons: [NSButton] = []
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            buttons.forEach { $0.removeFromSuperview() }; buttons.removeAll()
            guard let window else { return }
            let types: [NSWindow.ButtonType] = [.closeButton, .miniaturizeButton, .zoomButton]
            let actions = [#selector(NSWindow.performClose(_:)), #selector(NSWindow.miniaturize(_:)), #selector(NSWindow.toggleFullScreen(_:))]
            for (type, action) in zip(types, actions) {
                guard let button = NSWindow.standardWindowButton(type, for: window.styleMask) else { continue }
                button.target = window; button.action = action
                addSubview(button); buttons.append(button)
            }
            needsLayout = true
        }
        override func layout() {
            super.layout()
            for (index, button) in buttons.enumerated() {
                button.setFrameOrigin(NSPoint(x: CGFloat(index) * 22, y: (bounds.height - button.frame.height) / 2))
            }
        }
        override var mouseDownCanMoveWindow: Bool { true }
        override func mouseDown(with event: NSEvent) {
            if event.clickCount == 2 { window?.zoom(nil) }
            else { window?.performDrag(with: event) }
        }
    }
}
