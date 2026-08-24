#!/usr/bin/env swift

import AppKit
import Foundation

struct RGB {
    var r: Int
    var g: Int
    var b: Int

    static func from(_ color: NSColor) -> RGB {
        let value = color.usingColorSpace(.deviceRGB)!
        return RGB(
            r: Int(round(value.redComponent * 255)),
            g: Int(round(value.greenComponent * 255)),
            b: Int(round(value.blueComponent * 255))
        )
    }

    var color: NSColor {
        NSColor(
            deviceRed: CGFloat(r) / 255,
            green: CGFloat(g) / 255,
            blue: CGFloat(b) / 255,
            alpha: 1
        )
    }
}

enum PaletteError: Error, CustomStringConvertible {
    case usage
    case load(URL)
    case encode

    var description: String {
        switch self {
        case .usage:
            return "Usage: apply_sampled_palette.swift mascot|icon|mark INPUT.png OUTPUT.png"
        case .load(let url):
            return "Could not load image: \(url.path)"
        case .encode:
            return "Could not encode PNG"
        }
    }
}

let canvas = RGB(r: 254, g: 249, b: 242)        // #FEF9F2
let mascotHead = RGB(r: 255, g: 247, b: 232)   // #FFF7E8
let iconHead = RGB(r: 254, g: 244, b: 227)     // #FEF4E3
let mascotBody = RGB(r: 252, g: 239, b: 214)   // #FCEFD6
let cardPaper = RGB(r: 254, g: 248, b: 237)    // #FEF8ED
let iconField = RGB(r: 229, g: 142, b: 109)    // #E58E6D
let graphite = RGB(r: 59, g: 58, b: 56)        // #3B3A38
let accent = RGB(r: 233, g: 124, b: 77)        // #E97C4D

func clamp(_ value: Int) -> Int { min(255, max(0, value)) }

func isLightFill(_ value: RGB) -> Bool {
    value.r > 180 && value.g > 165 && value.b > 135
}

func isCoral(_ value: RGB) -> Bool {
    value.r > 150 && value.r - value.g > 18 && value.g - value.b > 4 && value.b < 210
}

func isGraphite(_ value: RGB) -> Bool {
    let maximum = max(value.r, value.g, value.b)
    let minimum = min(value.r, value.g, value.b)
    return maximum < 145 && maximum - minimum < 24
}

func median(_ values: [Int]) -> Int {
    values.sorted()[values.count / 2]
}

func floodMask(
    width: Int,
    height: Int,
    pixels: [RGB],
    seeds: [(Int, Int)],
    predicate: (RGB) -> Bool
) -> [Bool] {
    var mask = [Bool](repeating: false, count: width * height)
    var queue: [Int] = []

    for (x, y) in seeds where x >= 0 && x < width && y >= 0 && y < height {
        let index = y * width + x
        if predicate(pixels[index]) && !mask[index] {
            mask[index] = true
            queue.append(index)
        }
    }

    var cursor = 0
    while cursor < queue.count {
        let index = queue[cursor]
        cursor += 1
        let x = index % width
        let y = index / width
        let neighbors = [
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1)
        ]

        for (nextX, nextY) in neighbors where nextX >= 0 && nextX < width && nextY >= 0 && nextY < height {
            let nextIndex = nextY * width + nextX
            if !mask[nextIndex] && predicate(pixels[nextIndex]) {
                mask[nextIndex] = true
                queue.append(nextIndex)
            }
        }
    }

    return mask
}

func borderSeeds(width: Int, height: Int) -> [(Int, Int)] {
    var seeds: [(Int, Int)] = []
    for x in 0..<width {
        seeds.append((x, 0))
        seeds.append((x, height - 1))
    }
    for y in 0..<height {
        seeds.append((0, y))
        seeds.append((width - 1, y))
    }
    return seeds
}

func normalizedSeeds(_ points: [(Double, Double)], width: Int, height: Int) -> [(Int, Int)] {
    points.map { point in
        (Int(point.0 * Double(width)), Int(point.1 * Double(height)))
    }
}

func shift(mask: [Bool], pixels: inout [RGB], target: RGB, excluding excluded: [Bool]? = nil) {
    var rs: [Int] = []
    var gs: [Int] = []
    var bs: [Int] = []

    for index in pixels.indices where mask[index] && !(excluded?[index] ?? false) {
        rs.append(pixels[index].r)
        gs.append(pixels[index].g)
        bs.append(pixels[index].b)
    }
    guard !rs.isEmpty else { return }

    let delta = RGB(
        r: target.r - median(rs),
        g: target.g - median(gs),
        b: target.b - median(bs)
    )
    for index in pixels.indices where mask[index] && !(excluded?[index] ?? false) {
        pixels[index].r = clamp(pixels[index].r + delta.r)
        pixels[index].g = clamp(pixels[index].g + delta.g)
        pixels[index].b = clamp(pixels[index].b + delta.b)
    }
}

