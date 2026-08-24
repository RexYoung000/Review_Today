#!/usr/bin/env swift

import AppKit
import Foundation

struct RGB {
    let r: Int
    let g: Int
    let b: Int

    init(_ color: NSColor) {
        let value = color.usingColorSpace(.deviceRGB)!
        r = Int(round(value.redComponent * 255))
        g = Int(round(value.greenComponent * 255))
        b = Int(round(value.blueComponent * 255))
    }
}

enum ExtractionError: Error, CustomStringConvertible {
    case usage
    case load(URL)
    case bitmap
    case encode

    var description: String {
        switch self {
        case .usage:
            return "Usage: extract_alpha_cutout.swift INPUT.png OUTPUT.png [background-distance] [edge-radius]"
        case .load(let url):
            return "Could not load image: \(url.path)"
        case .bitmap:
            return "Could not create RGBA bitmap"
        case .encode:
            return "Could not encode PNG"
        }
    }
}

func median(_ values: [Int]) -> Int {
    values.sorted()[values.count / 2]
}

func backgroundColor(pixels: [RGB], width: Int, height: Int) -> RGB {
    let border = max(8, min(width, height) / 80)
    var red: [Int] = []
    var green: [Int] = []
    var blue: [Int] = []

    for y in 0..<height {
        for x in 0..<width where x < border || x >= width - border || y < border || y >= height - border {
            let value = pixels[y * width + x]
            red.append(value.r)
            green.append(value.g)
            blue.append(value.b)
        }
    }
    return RGB(NSColor(
        deviceRed: CGFloat(median(red)) / 255,
        green: CGFloat(median(green)) / 255,
        blue: CGFloat(median(blue)) / 255,
        alpha: 1
    ))
}

func squaredDistance(_ lhs: RGB, _ rhs: RGB) -> Int {
    let red = lhs.r - rhs.r
    let green = lhs.g - rhs.g
    let blue = lhs.b - rhs.b
    return red * red + green * green + blue * blue
}

