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
              package_raster_assets.swift alpha-board MASCOT-CUTOUT.png MARK-CUTOUT.png OUTPUT.png
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

func drawAspectFit(_ image: NSImage, in destination: NSRect) {
    let sourceAspect = image.size.width / image.size.height
    let destinationAspect = destination.width / destination.height
    let fitted: NSRect
    if sourceAspect > destinationAspect {
        let height = destination.width / sourceAspect
        fitted = NSRect(
            x: destination.minX,
            y: destination.midY - height / 2,
            width: destination.width,
            height: height
        )
    } else {
        let width = destination.height * sourceAspect
        fitted = NSRect(
            x: destination.midX - width / 2,
            y: destination.minY,
            width: width,
            height: destination.height
        )
    }
    image.draw(
        in: fitted,
        from: NSRect(origin: .zero, size: image.size),
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: false,
        hints: [.interpolation: NSImageInterpolation.high]
    )
}

func appIconSourceRect(for image: NSImage) -> NSRect {
    // V8.3 reproduces the accepted sketch crop: a close character view with the
    // ahoge near the top edge and the lower body/cards intentionally clipped.
    let cropFraction: CGFloat = 0.85
    let leftFraction: CGFloat = 0.110
    let topFraction: CGFloat = 0.022
    let cropWidth = image.size.width * cropFraction
    let cropHeight = image.size.height * cropFraction
    return NSRect(
        x: image.size.width * leftFraction,
        y: image.size.height * (1 - topFraction - cropFraction),
        width: cropWidth,
        height: cropHeight
    )
}

func drawAppIconCrop(_ image: NSImage, in destination: NSRect) {
    image.draw(
        in: destination,
        from: appIconSourceRect(for: image),
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
    drawAppIconCrop(image, in: iconRect)
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
    drawAppIconCrop(icon, in: rect)
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

    drawText("Review Today — GPT Image Brand Assets V8.3", at: NSPoint(x: 80, y: 920), size: 34, weight: .semibold, color: graphite)
    drawText("模型负责角色内容；颜色与 AppIcon 取景均按已接受草图校准", at: NSPoint(x: 80, y: 878), size: 18, color: secondary)

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
    drawText("取景：呆毛接近上沿，头部为主视觉，身体与知识卡在下沿自然裁切。", at: NSPoint(x: 820, y: 128), size: 14, color: secondary)

    NSGraphicsContext.restoreGraphicsState()
    try writePNG(bitmap, to: output)
}

func makeAlphaBoard(mascotURL: URL, markURL: URL, output: URL) throws {
    guard let mascot = NSImage(contentsOf: mascotURL) else { throw PackageError.load(mascotURL) }
    guard let mark = NSImage(contentsOf: markURL) else { throw PackageError.load(markURL) }

    let bitmap = try makeBitmap(width: 1600, height: 1000)
    let canvas = NSColor(deviceRed: 0.965, green: 0.95, blue: 0.925, alpha: 1)
    let warmIvory = NSColor(deviceRed: 254 / 255, green: 249 / 255, blue: 242 / 255, alpha: 1)
    let terracotta = NSColor(deviceRed: 229 / 255, green: 142 / 255, blue: 109 / 255, alpha: 1)
    let graphite = NSColor(deviceRed: 42 / 255, green: 41 / 255, blue: 39 / 255, alpha: 1)
    let panelBorder = NSColor(deviceRed: 0.84, green: 0.80, blue: 0.75, alpha: 1)
    let text = NSColor(deviceRed: 0.23, green: 0.22, blue: 0.21, alpha: 1)
    let secondary = NSColor(deviceRed: 0.43, green: 0.40, blue: 0.37, alpha: 1)

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    canvas.setFill()
    NSRect(x: 0, y: 0, width: 1600, height: 1000).fill()

    drawText("Review Today — Transparent Asset QA V8.4", at: NSPoint(x: 80, y: 920), size: 34, weight: .semibold, color: text)
    drawText("真实 Alpha 叠底检查：暖白／陶土为正式表面；深色只暴露边缘风险，不代表已完成深色适配", at: NSPoint(x: 80, y: 878), size: 18, color: secondary)

    let panels = [
        (NSRect(x: 80, y: 270, width: 450, height: 540), warmIvory, "暖白产品底"),
        (NSRect(x: 575, y: 270, width: 450, height: 540), terracotta, "陶土品牌底"),
        (NSRect(x: 1070, y: 270, width: 450, height: 540), graphite, "深色边缘检查")
    ]

    for (rect, background, label) in panels {
        background.setFill()
        let path = NSBezierPath(roundedRect: rect, xRadius: 30, yRadius: 30)
        path.fill()
        panelBorder.setStroke()
        path.lineWidth = 2
        path.stroke()
        drawAspectFit(mascot, in: rect.insetBy(dx: 34, dy: 34))
        drawText(label, at: NSPoint(x: rect.minX + 24, y: rect.maxY - 42), size: 16, weight: .medium, color: background == graphite ? .white : text)
    }

    drawText("透明单色标志（石墨）", at: NSPoint(x: 112, y: 205), size: 18, weight: .medium, color: text)
    let markBackgrounds = [warmIvory, terracotta]
    var markX: CGFloat = 360
    for background in markBackgrounds {
        let rect = NSRect(x: markX, y: 70, width: 130, height: 130)
        background.setFill()
        NSBezierPath(roundedRect: rect, xRadius: 24, yRadius: 24).fill()
        drawAspectFit(mark, in: rect.insetBy(dx: 12, dy: 12))
        markX += 180
    }
    drawText("当前石墨标志用于浅色／暖色表面；深色反白版本尚未制作。", at: NSPoint(x: 760, y: 120), size: 16, color: secondary)

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
    } else if args.count == 5, args[1] == "alpha-board" {
        try makeAlphaBoard(
            mascotURL: URL(fileURLWithPath: args[2]),
            markURL: URL(fileURLWithPath: args[3]),
            output: URL(fileURLWithPath: args[4])
        )
    } else {
        throw PackageError.usage
    }
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