func shiftBodyGradient(
    mask: [Bool],
    pixels: inout [RGB],
    width: Int,
    height: Int,
    topTarget: RGB,
    bottomTarget: RGB,
    blendStart: Double,
    blendEnd: Double,
    excluding excluded: [Bool]? = nil
) {
    var topR: [Int] = []
    var topG: [Int] = []
    var topB: [Int] = []
    var bottomR: [Int] = []
    var bottomG: [Int] = []
    var bottomB: [Int] = []

    for index in pixels.indices where mask[index] && !(excluded?[index] ?? false) {
        let normalizedY = Double(index / width) / Double(height)
        if normalizedY < blendStart {
            topR.append(pixels[index].r)
            topG.append(pixels[index].g)
            topB.append(pixels[index].b)
        } else if normalizedY > blendEnd {
            bottomR.append(pixels[index].r)
            bottomG.append(pixels[index].g)
            bottomB.append(pixels[index].b)
        }
    }
    guard !topR.isEmpty, !bottomR.isEmpty else { return }

    let topDelta = RGB(
        r: topTarget.r - median(topR),
        g: topTarget.g - median(topG),
        b: topTarget.b - median(topB)
    )
    let bottomDelta = RGB(
        r: bottomTarget.r - median(bottomR),
        g: bottomTarget.g - median(bottomG),
        b: bottomTarget.b - median(bottomB)
    )

    for index in pixels.indices where mask[index] && !(excluded?[index] ?? false) {
        let normalizedY = Double(index / width) / Double(height)
        let rawProgress = (normalizedY - blendStart) / (blendEnd - blendStart)
        let progress = min(1, max(0, rawProgress))
        let smoothProgress = progress * progress * (3 - 2 * progress)
        let redDelta = Int(round(Double(topDelta.r) * (1 - smoothProgress) + Double(bottomDelta.r) * smoothProgress))
        let greenDelta = Int(round(Double(topDelta.g) * (1 - smoothProgress) + Double(bottomDelta.g) * smoothProgress))
        let blueDelta = Int(round(Double(topDelta.b) * (1 - smoothProgress) + Double(bottomDelta.b) * smoothProgress))
        pixels[index].r = clamp(pixels[index].r + redDelta)
        pixels[index].g = clamp(pixels[index].g + greenDelta)
        pixels[index].b = clamp(pixels[index].b + blueDelta)
    }
}

func apply(mode: String, input: URL, output: URL) throws {
    guard let image = NSImage(contentsOf: input),
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff) else {
        throw PaletteError.load(input)
    }

    let width = bitmap.pixelsWide
    let height = bitmap.pixelsHigh
    var pixels = [RGB](repeating: RGB(r: 0, g: 0, b: 0), count: width * height)
    for y in 0..<height {
        for x in 0..<width {
            pixels[y * width + x] = RGB.from(bitmap.colorAt(x: x, y: y)!)
        }
    }

    var graphiteMask = [Bool](repeating: false, count: pixels.count)
    for index in pixels.indices where isGraphite(pixels[index]) {
        graphiteMask[index] = true
    }

    let bodySeeds = normalizedSeeds([
        (0.50, 0.37),
        (0.50, 0.84),
        (0.37, 0.64),
        (0.69, 0.70)
    ], width: width, height: height)
    let cardSeeds = normalizedSeeds([
        (0.55, 0.66),
        (0.72, 0.62)
    ], width: width, height: height)
    let bodyMask = floodMask(width: width, height: height, pixels: pixels, seeds: bodySeeds, predicate: isLightFill)
    let cardMask = floodMask(width: width, height: height, pixels: pixels, seeds: cardSeeds, predicate: isLightFill)

    if mode == "mascot" {
        let backgroundMask = floodMask(
            width: width,
            height: height,
            pixels: pixels,
            seeds: borderSeeds(width: width, height: height),
            predicate: isLightFill
        )
        var accentMask = [Bool](repeating: false, count: pixels.count)
        for index in pixels.indices where isCoral(pixels[index]) {
            accentMask[index] = true
        }
        shift(mask: backgroundMask, pixels: &pixels, target: canvas)
        shift(mask: cardMask, pixels: &pixels, target: cardPaper, excluding: backgroundMask)
        shiftBodyGradient(
            mask: bodyMask,
            pixels: &pixels,
            width: width,
            height: height,
            topTarget: mascotHead,
            bottomTarget: mascotBody,
            blendStart: 0.46,
            blendEnd: 0.82,
            excluding: backgroundMask
        )
        shift(mask: accentMask, pixels: &pixels, target: accent)
        shift(mask: graphiteMask, pixels: &pixels, target: graphite)
    } else if mode == "icon" {
        let backgroundMask = floodMask(
            width: width,
            height: height,
            pixels: pixels,
            seeds: borderSeeds(width: width, height: height),
            predicate: isCoral
        )
        var accentMask = [Bool](repeating: false, count: pixels.count)
        for index in pixels.indices {
            if isCoral(pixels[index]) && !backgroundMask[index] {
                accentMask[index] = true
            }
        }
        shift(mask: backgroundMask, pixels: &pixels, target: iconField)
        shift(mask: cardMask, pixels: &pixels, target: cardPaper)
        shiftBodyGradient(
            mask: bodyMask,
            pixels: &pixels,
            width: width,
            height: height,
            topTarget: iconHead,
            bottomTarget: mascotBody,
            blendStart: 0.48,
            blendEnd: 0.86
        )
        shift(mask: accentMask, pixels: &pixels, target: accent)
        shift(mask: graphiteMask, pixels: &pixels, target: graphite)
    } else if mode == "mark" {
        let backgroundMask = floodMask(
            width: width,
            height: height,
            pixels: pixels,
            seeds: borderSeeds(width: width, height: height),
            predicate: isLightFill
        )
        shift(mask: backgroundMask, pixels: &pixels, target: canvas)
        shift(mask: graphiteMask, pixels: &pixels, target: graphite)
    } else {
        throw PaletteError.usage
    }

    for y in 0..<height {
        for x in 0..<width {
            bitmap.setColor(pixels[y * width + x].color, atX: x, y: y)
        }
    }
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw PaletteError.encode
    }
    try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
    try data.write(to: output, options: .atomic)
}

do {
    let arguments = CommandLine.arguments
    guard arguments.count == 4 else { throw PaletteError.usage }
    try apply(
        mode: arguments[1],
        input: URL(fileURLWithPath: arguments[2]),
        output: URL(fileURLWithPath: arguments[3])
    )
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
