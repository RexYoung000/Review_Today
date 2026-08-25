#!/usr/bin/env swift

import AppKit
import CoreImage
import Foundation

private let names = ["closed", "small", "medium", "wide", "finish"]
private let alphaThreshold: UInt8 = 10
private let mergeGap = 18
private let padding = 10
private let opaqueBackgroundTolerance = 54

guard CommandLine.arguments.count == 3 else {
    fputs("Usage: swift brand/split_mouth_sheet.swift INPUT.png OUTPUT_DIR\n", stderr)
    exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)

guard let image = NSImage(contentsOf: inputURL) else {
    fputs("Unable to load \(inputURL.path)\n", stderr)
    exit(3)
}

var proposedRect = CGRect(origin: .zero, size: image.size)
guard let source = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
    fputs("Unable to decode \(inputURL.path)\n", stderr)
    exit(4)
}

let width = source.width
let height = source.height
let bytesPerRow = width * 4
var pixels = [UInt8](repeating: 0, count: height * bytesPerRow)

guard let bitmap = CGContext(
    data: &pixels,
    width: width,
    height: height,
    bitsPerComponent: 8,
    bytesPerRow: bytesPerRow,
    space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
) else {
    fputs("Unable to create bitmap context\n", stderr)
    exit(5)
}

bitmap.translateBy(x: 0, y: CGFloat(height))
bitmap.scaleBy(x: 1, y: -1)
bitmap.draw(source, in: CGRect(x: 0, y: 0, width: width, height: height))

// Image generation can return a visually uniform paper background instead of
// real alpha. Remove only the edge-connected paper area before detecting and
// splitting the five generated mouth drawings. Enclosed light areas (such as
// the two front teeth) are intentionally preserved.
let isOpaque = stride(from: 3, to: pixels.count, by: 4).allSatisfy { pixels[$0] == 255 }
if isOpaque {
    let sampleRadius = min(8, min(width, height))
    var sampleR = 0
    var sampleG = 0
    var sampleB = 0
    var sampleCount = 0

    for y in 0 ..< sampleRadius {
        for x in 0 ..< sampleRadius {
            let index = y * bytesPerRow + x * 4
            sampleR += Int(pixels[index])
            sampleG += Int(pixels[index + 1])
            sampleB += Int(pixels[index + 2])
            sampleCount += 1
        }
    }

    let background = (
        r: sampleR / max(1, sampleCount),
        g: sampleG / max(1, sampleCount),
        b: sampleB / max(1, sampleCount)
    )

    func resemblesBackground(_ pixelIndex: Int) -> Bool {
        let redDistance = abs(Int(pixels[pixelIndex]) - background.r)
        let greenDistance = abs(Int(pixels[pixelIndex + 1]) - background.g)
        let blueDistance = abs(Int(pixels[pixelIndex + 2]) - background.b)
        return max(redDistance, greenDistance, blueDistance) <= opaqueBackgroundTolerance
    }

    var visited = [Bool](repeating: false, count: width * height)
    var queue: [Int] = []
    queue.reserveCapacity(width * height / 2)

    func enqueue(_ x: Int, _ y: Int) {
        let position = y * width + x
        guard !visited[position] else { return }
        let pixelIndex = y * bytesPerRow + x * 4
        guard resemblesBackground(pixelIndex) else { return }
        visited[position] = true
        queue.append(position)
    }

    for x in 0 ..< width {
        enqueue(x, 0)
        enqueue(x, height - 1)
    }
    for y in 0 ..< height {
        enqueue(0, y)
        enqueue(width - 1, y)
    }

    var cursor = 0
    while cursor < queue.count {
        let position = queue[cursor]
        cursor += 1
        let x = position % width
        let y = position / width
        if x > 0 { enqueue(x - 1, y) }
        if x + 1 < width { enqueue(x + 1, y) }
        if y > 0 { enqueue(x, y - 1) }
        if y + 1 < height { enqueue(x, y + 1) }
    }

    for position in queue {
        let pixelIndex = position / width * bytesPerRow + position % width * 4
        pixels[pixelIndex] = 0
        pixels[pixelIndex + 1] = 0
        pixels[pixelIndex + 2] = 0
        pixels[pixelIndex + 3] = 0
    }
}

