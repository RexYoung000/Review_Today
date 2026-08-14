import AppKit
import SwiftUI

extension NSAppearance {
    var isDark: Bool {
        bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
    }
}

/// Persists an explicit light/dark choice and drives a Magic UI-style circle reveal.
@MainActor
@Observable
final class AppearanceController {
    static let shared = AppearanceController()

    private static let defaultsKey = "runway.appearance.isDark"

    var isDark: Bool

    var colors: RunwayPalette { Runway.palette(dark: isDark) }

    private init() {
        if UserDefaults.standard.object(forKey: Self.defaultsKey) == nil {
            isDark = NSApp.effectiveAppearance.isDark
        } else {
            isDark = UserDefaults.standard.bool(forKey: Self.defaultsKey)
        }
        applyAppKit()
    }

    func applyAppKit() {
        NSApp.appearance = NSAppearance(named: isDark ? .darkAqua : .aqua)
        UserDefaults.standard.set(isDark, forKey: Self.defaultsKey)
    }

    func setDark(_ dark: Bool, screenPoint: NSPoint?, reduceMotion: Bool) {
        guard dark != isDark else { return }
        let change = {
            self.isDark = dark
            self.applyAppKit()
        }
        guard !reduceMotion, let window = NSApp.keyWindow ?? NSApp.windows.first(where: \.isVisible) else {
            change()
            return
        }
        ThemeReveal.play(
            in: window,
            screenPoint: screenPoint ?? NSEvent.mouseLocation,
            goingDark: dark,
            apply: change
        )
    }

    func toggle(screenPoint: NSPoint? = nil, reduceMotion: Bool) {
        setDark(!isDark, screenPoint: screenPoint ?? NSEvent.mouseLocation, reduceMotion: reduceMotion)
    }
}

/// Overlay window + expanding hole from the toggle, matching Magic UI
/// AnimatedThemeToggler. Old canvas covers the window, then a circle
/// reveals the new theme underneath.
private enum ThemeReveal {
    static let duration: CFTimeInterval = 0.72

    static func play(in window: NSWindow, screenPoint: NSPoint, goingDark: Bool, apply: @escaping () -> Void) {
        let frame = window.frame
        guard frame.width > 8, frame.height > 8 else {
            apply()
            return
        }

        let overlay = NSPanel(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        overlay.isFloatingPanel = true
        overlay.level = NSWindow.Level(rawValue: window.level.rawValue + 1)
        overlay.isOpaque = false
        overlay.backgroundColor = .clear
        overlay.hasShadow = false
        overlay.ignoresMouseEvents = true
        overlay.hidesOnDeactivate = false
        overlay.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        overlay.setFrame(frame, display: true)

        let host = NSView(frame: NSRect(origin: .zero, size: frame.size))
        host.wantsLayer = true
        host.layer?.masksToBounds = true
        overlay.contentView = host

        let cover = NSView(frame: host.bounds)
        cover.autoresizingMask = [.width, .height]
        cover.wantsLayer = true
        let old = goingDark
            ? NSColor(srgbRed: 0.965, green: 0.965, blue: 0.968, alpha: 1)
            : NSColor(srgbRed: 0.07, green: 0.07, blue: 0.08, alpha: 1)
        cover.layer?.backgroundColor = old.cgColor
        host.addSubview(cover)

        var origin = window.convertPoint(fromScreen: screenPoint)
        origin.x = min(max(origin.x, 0), frame.width)
        origin.y = min(max(origin.y, 0), frame.height)
        let maxRadius = hypot(
            max(origin.x, frame.width - origin.x),
            max(origin.y, frame.height - origin.y)
        ) + 24

        let mask = CAShapeLayer()
        mask.fillRule = .evenOdd
        mask.path = holePath(bounds: host.bounds, center: origin, radius: 1)
        cover.layer?.mask = mask

        overlay.orderFront(nil)
        apply()

        let animation = CABasicAnimation(keyPath: "path")
        animation.fromValue = holePath(bounds: host.bounds, center: origin, radius: 1)
        animation.toValue = holePath(bounds: host.bounds, center: origin, radius: maxRadius)
        animation.duration = duration
        animation.timingFunction = CAMediaTimingFunction(controlPoints: 0.22, 0.61, 0.36, 1)
        animation.fillMode = .forwards
        animation.isRemovedOnCompletion = false
        mask.add(animation, forKey: "reveal")
        mask.path = holePath(bounds: host.bounds, center: origin, radius: maxRadius)

        DispatchQueue.main.asyncAfter(deadline: .now() + duration + 0.04) {
            overlay.orderOut(nil)
            overlay.close()
        }
    }

    private static func holePath(bounds: CGRect, center: CGPoint, radius: CGFloat) -> CGPath {
        let path = CGMutablePath()
        path.addRect(bounds)
        path.addEllipse(in: CGRect(
            x: center.x - radius,
            y: center.y - radius,
            width: radius * 2,
            height: radius * 2
        ))
        return path
    }
}

struct AnimatedThemeToggler: View {
    @Environment(AppearanceController.self) private var appearance
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.runway) private var runway

    var body: some View {
        Button {
            appearance.toggle(screenPoint: NSEvent.mouseLocation, reduceMotion: reduceMotion)
        } label: {
            Image(systemName: appearance.isDark ? "sun.max.fill" : "moon.fill")
                .font(.body.weight(.semibold))
                .foregroundStyle(runway.ink)
                .frame(width: 32, height: 32)
                .contentTransition(.symbolEffect(.replace))
                .background(runway.card, in: Circle())
                .overlay(Circle().strokeBorder(runway.hairline, lineWidth: 1))
                .shadow(color: runway.liftShadow, radius: 6, y: 2)
        }
        .buttonStyle(.plain)
        .help(appearance.isDark ? String(localized: "切换到浅色") : String(localized: "切换到深色"))
        .accessibilityLabel(appearance.isDark ? String(localized: "切换到浅色") : String(localized: "切换到深色"))
        .animation(reduceMotion ? nil : Runway.spring, value: appearance.isDark)
    }
}

struct AppearanceGate: ViewModifier {
    func body(content: Content) -> some View {
        AppearanceGateBody { content }
    }
}

private struct AppearanceGateBody<Content: View>: View {
    @Bindable private var appearance = AppearanceController.shared
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .preferredColorScheme(appearance.isDark ? .dark : .light)
            .environment(appearance)
            .environment(\.runway, appearance.colors)
            .onAppear { appearance.applyAppKit() }
    }
}

extension View {
    func runwayAppearance() -> some View {
        modifier(AppearanceGate())
    }
}
