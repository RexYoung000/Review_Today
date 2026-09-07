import AppKit
import SwiftUI
import SwiftData

@main struct BrandMaterialContractTests {
    static func luminance(_ color: Color) -> Double {
        let c = NSColor(color).usingColorSpace(.sRGB)!
        func l(_ x: Double) -> Double { x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4) }
        return 0.2126*l(c.redComponent)+0.7152*l(c.greenComponent)+0.0722*l(c.blueComponent)
    }
    static func contrast(_ a: Color,_ b: Color) -> Double { let x=luminance(a),y=luminance(b);return (max(x,y)+0.05)/(min(x,y)+0.05) }
    static func neutral(_ color: Color) -> Bool { let c=NSColor(color).usingColorSpace(.sRGB)!;return abs(c.redComponent-c.greenComponent)<0.001 && abs(c.redComponent-c.blueComponent)<0.001 }
    @MainActor static func main() throws {
        _ = NSApplication.shared
        let environment=EnvironmentValues()
        precondition(!environment.brandMaterialTrial && !environment.brandTrialStill)
        precondition(MascotMotionConfiguration().material == "current")
        precondition(!RunwayPalette.light.monochrome && !RunwayPalette.dark.monochrome)
        for dark in [false,true] {
            let p=RunwayPalette.monochromeTrial(dark:dark)
            for surface in [p.canvas,p.card,p.field] {
                precondition(neutral(surface));precondition(contrast(p.ink,surface)>=4.5);precondition(contrast(p.copy,surface)>=4.5)
                precondition(contrast(p.controlBorder,surface)>=3);precondition(contrast(p.agent,surface)>=3)
            }
            for color in [p.agent,p.plus,p.information,p.secondaryInformation,p.decorativeAccent,p.history,p.hoverWash] { precondition(neutral(color)) }
            precondition(contrast(p.action,p.onAction)>=7)
            let m=MascotMaterialPalette.theme(dark:dark)
            precondition(m.accent[0]==m.accent[1] && m.accent[1]==m.accent[2])
            precondition(m.wave[0]==m.wave[1] && m.wave[1]==m.wave[2])
            print("PASS \(dark ? "dark" : "light"): text, control edges, state accent and neutral information roles")
        }
        let runtime=try AppRuntime.resolve(["REVIEW_TODAY_M1_UI_FIXTURE":"learning"],bundleID:"Rex.Review-Today.BrandMaterialPreview")
        precondition(runtime.isPreview && !runtime.allowsSending)
        let container=try M1DebugFixture.makeContainer(mode:"learning"),context=container.mainContext
        let settings=try AgentComposerStore.prepare(context);settings.agentDraftText="材质对照保留草稿"
        let before=try context.fetchCount(FetchDescriptor<AgentMessage>())
        do { _ = try AgentComposerStore.sendFirst(settings.agentDraftText,context:context,runtime:runtime);preconditionFailure("Trial sent a message") }
        catch { precondition(HarnessAPIError.code(for:error)=="RT.PREVIEW.SEND_DISABLED") }
        let after=try context.fetchCount(FetchDescriptor<AgentMessage>())
        precondition(after==before)
        precondition(settings.agentDraftText=="材质对照保留草稿")
        print("PASS: daily defaults unchanged, memory-only trial rejects sending and keeps draft")
    }
}