guard let cleanedSource = bitmap.makeImage() else {
    fputs("Unable to create cleaned source image\n", stderr)
    exit(6)
}
let cleanedImage = CIImage(cgImage: cleanedSource).oriented(.downMirrored)

func alphaAt(x: Int, y: Int) -> UInt8 {
    pixels[y * bytesPerRow + x * 4 + 3]
}

var activeColumns = [Bool](repeating: false, count: width)
for x in 0 ..< width {
    activeColumns[x] = (0 ..< height).contains { alphaAt(x: x, y: $0) > alphaThreshold }
}

var rawRanges: [ClosedRange<Int>] = []
var start: Int?
for x in 0 ... width {
    let active = x < width && activeColumns[x]
    if active, start == nil {
        start = x
    } else if !active, let rangeStart = start {
        rawRanges.append(rangeStart ... max(rangeStart, x - 1))
        start = nil
    }
}

var ranges: [ClosedRange<Int>] = []
for range in rawRanges {
    if let previous = ranges.last, range.lowerBound - previous.upperBound <= mergeGap {
        ranges[ranges.count - 1] = previous.lowerBound ... range.upperBound
    } else {
        ranges.append(range)
    }
}
ranges = ranges.filter { $0.count >= 8 }

guard ranges.count == names.count else {
    fputs("Expected \(names.count) mouth regions, found \(ranges.count): \(ranges)\n", stderr)
    exit(6)
}

var bounds: [CGRect] = []
for range in ranges {
    var minY = height
    var maxY = 0
    for x in range {
        for y in 0 ..< height where alphaAt(x: x, y: y) > alphaThreshold {
            minY = min(minY, y)
            maxY = max(maxY, y)
        }
    }
    let minX = max(0, range.lowerBound - padding)
    let maxX = min(width - 1, range.upperBound + padding)
    minY = max(0, minY - padding)
    maxY = min(height - 1, maxY + padding)
    bounds.append(CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1))
}

let canvasWidth = Int(bounds.map(\.width).max() ?? 1)
let canvasHeight = Int(bounds.map(\.height).max() ?? 1)
let ciContext = CIContext(options: [.useSoftwareRenderer: false])
try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)

for (index, topLeftBounds) in bounds.enumerated() {
    let sourceBounds = CGRect(
        x: topLeftBounds.minX,
        y: topLeftBounds.minY,
        width: topLeftBounds.width,
        height: topLeftBounds.height
    )
    let cropped = cleanedImage.cropped(to: sourceBounds)
    let offsetX = (CGFloat(canvasWidth) - sourceBounds.width) / 2 - sourceBounds.minX
    let offsetY = (CGFloat(canvasHeight) - sourceBounds.height) / 2 - sourceBounds.minY
    let positioned = cropped.transformed(by: CGAffineTransform(translationX: offsetX, y: offsetY))
    let canvas = CIImage(color: .clear).cropped(to: CGRect(x: 0, y: 0, width: canvasWidth, height: canvasHeight))
    let output = positioned.composited(over: canvas)
    guard let cgOutput = ciContext.createCGImage(output, from: output.extent) else {
        fputs("Unable to render \(names[index]) mouth\n", stderr)
        exit(8)
    }
    let representation = NSBitmapImageRep(cgImage: cgOutput)
    guard let png = representation.representation(using: .png, properties: [:]) else {
        fputs("Unable to encode \(names[index]) mouth\n", stderr)
        exit(9)
    }
    let destination = outputURL.appendingPathComponent("mascot-mouth-\(names[index])-v12-1.png")
    try png.write(to: destination)
    print("WROTE \(destination.path) \(canvasWidth)x\(canvasHeight)")
}
