import AppKit
import Foundation

// Render the same SF Symbol used by Today's static macOS entry at a fixed 2x
// resolution. The build script uses its alpha as both the resting image and
// the source for the Spine layers, so the two states share one silhouette.
guard CommandLine.arguments.count == 2,
      let symbol = NSImage(systemSymbolName: "checklist", accessibilityDescription: nil)?
        .withSymbolConfiguration(.init(pointSize: 19, weight: .medium)),
      let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 88, pixelsHigh: 88,
                                    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                    isPlanar: false, colorSpaceName: .deviceRGB,
                                    bytesPerRow: 0, bitsPerPixel: 0),
      let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fatalError("Unable to render the Today exam symbol")
}

bitmap.size = NSSize(width: 44, height: 44)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
context.imageInterpolation = .high
NSColor.clear.setFill()
NSRect(x: 0, y: 0, width: 88, height: 88).fill()
context.cgContext.scaleBy(x: 2, y: 2)
symbol.draw(in: NSRect(x: (44 - symbol.size.width) / 2,
                       y: (44 - symbol.size.height) / 2,
                       width: symbol.size.width, height: symbol.size.height),
            from: .zero, operation: .sourceOver, fraction: 1)
context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fatalError("Unable to encode the Today exam symbol")
}
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]), options: .atomic)
