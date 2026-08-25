#!/usr/bin/env swift

import AppKit
import Foundation

guard CommandLine.arguments.count >= 4 else {
    fputs("Usage: swift brand/render_mouth_preview.swift BASE.png OUTPUT.png MOUTH...\n", stderr)
    exit(2)
}

let baseURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let mouthURLs = CommandLine.arguments.dropFirst(3).map(URL.init(fileURLWithPath:))

guard let base = NSImage(contentsOf: baseURL) else {
    fputs("Unable to load base image\n", stderr)
    exit(3)
}

let mouths = mouthURLs.compactMap(NSImage.init(contentsOf:))
guard mouths.count == mouthURLs.count else {
    fputs("Unable to load every mouth image\n", stderr)
    exit(4)
}

let panelSize = CGSize(width: 320, height: 380)
let boardSize = CGSize(width: panelSize.width * CGFloat(mouths.count), height: panelSize.height)
let board = NSImage(size: boardSize)
board.lockFocus()

NSColor(red: 0.996, green: 0.976, blue: 0.949, alpha: 1).setFill()
NSBezierPath(rect: CGRect(origin: .zero, size: boardSize)).fill()

let characterHeight: CGFloat = 350
let characterWidth = characterHeight * base.size.width / base.size.height
let mouthScale = characterHeight / base.size.height
let mouthCenterInBase = CGPoint(x: 657, y: base.size.height - 668)

for (index, mouth) in mouths.enumerated() {
    let panelOriginX = CGFloat(index) * panelSize.width
    let characterRect = CGRect(
        x: panelOriginX + (panelSize.width - characterWidth) / 2,
        y: 15,
        width: characterWidth,
        height: characterHeight
    )
    base.draw(in: characterRect, from: .zero, operation: .sourceOver, fraction: 1)

    let mouthSize = CGSize(width: mouth.size.width * mouthScale, height: mouth.size.height * mouthScale)
    let mouthCenter = CGPoint(
        x: characterRect.minX + mouthCenterInBase.x * mouthScale,
        y: characterRect.minY + mouthCenterInBase.y * mouthScale
    )
    let mouthRect = CGRect(
        x: mouthCenter.x - mouthSize.width / 2,
        y: mouthCenter.y - mouthSize.height / 2,
        width: mouthSize.width,
        height: mouthSize.height
    )
    mouth.draw(in: mouthRect, from: .zero, operation: .sourceOver, fraction: 1)
}

board.unlockFocus()

guard
    let tiff = board.tiffRepresentation,
    let representation = NSBitmapImageRep(data: tiff),
    let png = representation.representation(using: .png, properties: [:])
else {
    fputs("Unable to encode preview\n", stderr)
    exit(5)
}

try png.write(to: outputURL)
print("WROTE \(outputURL.path) \(Int(boardSize.width))x\(Int(boardSize.height))")
