import SwiftUI

enum CoachPose: Hashable {
    case idle
    case working
    case whistle
    case waitYou
}

/// Lightweight 2-bone rig: head + whistle pendulum, with spring pose changes
/// and idle oscillation. Reduce Motion keeps a still rest pose.
struct CoachMark: View {
    var pose: CoachPose = .idle
    var size: CGFloat = 56

    @Environment(\.brandReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.runway) private var runway
    @State private var headTilt = 0.02
    @State private var headAmp = 0.03
    @State private var whistle = 0.10
    @State private var whistleAmp = 0.12
    @State private var lift = 0.0
    @State private var breatheAmp = 0.016
    @State private var freq = 2.35

    var body: some View {
        TimelineView(.animation(minimumInterval: reduceMotion ? 10 : 1 / 30, paused: reduceMotion)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            Canvas { context, canvasSize in
                draw(context, size: canvasSize, t: t)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
        .onAppear { snap(to: pose) }
        .onChange(of: pose) { _, new in
            snap(to: new)
        }
    }

    private func snap(to pose: CoachPose) {
        let next = CoachRig.rest(for: pose)
        let apply = {
            headTilt = next.headTilt
            headAmp = next.headAmp
            whistle = next.whistle
            whistleAmp = next.whistleAmp
            lift = next.lift
            breatheAmp = next.breathe
            freq = next.freq
        }
        if reduceMotion {
            apply()
        } else {
            withAnimation(Runway.softSpring, apply)
        }
    }

    private func draw(_ context: GraphicsContext, size: CGSize, t: TimeInterval) {
        let w = size.width
        let h = size.height
        let osc = reduceMotion ? 0.0 : sin(t * freq)
        let breathe = 1 + osc * breatheAmp
        let liveHead = headTilt + osc * headAmp
        let liveWhistle = whistle + osc * whistleAmp
        let blinkCycle = t.truncatingRemainder(dividingBy: 4.6)
        let blink = reduceMotion ? 1.0 : (blinkCycle < 0.11 ? 0.14 : 1.0)

        var ctx = context
        ctx.translateBy(x: w / 2, y: h / 2 + h * 0.04)
        ctx.scaleBy(x: breathe, y: breathe)

        drawShadow(&ctx, w: w, h: h)
        drawBody(&ctx, w: w, h: h)
        drawCord(&ctx, w: w, h: h, swing: liveWhistle, lift: lift)
        drawWhistle(&ctx, w: w, h: h, swing: liveWhistle, lift: lift)
        drawHead(&ctx, w: w, h: h, tilt: liveHead, blink: blink)
    }

    private func drawShadow(_ context: inout GraphicsContext, w: CGFloat, h: CGFloat) {
        context.fill(
            Path(ellipseIn: CGRect(x: -w * 0.22, y: h * 0.36, width: w * 0.44, height: h * 0.10)),
            with: .color(Color.black.opacity(0.10))
        )
    }

    private func drawBody(_ context: inout GraphicsContext, w: CGFloat, h: CGFloat) {
        let body = Path(roundedRect: CGRect(x: -w * 0.30, y: h * 0.00, width: w * 0.60, height: h * 0.46), cornerRadius: w * 0.18)
        context.fill(body, with: .color(runway.monochrome ? Color(white: colorScheme == .dark ? 0.90 : 0.12) : runway.agent))
        var shine = Path()
        shine.addEllipse(in: CGRect(x: -w * 0.18, y: h * 0.04, width: w * 0.22, height: h * 0.10))
        context.fill(shine, with: .color(Color.white.opacity(0.14)))
        var stripe = Path()
        stripe.addRoundedRect(in: CGRect(x: -w * 0.24, y: h * 0.08, width: w * 0.07, height: h * 0.22), cornerSize: CGSize(width: 3, height: 3))
        stripe.addRoundedRect(in: CGRect(x: w * 0.17, y: h * 0.08, width: w * 0.07, height: h * 0.22), cornerSize: CGSize(width: 3, height: 3))
        context.fill(stripe, with: .color(Color.white.opacity(0.92)))
    }

    private func drawHead(_ context: inout GraphicsContext, w: CGFloat, h: CGFloat, tilt: Double, blink: Double) {
        var ctx = context
        ctx.translateBy(x: 0, y: -h * 0.18)
        ctx.rotate(by: .radians(tilt))

        let headRect = CGRect(x: -w * 0.23, y: -w * 0.23, width: w * 0.46, height: w * 0.46)
        ctx.fill(Path(ellipseIn: headRect), with: .color(runway.monochrome ? Color(white: colorScheme == .dark ? 0.94 : 0.18) : Runway.cream))
        ctx.fill(
            Path(ellipseIn: CGRect(x: -w * 0.14, y: -w * 0.18, width: w * 0.18, height: w * 0.10)),
            with: .color(Color.white.opacity(0.35))
        )

        let visor = Path(roundedRect: CGRect(x: -w * 0.26, y: -w * 0.08, width: w * 0.52, height: w * 0.11), cornerRadius: w * 0.055)
        ctx.fill(visor, with: .color(runway.monochrome ? Color(white: colorScheme == .dark ? 0.90 : 0.12) : runway.agent))
        ctx.fill(
            Path(roundedRect: CGRect(x: -w * 0.20, y: -w * 0.075, width: w * 0.16, height: w * 0.035), cornerRadius: 2),
            with: .color(Color.white.opacity(0.18))
        )

        let eyeH = w * 0.046 * blink
        ctx.fill(Path(ellipseIn: CGRect(x: -w * 0.09, y: -w * 0.01 - eyeH / 2, width: w * 0.046, height: eyeH)), with: .color(runway.monochrome ? (colorScheme == .dark ? Color.black : Color.white) : Runway.mascotInk))
        ctx.fill(Path(ellipseIn: CGRect(x: w * 0.044, y: -w * 0.01 - eyeH / 2, width: w * 0.046, height: eyeH)), with: .color(runway.monochrome ? (colorScheme == .dark ? Color.black : Color.white) : Runway.mascotInk))

        var smile = Path()
        smile.addArc(center: CGPoint(x: 0, y: w * 0.05), radius: w * 0.07, startAngle: .degrees(18), endAngle: .degrees(162), clockwise: false)
        ctx.stroke(smile, with: .color((runway.monochrome ? (colorScheme == .dark ? Color.black : Color.white) : Runway.mascotInk).opacity(0.72)), style: StrokeStyle(lineWidth: max(1.1, w * 0.018), lineCap: .round))
    }

    private func drawCord(_ context: inout GraphicsContext, w: CGFloat, h: CGFloat, swing: Double, lift: Double) {
        var cord = Path()
        let start = CGPoint(x: 0, y: h * 0.02)
        let end = CGPoint(x: sin(swing) * w * 0.18, y: h * (0.26 - lift))
        cord.move(to: start)
        cord.addQuadCurve(to: end, control: CGPoint(x: end.x * 0.35, y: h * 0.12))
        context.stroke(cord, with: .color((runway.monochrome ? (colorScheme == .dark ? Color.black : Color.white) : Runway.mascotInk).opacity(0.55)), style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
    }

    private func drawWhistle(_ context: inout GraphicsContext, w: CGFloat, h: CGFloat, swing: Double, lift: Double) {
        let cx = sin(swing) * w * 0.18
        let cy = h * (0.28 - lift)
        var ctx = context
        ctx.translateBy(x: cx, y: cy)
        ctx.rotate(by: .radians(swing * 0.35))
        ctx.fill(
            Path(roundedRect: CGRect(x: -w * 0.10, y: -w * 0.045, width: w * 0.20, height: w * 0.09), cornerRadius: w * 0.03),
            with: .color(runway.monochrome ? Color(white: 0.78) : Color(red: 0.78, green: 0.79, blue: 0.81))
        )
        ctx.fill(
            Path(ellipseIn: CGRect(x: w * 0.00, y: -w * 0.028, width: w * 0.056, height: w * 0.056)),
            with: .color(runway.monochrome ? Color(white: 0.35) : Color(red: 0.89, green: 0.62, blue: 0.18))
        )
        ctx.fill(
            Path(ellipseIn: CGRect(x: w * 0.012, y: -w * 0.020, width: w * 0.018, height: w * 0.018)),
            with: .color(Color.white.opacity(0.35))
        )
    }
}

private struct CoachRig: Equatable {
    var headTilt: Double
    var headAmp: Double
    var whistle: Double
    var whistleAmp: Double
    var lift: Double
    var breathe: Double
    var freq: Double

    static func rest(for pose: CoachPose) -> CoachRig {
        switch pose {
        case .idle:
            CoachRig(headTilt: 0.02, headAmp: 0.03, whistle: 0.10, whistleAmp: 0.12, lift: 0, breathe: 0.016, freq: 2.35)
        case .working:
            CoachRig(headTilt: 0.06, headAmp: 0.12, whistle: 0.18, whistleAmp: 0.38, lift: 0.02, breathe: 0.028, freq: 5.1)
        case .whistle:
            CoachRig(headTilt: -0.05, headAmp: 0.02, whistle: -0.92, whistleAmp: 0.04, lift: 0.11, breathe: 0.012, freq: 2.0)
        case .waitYou:
            CoachRig(headTilt: -0.11, headAmp: 0.015, whistle: 0.04, whistleAmp: 0.05, lift: 0, breathe: 0.010, freq: 1.55)
        }
    }
}
