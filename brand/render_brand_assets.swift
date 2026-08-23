#!/usr/bin/env swift

import AppKit
import Foundation

enum RenderError: Error, CustomStringConvertible {
    case usage
    case load(URL)
    case bitmap
    case png

    var description: String {
        switch self {
        case .usage:
            return """
            Usage:
              render_brand_assets.swift render INPUT.svg OUTPUT.png SIZE
              render_brand_assets.swift board ICON.png MASCOT.png MARK.png SMALL_ICON.png OUTPUT.png
            """
        case .load(let url):
            return "Could not load SVG: \(url.path)"
        case .bitmap:
            return "Could not create bitmap context"
        case .png:
            return "Could not encode PNG"
        }
    }
}

func makeBitmap(width: Int, height: Int) throws -> NSBitmapImageRep {
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
    ) else { throw RenderError.bitmap }
    bitmap.size = NSSize(width: width, height: height)
    return bitmap
}

func writePNG(_ bitmap: NSBitmapImageRep, to output: URL) throws {
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw RenderError.png
    }
    try FileManager.default.createDirectory(
        at: output.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: output, options: .atomic)
}

func render(svg input: URL, output: URL, size: Int) throws {
    guard let image = NSImage(contentsOf: input) else { throw RenderError.load(input) }
    let bitmap = try makeBitmap(width: size, height: size)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: size, height: size).fill()
    image.draw(
        in: NSRect(x: 0, y: 0, width: size, height: size),
        from: .zero,
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: true,
        hints: [.interpolation: NSImageInterpolation.high]
    )
    NSGraphicsContext.restoreGraphicsState()
    try writePNG(bitmap, to: output)
}

func fillRoundedRect(_ rect: NSRect, radius: CGFloat, color: NSColor) {
    color.setFill()
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).fill()
}

func strokeRoundedRect(_ rect: NSRect, radius: CGFloat, color: NSColor) {
    color.setStroke()
    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    path.lineWidth = 2
    path.stroke()
}

func drawText(_ text: String, at point: NSPoint, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor) {
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: color
    ]
    NSString(string: text).draw(at: point, withAttributes: attributes)
}

func drawImage(_ image: NSImage, in rect: NSRect) {
    image.draw(
        in: rect,
        from: .zero,
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: false,
        hints: [.interpolation: NSImageInterpolation.high]
    )
}

