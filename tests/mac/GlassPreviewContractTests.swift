import AppKit
import SwiftData
import SwiftUI

@main
struct GlassPreviewContractTests {
    static func luminance(_ color: Color) -> Double {
        let c = NSColor(color).usingColorSpace(.sRGB)!
        func linear(_ x: Double) -> Double { x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4) }
        return 0.2126 * linear(c.redComponent) + 0.7152 * linear(c.greenComponent) + 0.0722 * linear(c.blueComponent)
    }
    static func contrast(_ a: Color, _ b: Color) -> Double {
        let x = luminance(a), y = luminance(b)
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    }
    @MainActor static func main() throws {
        _ = NSApplication.shared
        var environment = EnvironmentValues()
        precondition(!environment.glassPreview, "Daily app must retain the existing appearance")
        precondition(!environment.glassPreviewReduceMotion && !environment.glassPreviewReduceTransparency)
        environment.glassPreviewReduceMotion = true
        environment.glassPreviewReduceTransparency = true
        precondition(environment.previewAwareReduceMotion && environment.previewAwareReduceTransparency)
        for dark in [false, true] {
            let palette = RunwayPalette.glassPreview(dark: dark)
            for surface in [palette.canvas, palette.card, palette.field] {
                precondition(contrast(palette.ink, surface) >= 7)
                precondition(contrast(palette.copy, surface) >= 4.5)
                precondition(contrast(palette.agent, surface) >= 4.5, "Brand text and focus colors must remain legible")
            }
            precondition(palette.agent == palette.plus)
            print("PASS \(dark ? "dark" : "light") brand contrast: \(contrast(palette.agent, palette.canvas))")
        }
        let runtime = try AppRuntime.resolve(["REVIEW_TODAY_M1_UI_FIXTURE": "learning"], bundleID: "Rex.Review-Today.GlassPreview")
        let container = try M1DebugFixture.makeContainer(mode: "learning")
        let context = container.mainContext
        let before = try context.fetchCount(FetchDescriptor<AgentMessage>())
        let settings = try AgentComposerStore.prepare(context)
        settings.agentDraftText = "小样输入保留"
        do { _ = try AgentComposerStore.sendFirst(settings.agentDraftText, context: context, runtime: runtime); preconditionFailure("Preview cannot send") }
        catch { precondition(HarnessAPIError.code(for: error) == "RT.PREVIEW.SEND_DISABLED") }
        let after = try context.fetchCount(FetchDescriptor<AgentMessage>())
        precondition(after == before)
        precondition(settings.agentDraftText == "小样输入保留")
        print("PASS: default-off material, reduction fallback, neutral palette contrast, preview submit isolation")
    }
}
