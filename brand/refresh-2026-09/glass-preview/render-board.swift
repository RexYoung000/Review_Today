import AppKit

let folder = URL(fileURLWithPath: CommandLine.arguments[1])
let version = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "v3"
let renderFolder = version == "v1" ? "icon-renders" : "icon-renders-\(version)"
let boardName = version == "v1" ? "icon-board.png" : "icon-board-\(version).png"
let width = 1440, height = 1000
let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height, bitsPerSample: 8,
    samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
bitmap.size = NSSize(width: width, height: height)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
NSColor(white: 0.96, alpha: 1).setFill()
NSRect(x: 0, y: 0, width: width, height: height).fill()
func label(_ value: String, _ x: CGFloat, _ y: CGFloat, size: CGFloat = 16, dark: Bool = false) {
    (value as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [.font: NSFont.systemFont(ofSize: size, weight: .medium),
        .foregroundColor: dark ? NSColor.white : NSColor(white: 0.15, alpha: 1)])
}
func icon(_ appearance: String, _ size: Int, _ x: CGFloat, _ y: CGFloat, drawSize: CGFloat? = nil) {
    let image = NSImage(contentsOf: folder.appendingPathComponent("\(renderFolder)/\(appearance)-\(size).png"))!
    image.draw(in: NSRect(x: x, y: y, width: drawSize ?? CGFloat(size), height: drawSize ?? CGFloat(size)))
}
label(version == "v1" ? "REVIEW TODAY / GLASS ICON" : "REVIEW TODAY / SATIN METAL + GLASS", 48, 936, size: 28)
label("Icon Composer 原生导出 · \(version) · 轮廓沿用已选 R · 小样待确认", 48, 902)
for (i, name) in ["default", "dark", "mono"].enumerated() {
    let x = 56 + CGFloat(i) * 460
    icon(name, 512, x, 500, drawSize: 360)
    label(["默认 / Default", "深色 / Dark", "单色 / Mono"][i], x, 463, size: 20)
    label("实际像素尺寸", x, 420, size: 14)
    var offset = x
    for size in [16, 32, 64, 128] {
        icon(name, size, offset, 252)
        label("\(size) px", offset, 225, size: 12)
        offset += CGFloat(size) + 28
    }
    NSColor(white: 0.10, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: x - 8, y: 52, width: 400, height: 128), xRadius: 16, yRadius: 16).fill()
    icon(name, 64, x + 12, 84)
    label("深色背景辨识", x + 100, 108, size: 16, dark: true)
}
NSGraphicsContext.restoreGraphicsState()
try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent(boardName))
print("Saved \(boardName)")

if version == "v2" {
    let comparison = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1440, pixelsHigh: 760,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    comparison.size = NSSize(width: 1440, height: 760)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: comparison)
    NSColor(white: 0.96, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: 1440, height: 760).fill()
    label("REVIEW TODAY / v1 → v2", 48, 695, size: 28)
    label("青绿渐变金属 · 缎面柔化亮边 · 独立透明玻璃外壳", 48, 658)
    let variants = [("icon-renders/default-512.png", "v1 / 原玻璃 R"),
                    ("icon-renders-v2/default-512.png", "v2 / 缎面金属 + 玻璃外壳"),
                    ("icon-renders-v2/dark-512.png", "v2 / 石墨深色外观")]
    for (index, item) in variants.enumerated() {
        let x = 56 + CGFloat(index) * 460
        NSImage(contentsOf: folder.appendingPathComponent(item.0))!
            .draw(in: NSRect(x: x, y: 238, width: 360, height: 360))
        label(item.1, x, 190, size: 20)
    }
    label("保留原始 R 轮廓与内侧斜切 · Icon Composer 原生导出 · 日常 App 尚未替换", 48, 80)
    NSGraphicsContext.restoreGraphicsState()
    try comparison.representation(using: .png, properties: [:])!
        .write(to: folder.appendingPathComponent("material-comparison-v2.png"))
    print("Saved material-comparison-v2.png")
}

if version == "v3" {
    let comparison = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1280, pixelsHigh: 830,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    comparison.size = NSSize(width: 1280, height: 830)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: comparison)
    NSColor(white: 0.94, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: 1280, height: 830).fill()
    label("REVIEW TODAY / 深色清晰度修复", 64, 765, size: 28)
    label("同为 512 px 原生导出 · 无锐化或后期滤镜", 64, 725)
    for (index, rev) in ["v2", "v3"].enumerated() {
        let x: CGFloat = index == 0 ? 64 : 704
        NSImage(contentsOf: folder.appendingPathComponent("icon-renders-\(rev)/dark-512.png"))!
            .draw(in: NSRect(x: x, y: 170, width: 512, height: 512))
        label(index == 0 ? "修复前 / v2" : "修复后 / v3", x, 120, size: 22)
    }
    label("中央透明 · 窄玻璃亮边 · 去除外壳投影 · R 的轮廓与金属材质保持", 64, 53)
    NSGraphicsContext.restoreGraphicsState()
    try comparison.representation(using: .png, properties: [:])!
        .write(to: folder.appendingPathComponent("clarity-comparison-v3.png"))
    print("Saved clarity-comparison-v3.png")
}
