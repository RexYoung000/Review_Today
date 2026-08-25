#!/usr/bin/env swift

import AppKit
import Foundation

enum FaceRenderError: Error, CustomStringConvertible {
    case usage
    case load(String)
    case bitmap
    case encode

    var description: String {
        switch self {
        case .usage:
            return "Usage: render_spine_face_recomposition.swift CORE BAND SCREEN_LEFT_EARCUP SCREEN_RIGHT_EARCUP SCREEN_LEFT_EYE SCREEN_RIGHT_EYE BLINK_EYES BANGS AHOGE MOUTH OPEN_OUTPUT BLINK_OUTPUT"
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
        throw FaceRenderError.load(path)
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
    image.draw(
        in: NSRect(
            x: x,
            y: canvasHeight - top - size.height,
            width: size.width,
            height: size.height
        ),
        from: NSRect(origin: .zero, size: image.size),
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: false,
        hints: [.interpolation: NSImageInterpolation.high]
    )
}

func render(
    core: NSImage,
    band: NSImage,
    screenLeftEarcup: NSImage,
    screenRightEarcup: NSImage,
    screenLeftEye: NSImage,
    screenRightEye: NSImage,
    blinkEyes: NSImage,
    bangs: NSImage,
    ahoge: NSImage,
    mouth: NSImage,
    blinking: Bool,
    output: URL
) throws {
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
    ) else { throw FaceRenderError.bitmap }
    bitmap.size = NSSize(width: width, height: height)
    guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw FaceRenderError.bitmap
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.cgContext.clear(CGRect(x: 0, y: 0, width: width, height: height))
    let canvasHeight = CGFloat(height)

    draw(band, x: -74, top: -26, scale: 1.45, canvasHeight: canvasHeight)
    draw(core, x: 0, top: 0, scale: 1, canvasHeight: canvasHeight)

    if blinking {
        draw(blinkEyes, x: 137, top: 237, scale: 0.53, canvasHeight: canvasHeight)
    } else {
        draw(screenLeftEye, x: 188, top: 248, scale: 0.80, canvasHeight: canvasHeight)
        draw(screenRightEye, x: 308, top: 248, scale: 0.80, canvasHeight: canvasHeight)
    }
    draw(mouth, x: 243, top: 330, scale: 0.43, canvasHeight: canvasHeight)
    draw(bangs, x: 112, top: 83, scale: 1, canvasHeight: canvasHeight)
    // Keep the extracted ahoge clear of the canvas edge; its source alpha begins
    // 42 px down, so -26 preserves the intended overlap with a 12 px top margin.
    draw(ahoge, x: 216, top: -26, scale: 0.90, canvasHeight: canvasHeight)

    draw(screenLeftEarcup, x: -27, top: 174, scale: 1.30, canvasHeight: canvasHeight)
    draw(screenRightEarcup, x: 357, top: 174, scale: 1.30, canvasHeight: canvasHeight)

    NSGraphicsContext.restoreGraphicsState()
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw FaceRenderError.encode
    }
    try FileManager.default.createDirectory(
        at: output.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: output, options: .atomic)
    print("WROTE \(output.path) \(width)x\(height)")
}

do {
    let arguments = CommandLine.arguments
    guard arguments.count == 13 else { throw FaceRenderError.usage }

    let core = try load(arguments[1])
    let band = try load(arguments[2])
    let screenLeftEarcup = try load(arguments[3])
    let screenRightEarcup = try load(arguments[4])
    let screenLeftEye = try load(arguments[5])
    let screenRightEye = try load(arguments[6])
    let blinkEyes = try load(arguments[7])
    let bangs = try load(arguments[8])
    let ahoge = try load(arguments[9])
    let mouth = try load(arguments[10])

    try render(
        core: core,
        band: band,
        screenLeftEarcup: screenLeftEarcup,
        screenRightEarcup: screenRightEarcup,
        screenLeftEye: screenLeftEye,
        screenRightEye: screenRightEye,
        blinkEyes: blinkEyes,
        bangs: bangs,
        ahoge: ahoge,
        mouth: mouth,
        blinking: false,
        output: URL(fileURLWithPath: arguments[11])
    )
    try render(
        core: core,
        band: band,
        screenLeftEarcup: screenLeftEarcup,
        screenRightEarcup: screenRightEarcup,
        screenLeftEye: screenLeftEye,
        screenRightEye: screenRightEye,
        blinkEyes: blinkEyes,
        bangs: bangs,
        ahoge: ahoge,
        mouth: mouth,
        blinking: true,
        output: URL(fileURLWithPath: arguments[12])
    )
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
