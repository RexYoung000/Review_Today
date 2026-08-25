#!/usr/bin/env swift

import AppKit
import Foundation

enum RenderError: Error, CustomStringConvertible {
    case usage
    case load(String)
    case bitmap
    case encode

    var description: String {
        switch self {
        case .usage:
            return "Usage: render_spine_headset_recomposition.swift CORE.png BAND.png SCREEN_LEFT.png SCREEN_RIGHT.png OUTPUT.png"
        case .load(let path):
            return "Could not load PNG: \(path)"
        case .bitmap:
            return "Could not create output bitmap"
        case .encode:
            return "Could not encode output PNG"
        }
    }
}

func load(_ path: String) throws -> NSImage {
    guard let image = NSImage(contentsOfFile: path) else {
        throw RenderError.load(path)
    }
    return image
}

func draw(
    _ image: NSImage,
    x: CGFloat,
    top: CGFloat,
    scale: CGFloat,
    canvasHeight: CGFloat
) {
    let size = NSSize(width: image.size.width * scale, height: image.size.height * scale)
    let destination = NSRect(
        x: x,
        y: canvasHeight - top - size.height,
        width: size.width,
        height: size.height
    )
    image.draw(
        in: destination,
        from: NSRect(origin: .zero, size: image.size),
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: false,
        hints: [.interpolation: NSImageInterpolation.high]
    )
}

do {
    let arguments = CommandLine.arguments
    guard arguments.count == 6 else { throw RenderError.usage }

    let core = try load(arguments[1])
    let band = try load(arguments[2])
    let screenLeft = try load(arguments[3])
    let screenRight = try load(arguments[4])
    let output = URL(fileURLWithPath: arguments[5])

    let width = Int(core.size.width)
    let height = Int(core.size.height)
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        throw RenderError.bitmap
    }
    bitmap.size = NSSize(width: width, height: height)
    guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw RenderError.bitmap
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.cgContext.clear(CGRect(x: 0, y: 0, width: width, height: height))

    let canvasHeight = CGFloat(height)
    let bandScale: CGFloat = 1.45
    let earcupScale: CGFloat = 1.30

    // The band sits behind the continuous body texture. Its generated source
    // uses the V13.1 exploded-view scale, so only uniform scaling and placement
    // are applied here.
    draw(band, x: -74, top: -26, scale: bandScale, canvasHeight: canvasHeight)
    draw(core, x: 0, top: 0, scale: 1, canvasHeight: canvasHeight)

    // Earcups are front attachments. screen-left/right refer to the user's
    // view, avoiding ambiguity with the character's anatomical sides.
    draw(screenLeft, x: -27, top: 174, scale: earcupScale, canvasHeight: canvasHeight)
    draw(screenRight, x: 357, top: 174, scale: earcupScale, canvasHeight: canvasHeight)

    NSGraphicsContext.restoreGraphicsState()

    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw RenderError.encode
    }
    try FileManager.default.createDirectory(
        at: output.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: output, options: .atomic)
    print("WROTE \(output.path) \(width)x\(height)")
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
