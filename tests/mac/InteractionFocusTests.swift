import AppKit
import SwiftUI

@main
struct InteractionFocusTests {
    @MainActor static func main() throws {
        // isFocused can describe a focused ancestor. A shared row style must not
        // consume that environment as if every descendant owned keyboard focus.
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(contentsOf: root.appendingPathComponent("Review_Today/InteractionChrome.swift"), encoding: .utf8)
        precondition(!source.contains("@Environment(\\.isFocused)"),
                     "shared feedback must not broadcast an ancestor's focus to every row")
        let workspace = try String(contentsOf: root.appendingPathComponent("Review_Today/LearningWorkspace.swift"), encoding: .utf8)
        precondition(workspace.contains(".toolbar(removing: .title)") && !workspace.contains(".toolbar(.hidden, for: .windowToolbar)"),
                     "remove duplicate title, not native window controls")
        precondition(workspace.contains(".popover(isPresented: $showSessionTags, arrowEdge: .top)") && workspace.contains("symbol: \"ellipsis\", arrowEdge: .top"),
                     "header popovers must open into the workspace, not above the window")
        let empty = ContextCapacityPresentation(json: nil)
        precondition(empty.fraction == nil && empty.used == nil)
        let unknown = ContextCapacityPresentation(json: "{\"input_tokens\":4721}")
        precondition(unknown.fraction == nil && unknown.headline.contains("上限未知"))
        let local = ContextCapacityPresentation(json: "{\"input_tokens\":64000,\"input_budget\":256000}")
        precondition(local.fraction == 0.25 && local.detail.contains("模型窗口上限未知"))
        let known = ContextCapacityPresentation(json: "{\"input_tokens\":64000,\"input_budget\":256000,\"model_window\":1000000,\"compact_threshold\":220000}")
        precondition(known.fraction == 0.25 && known.headline == "约 64K / 256K", "ring uses effective active input capacity")
        precondition(known.detail.contains("220,000") && known.detail.contains("1,000,000"))
        let legacy = ContextCapacityPresentation(json: "{\"input_tokens\":4721,\"input_budget\":24000,\"model_window\":1000000}")
        precondition(legacy.limit == 24000, "do not relabel a historical request as a new 256K request")
        let full = ContextCapacityPresentation(json: "{\"input_tokens\":200,\"input_budget\":100}")
        precondition(full.fraction == 1 && full.used == 200, "clamp drawing without hiding actual usage")
        precondition(ContextCapacityPresentation(json: "{\"input_tokens\":-1,\"model_window\":0}").fraction == nil)
        _ = NSApplication.shared
        for palette in [RunwayPalette.light, .dark] {
            precondition(focusRows(palette: palette, focusedRow: nil) == [],
                         "selection alone must not paint a keyboard-focus ring")
            precondition(focusRows(palette: palette, focusedRow: 2) == [2],
                         "only the explicitly focused row may have a focus ring, independently of selection")
            precondition(focusRows(palette: palette, focusedRow: 2, enabled: false) == [],
                         "disabled controls cannot advertise keyboard focus")
        }
        print("PASS: ancestor-focus guard, rendered single-row focus independent of selection, light/dark/disabled")
    }

    @MainActor private static func focusRows(palette: RunwayPalette, focusedRow: Int?, enabled: Bool = true) -> [Int] {
        let renderer = ImageRenderer(content:
            VStack(spacing: 10) {
                ForEach(0..<4) { row in
                    Button {} label: { Text("会话 \(row)").frame(width: 180, height: 32) }
                        .buttonStyle(InteractionButtonStyle(selected: row == 0, focused: focusedRow == row, padding: 0))
                }
            }
            .padding(4).background(palette.canvas)
            .environment(\.runway, palette)
            .disabled(!enabled)
        )
        renderer.scale = 1
        guard let image = renderer.cgImage else { preconditionFailure("SwiftUI focus sample failed to render") }
        let bitmap = NSBitmapImageRep(cgImage: image)
        return (0..<4).filter { row in
            // Inspect only the left outline, never text, selection fill, or a checkmark.
            (4..<8).contains { x in
                guard let color = bitmap.colorAt(x: x, y: 4 + row * 42 + 16)?.usingColorSpace(NSColorSpace.sRGB) else { return false }
                return color.alphaComponent > 0.5 && color.greenComponent - color.redComponent > 0.2 && color.blueComponent - color.redComponent > 0.2
            }
        }
    }
}
