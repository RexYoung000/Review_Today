#!/usr/bin/env swift

import AppKit
import Foundation

enum PackageError: Error, CustomStringConvertible {
    case usage
    case load(URL)
    case bitmap
    case png

    var description: String {
        switch self {
        case .usage:
            return """
            Usage:
              package_raster_assets.swift icon INPUT.png OUTPUT.png SIZE
              package_raster_assets.swift resize INPUT.png OUTPUT.png SIZE
              package_raster_assets.swift board MASCOT.png ICON.png MARK.png OUTPUT.png
            """
        case .load(let url):
            return "Could not load image: \(url.path)"
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
    ) else { throw PackageError.bitmap }
    bitmap.size = NSSize(width: width, height: height)
    return bitmap
}

func writePNG(_ bitmap: NSBitmapImageRep, to output: URL) throws {
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw PackageError.png
    }
    try FileManager.default.createDirectory(
        at: output.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try data.write(to: output, options: .atomic)
}

func sourceRect(for image: NSImage, destination: NSRect) -> NSRect {
    let sourceSize = image.size
    let sourceAspect = sourceSize.width / sourceSize.height
    let destinationAspect = destination.width / destination.height
    if sourceAspect > destinationAspect {
        let width = sourceSize.height * destinationAspect
        return NSRect(x: (sourceSize.width - width) / 2, y: 0, width: width, height: sourceSize.height)
    }
    let height = sourceSize.width / destinationAspect
    return NSRect(x: 0, y: (sourceSize.height - height) / 2, width: sourceSize.width, height: height)
}

func drawAspectFill(_ image: NSImage, in destination: NSRect) {
    image.draw(
        in: destination,
        from: sourceRect(for: image, destination: destination),
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: false,
        hints: [.interpolation: NSImageInterpolation.high]
    )
}

func exportIcon(input: URL, output: URL, size: Int) throws {
    guard let image = NSImage(contentsOf: input) else { throw PackageError.load(input) }
    let bitmap = try makeBitmap(width: size, height: size)
    let canvas = NSRect(x: 0, y: 0, width: size, height: size)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor.clear.setFill()
    canvas.fill()
    let inset = max(CGFloat(size) * 0.018, size >= 64 ? 1 : 0)
    let iconRect = canvas.insetBy(dx: inset, dy: inset)
    NSBezierPath(
        roundedRect: iconRect,
        xRadius: CGFloat(size) * 0.22,
        yRadius: CGFloat(size) * 0.22
    ).addClip()
    drawAspectFill(image, in: iconRect)
    NSGraphicsContext.restoreGraphicsState()
    try writePNG(bitmap, to: output)
}

func resize(input: URL, output: URL, size: Int) throws {
    guard let image = NSImage(contentsOf: input) else { throw PackageError.load(input) }
    let bitmap = try makeBitmap(width: size, height: size)
    let canvas = NSRect(x: 0, y: 0, width: size, height: size)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor.clear.setFill()
    canvas.fill()
    drawAspectFill(image, in: canvas)
    NSGraphicsContext.restoreGraphicsState()
    try writePNG(bitmap, to: output)
}

func fillPanel(_ rect: NSRect, color: NSColor, border: NSColor) {
    color.setFill()
    let path = NSBezierPath(roundedRect: rect, xRadius: 28, yRadius: 28)
    path.fill()
    border.setStroke()
    path.lineWidth = 2
    path.stroke()
}

func drawText(_ text: String, at point: NSPoint, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor) {
    NSString(string: text).draw(
        at: point,
        withAttributes: [
            .font: NSFont.systemFont(ofSize: size, weight: weight),
            .foregroundColor: color
        ]
    )
}

func drawIconMaster(_ icon: NSImage, in rect: NSRect) {
    NSGraphicsContext.saveGraphicsState()
    NSBezierPath(
        roundedRect: rect,
        xRadius: rect.width * 0.22,
        yRadius: rect.height * 0.22
    ).addClip()
    drawAspectFill(icon, in: rect)
    NSGraphicsContext.restoreGraphicsState()
}

func makeBoard(mascotURL: URL, iconURL: URL, markURL: URL, output: URL) throws {
    guard let mascot = NSImage(contentsOf: mascotURL) else { throw PackageError.load(mascotURL) }
    guard let icon = NSImage(contentsOf: iconURL) else { throw PackageError.load(iconURL) }
    guard let mark = NSImage(contentsOf: markURL) else { throw PackageError.load(markURL) }

    let bitmap = try makeBitmap(width: 1600, height: 1000)
    let background = NSColor(calibratedRed: 0.969, green: 0.953, blue: 0.925, alpha: 1)
    let panel = NSColor(calibratedWhite: 1, alpha: 0.9)
    let border = NSColor(calibratedRed: 0.875, green: 0.835, blue: 0.792, alpha: 1)
    let graphite = NSColor(calibratedRed: 0.208, green: 0.192, blue: 0.180, alpha: 1)
    let secondary = NSColor(calibratedRed: 0.43, green: 0.39, blue: 0.36, alpha: 1)

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    background.setFill()
    NSRect(x: 0, y: 0, width: 1600, height: 1000).fill()

    drawText("Review Today — GPT Image Brand Assets V8.2", at: NSPoint(x: 80, y: 920), size: 34, weight: .semibold, color: graphite)
    drawText("模型负责角色内容；颜色按已接受草图直接取样，工程只做像素校色与打包", at: NSPoint(x: 80, y: 878), size: 18, color: secondary)

    let mascotPanel = NSRect(x: 80, y: 330, width: 480, height: 500)
    let iconPanel = NSRect(x: 600, y: 330, width: 480, height: 500)
    let markPanel = NSRect(x: 1120, y: 330, width: 400, height: 500)
    let sizePanel = NSRect(x: 80, y: 70, width: 1440, height: 210)
    for rect in [mascotPanel, iconPanel, markPanel, sizePanel] {
        fillPanel(rect, color: panel, border: border)
    }

    drawText("完整吉祥物", at: NSPoint(x: 112, y: 785), size: 18, weight: .medium, color: graphite)
    drawAspectFill(mascot, in: NSRect(x: 120, y: 365, width: 400, height: 400))
    drawText("App 图标母图", at: NSPoint(x: 632, y: 785), size: 18, weight: .medium, color: graphite)
    drawIconMaster(icon, in: NSRect(x: 640, y: 365, width: 400, height: 400))
    drawText("单色标志", at: NSPoint(x: 1152, y: 785), size: 18, weight: .medium, color: graphite)
    drawAspectFill(mark, in: NSRect(x: 1160, y: 385, width: 320, height: 320))

    drawText("AppIcon 实际尺寸", at: NSPoint(x: 112, y: 235), size: 18, weight: .medium, color: graphite)
    let sizes = [128, 64, 32, 16]
    var x: CGFloat = 112
    for size in sizes {
        let dimension = CGFloat(size)
        drawIconMaster(icon, in: NSRect(x: x, y: 92, width: dimension, height: dimension))
        drawText("\(size)", at: NSPoint(x: x, y: 78), size: 12, color: secondary)
        x += max(dimension + 70, 118)
    }
    drawText("静态品牌：闭口微笑 + 两张知识卡", at: NSPoint(x: 820, y: 165), size: 18, weight: .medium, color: graphite)
    drawText("陶土底 #E58E6D；头部 #FFF7E8；下半身 #FCEFD6；不改变模型角色造型。", at: NSPoint(x: 820, y: 128), size: 14, color: secondary)

    NSGraphicsContext.restoreGraphicsState()
    try writePNG(bitmap, to: output)
}

do {
    let args = CommandLine.arguments
    if args.count == 5, args[1] == "icon", let size = Int(args[4]), size > 0 {
        try exportIcon(input: URL(fileURLWithPath: args[2]), output: URL(fileURLWithPath: args[3]), size: size)
    } else if args.count == 5, args[1] == "resize", let size = Int(args[4]), size > 0 {
        try resize(input: URL(fileURLWithPath: args[2]), output: URL(fileURLWithPath: args[3]), size: size)
    } else if args.count == 6, args[1] == "board" {
        try makeBoard(
            mascotURL: URL(fileURLWithPath: args[2]),
            iconURL: URL(fileURLWithPath: args[3]),
            markURL: URL(fileURLWithPath: args[4]),
            output: URL(fileURLWithPath: args[5])
        )
    } else {
        throw PackageError.usage
    }
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
