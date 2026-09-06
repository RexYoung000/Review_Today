#!/usr/bin/env swift
import AppKit

// Packaging only: preserve the ImageGen master silhouette; crop transparent
// padding, tint its alpha, scale and apply the macOS tile boundary once.
let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let source = root.appendingPathComponent("brand/refresh-2026-09/masters/mark-alpha.png")
let assets = root.appendingPathComponent("Review_Today/Assets.xcassets")
let exports = root.appendingPathComponent("brand/exports")
let fm = FileManager.default
let teal = NSColor(srgbRed: 36/255, green: 108/255, blue: 99/255, alpha: 1)
let cream = NSColor(srgbRed: 247/255, green: 246/255, blue: 242/255, alpha: 1)
let ink = NSColor(srgbRed: 39/255, green: 43/255, blue: 42/255, alpha: 1)

guard let input = NSBitmapImageRep(data: try Data(contentsOf: source)), input.hasAlpha, let cg = input.cgImage else {
    fatalError("Recall master must be a PNG with real alpha")
}
var minX = input.pixelsWide, minY = input.pixelsHigh, maxX = -1, maxY = -1
for y in 0..<input.pixelsHigh {
    for x in 0..<input.pixelsWide where (input.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.5 {
        minX = min(minX, x); minY = min(minY, y)
        maxX = max(maxX, x); maxY = max(maxY, y)
    }
}
precondition(maxX >= minX && maxY >= minY, "Empty Recall master")
// Two source pixels retain antialiased boundary pixels around the solid glyph.
let cropX = max(0, minX - 2), cropY = max(0, minY - 2)
let cropWidth = min(input.pixelsWide - cropX, maxX - minX + 5)
let cropHeight = min(input.pixelsHigh - cropY, maxY - minY + 5)
let bounds = CGRect(x: cropX, y: cropY, width: cropWidth, height: cropHeight)
let trimmed = cg.cropping(to: bounds)!
let mark = NSImage(cgImage: trimmed, size: bounds.size)
print("Recall alpha bounds: \(bounds)")

func bitmap(_ width: Int, _ height: Int? = nil, draw: (NSRect) -> Void) -> NSBitmapImageRep {
    let height = height ?? width
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        .retagging(with: .sRGB)!
    rep.size = NSSize(width: width, height: height)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current?.imageInterpolation = .high
    let rect = NSRect(x: 0, y: 0, width: width, height: height)
    NSColor.clear.setFill(); rect.fill(using: .copy)
    draw(rect)
    NSGraphicsContext.restoreGraphicsState()
    return rep
}
func write(_ rep: NSBitmapImageRep, _ url: URL) throws {
    try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try rep.representation(using: .png, properties: [:])!.write(to: url, options: .atomic)
}
func image(_ rep: NSBitmapImageRep) -> NSImage { NSImage(cgImage: rep.cgImage!, size: rep.size) }
func fit(_ img: NSImage, in rect: NSRect) {
    let scale = min(rect.width / img.size.width, rect.height / img.size.height)
    let size = NSSize(width: img.size.width * scale, height: img.size.height * scale)
    img.draw(in: NSRect(x: rect.midX - size.width/2, y: rect.midY - size.height/2,
        width: size.width, height: size.height), from: .zero, operation: .sourceOver, fraction: 1)
}
func template(_ size: Int, color: NSColor = ink) -> NSBitmapImageRep {
    bitmap(size) { rect in
        fit(mark, in: rect.insetBy(dx: rect.width * 0.02, dy: rect.height * 0.02))
        color.setFill(); rect.fill(using: .sourceIn)
    }
}
let whiteMark = image(template(1024, color: cream))
func icon(_ size: Int) -> NSBitmapImageRep {
    bitmap(size) { rect in
        let tile = rect.insetBy(dx: rect.width * 0.05, dy: rect.height * 0.05)
        teal.setFill()
        NSBezierPath(roundedRect: tile, xRadius: tile.width * 0.22, yRadius: tile.height * 0.22).fill()
        // 58% of the tile including the template's 2% edge clearance.
        fit(whiteMark, in: tile.insetBy(dx: tile.width * 0.21, dy: tile.height * 0.21))
    }
}
for size in [16, 32, 64, 128, 256, 512, 1024] {
    try write(icon(size), assets.appendingPathComponent("AppIcon.appiconset/icon_\(size).png"))
}
try write(icon(1024), exports.appendingPathComponent("app-icon-1024.png"))
try write(template(512), exports.appendingPathComponent("mark-512.png"))
for (name, size) in [("BrandRecallMark", 128), ("BrandMenuMark", 18)] {
    let dir = assets.appendingPathComponent("\(name).imageset")
    try write(template(size), dir.appendingPathComponent("mark.png"))
    try write(template(size * 2), dir.appendingPathComponent("mark@2x.png"))
    let json = """
    {"images":[{"filename":"mark.png","idiom":"mac","scale":"1x"},{"filename":"mark@2x.png","idiom":"mac","scale":"2x"}],"info":{"author":"xcode","version":1},"properties":{"template-rendering-intent":"template"}}
    """
    try Data(json.utf8).write(to: dir.appendingPathComponent("Contents.json"), options: .atomic)
}
// QA uses the actual exported pixels, not ImageGen's illustrative miniatures.
let board = bitmap(1400, 720) { rect in
    cream.setFill(); rect.fill()
    func label(_ text: String, _ x: CGFloat, _ y: CGFloat, color: NSColor = ink, size: CGFloat = 16) {
        (text as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [
            .font: NSFont.systemFont(ofSize: size, weight: .medium), .foregroundColor: color])
    }
    label("REVIEW TODAY / ORIGINAL A — EXPORTED ASSETS", 44, 670, size: 20)
    image(icon(512)).draw(in: NSRect(x: 36, y: 195, width: 390, height: 390))
    label("macOS icon", 58, 170)
    image(template(256)).draw(in: NSRect(x: 480, y: 384, width: 160, height: 160))
    label("Review Today", 670, 443, size: 44)
    NSColor(srgbRed: 0.10, green: 0.11, blue: 0.11, alpha: 1).setFill()
    NSRect(x: 460, y: 170, width: 870, height: 150).fill()
    var x: CGFloat = 480
    for size in [16, 24, 32, 48, 64] {
        image(template(size, color: cream)).draw(at: NSPoint(x: x, y: 225), from: .zero, operation: .sourceOver, fraction: 1)
        label("\(size) px", x, 190, color: cream, size: 12)
        x += CGFloat(size) + 64
    }
    x = 480
    for size in [16, 32, 64, 128] {
        image(icon(size)).draw(at: NSPoint(x: x, y: 18), from: .zero, operation: .sourceOver, fraction: 1)
        label("\(size) px", x, 150, size: 12)
        x += CGFloat(size) + 70
    }
}
try write(board, exports.appendingPathComponent("brand-acceptance-board.png"))
print("Recall icon, template assets and actual-size QA board exported")