func neighbors(of index: Int, width: Int, height: Int, diagonals: Bool) -> [Int] {
    let x = index % width
    let y = index / width
    let offsets = diagonals
        ? [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
        : [(0, -1), (-1, 0), (1, 0), (0, 1)]
    return offsets.compactMap { dx, dy in
        let nextX = x + dx
        let nextY = y + dy
        guard nextX >= 0, nextX < width, nextY >= 0, nextY < height else { return nil }
        return nextY * width + nextX
    }
}

func floodBackground(pixels: [RGB], width: Int, height: Int, color: RGB, distance: Int) -> [Bool] {
    let limit = distance * distance
    var background = [Bool](repeating: false, count: pixels.count)
    var queue: [Int] = []

    func add(_ index: Int) {
        guard !background[index], squaredDistance(pixels[index], color) <= limit else { return }
        background[index] = true
        queue.append(index)
    }

    for x in 0..<width {
        add(x)
        add((height - 1) * width + x)
    }
    for y in 0..<height {
        add(y * width)
        add(y * width + width - 1)
    }

    var cursor = 0
    while cursor < queue.count {
        let index = queue[cursor]
        cursor += 1
        for next in neighbors(of: index, width: width, height: height, diagonals: false) {
            add(next)
        }
    }
    return background
}

func largestForeground(background: [Bool], width: Int, height: Int) -> [Bool] {
    var visited = background
    var largest: [Int] = []

    for start in visited.indices where !visited[start] {
        var component: [Int] = [start]
        var cursor = 0
        visited[start] = true
        while cursor < component.count {
            let index = component[cursor]
            cursor += 1
            for next in neighbors(of: index, width: width, height: height, diagonals: true) where !visited[next] {
                visited[next] = true
                component.append(next)
            }
        }
        if component.count > largest.count {
            largest = component
        }
    }

    var foreground = [Bool](repeating: false, count: background.count)
    for index in largest {
        foreground[index] = true
    }
    return foreground
}

func edgeBand(
    foreground: [Bool],
    width: Int,
    height: Int,
    radius: Int
) -> [Bool] {
    var depth = [Int16](repeating: -1, count: foreground.count)
    var queue: [Int] = []
    queue.reserveCapacity(foreground.count / 10)

    for index in foreground.indices where foreground[index] {
        if neighbors(of: index, width: width, height: height, diagonals: true).contains(where: { !foreground[$0] }) {
            depth[index] = 1
            queue.append(index)
        }
    }

    var cursor = 0
    while cursor < queue.count {
        let index = queue[cursor]
        cursor += 1
        let currentDepth = Int(depth[index])
        guard currentDepth < radius else { continue }
        for next in neighbors(of: index, width: width, height: height, diagonals: true)
            where foreground[next] && depth[next] == -1 {
            depth[next] = Int16(currentDepth + 1)
            queue.append(next)
        }
    }

    return depth.map { value in
        value > 0 && value <= radius
    }
}

func writePixel(_ value: RGB, alpha: UInt8, at offset: Int, into buffer: UnsafeMutablePointer<UInt8>) {
    buffer[offset] = UInt8(value.r)
    buffer[offset + 1] = UInt8(value.g)
    buffer[offset + 2] = UInt8(value.b)
    buffer[offset + 3] = alpha
}

func clearPixel(at offset: Int, in buffer: UnsafeMutablePointer<UInt8>) {
    for channel in 0..<4 {
        buffer[offset + channel] = 0
    }
}

func extract(input: URL, output: URL, distance: Int, edgeRadius: Int) throws {
    guard let image = NSImage(contentsOf: input),
          let tiff = image.tiffRepresentation,
          let source = NSBitmapImageRep(data: tiff) else {
        throw ExtractionError.load(input)
    }

    let width = source.pixelsWide
    let height = source.pixelsHigh
    var pixels = [RGB]()
    pixels.reserveCapacity(width * height)
    for y in 0..<height {
        for x in 0..<width {
            pixels.append(RGB(source.colorAt(x: x, y: y)!))
        }
    }

    let sampledBackground = backgroundColor(pixels: pixels, width: width, height: height)
    let background = floodBackground(
        pixels: pixels,
        width: width,
        height: height,
        color: sampledBackground,
        distance: distance
    )
    let foreground = largestForeground(background: background, width: width, height: height)
    let decontaminationBand = edgeBand(
        foreground: foreground,
        width: width,
        height: height,
        radius: edgeRadius
    )

    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bitmapFormat: .alphaNonpremultiplied,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else { throw ExtractionError.bitmap }

    guard let buffer = bitmap.bitmapData else { throw ExtractionError.bitmap }
    let graphite = RGB(NSColor(deviceRed: 59 / 255, green: 58 / 255, blue: 56 / 255, alpha: 1))
    let accent = RGB(NSColor(deviceRed: 233 / 255, green: 124 / 255, blue: 77 / 255, alpha: 1))
    let graphiteDistance = sqrt(Double(squaredDistance(sampledBackground, graphite)))
    let accentDistance = sqrt(Double(squaredDistance(sampledBackground, accent)))

    for index in pixels.indices {
        let x = index % width
        let y = index / width
        let offset = y * bitmap.bytesPerRow + x * 4
        if foreground[index] {
            let value = pixels[index]
            if decontaminationBand[index] {
                let isWarmEdge = value.r - value.g > 6 && value.r - value.b > 12
                let target = isWarmEdge ? accent : graphite
                let targetDistance = isWarmEdge ? accentDistance : graphiteDistance
                let observedDistance = sqrt(Double(squaredDistance(value, sampledBackground)))
                let alpha = min(1, max(0, observedDistance / targetDistance))
                writePixel(target, alpha: UInt8(round(alpha * 255)), at: offset, into: buffer)
            } else {
                writePixel(value, alpha: 255, at: offset, into: buffer)
            }
        } else {
            clearPixel(at: offset, in: buffer)
        }
    }

    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw ExtractionError.encode
    }
    try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
    try data.write(to: output, options: .atomic)

    let foregroundCount = foreground.reduce(0) { $0 + ($1 ? 1 : 0) }
    let percent = Double(foregroundCount) / Double(width * height) * 100
    print(String(
        format: "background #%02X%02X%02X; foreground %.2f%%; threshold %d; edge radius %d",
        sampledBackground.r,
        sampledBackground.g,
        sampledBackground.b,
        percent,
        distance,
        edgeRadius
    ))
}

do {
    let arguments = CommandLine.arguments
    guard (3...5).contains(arguments.count) else { throw ExtractionError.usage }
    let distance = arguments.count >= 4 ? Int(arguments[3]) ?? 18 : 18
    let edgeRadius = arguments.count == 5 ? Int(arguments[4]) ?? 8 : 8
    try extract(
        input: URL(fileURLWithPath: arguments[1]),
        output: URL(fileURLWithPath: arguments[2]),
        distance: distance,
        edgeRadius: max(1, edgeRadius)
    )
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