func makeBoard(iconURL: URL, mascotURL: URL, markURL: URL, smallIconURL: URL, output: URL) throws {
    guard let icon = NSImage(contentsOf: iconURL) else { throw RenderError.load(iconURL) }
    guard let mascot = NSImage(contentsOf: mascotURL) else { throw RenderError.load(mascotURL) }
    guard let mark = NSImage(contentsOf: markURL) else { throw RenderError.load(markURL) }
    guard let smallIcon = NSImage(contentsOf: smallIconURL) else { throw RenderError.load(smallIconURL) }

    let width = 1600
    let height = 1000
    let bitmap = try makeBitmap(width: width, height: height)
    let background = NSColor(calibratedRed: 0.969, green: 0.953, blue: 0.925, alpha: 1)
    let panel = NSColor(calibratedWhite: 1, alpha: 0.82)
    let border = NSColor(calibratedRed: 0.875, green: 0.835, blue: 0.792, alpha: 1)
    let graphite = NSColor(calibratedRed: 0.208, green: 0.192, blue: 0.180, alpha: 1)
    let secondary = NSColor(calibratedRed: 0.43, green: 0.39, blue: 0.36, alpha: 1)

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    background.setFill()
    NSRect(x: 0, y: 0, width: width, height: height).fill()

    drawText("Review Today — Brand Assets V8", at: NSPoint(x: 80, y: 918), size: 34, weight: .semibold, color: graphite)
    drawText("Caring review teacher · knowledge cards · warm, corrective, never blaming", at: NSPoint(x: 80, y: 877), size: 18, color: secondary)

    let iconPanel = NSRect(x: 80, y: 360, width: 500, height: 470)
    let mascotPanel = NSRect(x: 620, y: 360, width: 460, height: 470)
    let markPanel = NSRect(x: 1120, y: 586, width: 400, height: 244)
    let colorPanel = NSRect(x: 1120, y: 360, width: 400, height: 194)
    let sizePanel = NSRect(x: 80, y: 70, width: 1440, height: 240)

    for rect in [iconPanel, mascotPanel, markPanel, colorPanel, sizePanel] {
        fillRoundedRect(rect, radius: 30, color: panel)
        strokeRoundedRect(rect, radius: 30, color: border)
    }

    drawText("App icon", at: NSPoint(x: 112, y: 785), size: 18, weight: .medium, color: graphite)
    drawImage(icon, in: NSRect(x: 130, y: 405, width: 400, height: 400))

    drawText("Full mascot", at: NSPoint(x: 652, y: 785), size: 18, weight: .medium, color: graphite)
    drawImage(mascot, in: NSRect(x: 660, y: 387, width: 380, height: 380))

    drawText("Monochrome mark", at: NSPoint(x: 1152, y: 785), size: 18, weight: .medium, color: graphite)
    drawImage(mark, in: NSRect(x: 1222, y: 610, width: 196, height: 196))

    drawText("Semantic palette", at: NSPoint(x: 1152, y: 510), size: 18, weight: .medium, color: graphite)
    let swatches: [(NSColor, String)] = [
        (NSColor(calibratedRed: 0.851, green: 0.435, blue: 0.314, alpha: 1), "Terracotta"),
        (NSColor(calibratedRed: 0.969, green: 0.902, blue: 0.745, alpha: 1), "Cream"),
        (NSColor(calibratedRed: 1.000, green: 0.973, blue: 0.910, alpha: 1), "Paper"),
        (graphite, "Graphite")
    ]
    for (index, swatch) in swatches.enumerated() {
        let column = index % 2
        let row = index / 2
        let x = CGFloat(1152 + column * 184)
        let y = CGFloat(456 - row * 62)
        fillRoundedRect(NSRect(x: x, y: y, width: 46, height: 36), radius: 10, color: swatch.0)
        drawText(swatch.1, at: NSPoint(x: x + 58, y: y + 8), size: 14, color: graphite)
    }

    drawText("Optical size check", at: NSPoint(x: 112, y: 264), size: 18, weight: .medium, color: graphite)
    drawText("Large master", at: NSPoint(x: 112, y: 226), size: 14, color: secondary)
    drawImage(icon, in: NSRect(x: 112, y: 88, width: 128, height: 128))
    drawText("128", at: NSPoint(x: 159, y: 82), size: 12, color: secondary)

    let sizes = [64, 32, 16]
    var x: CGFloat = 330
    drawText("Small master", at: NSPoint(x: x, y: 226), size: 14, color: secondary)
    for size in sizes {
        let drawSize = CGFloat(size)
        drawImage(smallIcon, in: NSRect(x: x, y: 104, width: drawSize, height: drawSize))
        drawText("\(size)", at: NSPoint(x: x, y: 82), size: 12, color: secondary)
        x += max(drawSize + 72, 118)
    }
    drawText("Static logo: closed smile + cards", at: NSPoint(x: 845, y: 168), size: 18, weight: .medium, color: graphite)
    drawText("Conversation headset and two-tooth grin remain interaction states, not default branding.", at: NSPoint(x: 845, y: 132), size: 14, color: secondary)

    NSGraphicsContext.restoreGraphicsState()
    try writePNG(bitmap, to: output)
}

do {
    let args = CommandLine.arguments
    if args.count == 5, args[1] == "render", let size = Int(args[4]), size > 0 {
        try render(
            svg: URL(fileURLWithPath: args[2]),
            output: URL(fileURLWithPath: args[3]),
            size: size
        )
    } else if args.count == 7, args[1] == "board" {
        try makeBoard(
            iconURL: URL(fileURLWithPath: args[2]),
            mascotURL: URL(fileURLWithPath: args[3]),
            markURL: URL(fileURLWithPath: args[4]),
            smallIconURL: URL(fileURLWithPath: args[5]),
            output: URL(fileURLWithPath: args[6])
        )
    } else {
        throw RenderError.usage
    }
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
