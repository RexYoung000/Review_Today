#!/usr/bin/env swift

import AppKit
import Foundation

enum ValidationError: Error, CustomStringConvertible {
    case usage
    case load(String)
    case missingAlpha(String)
    case opaqueCorner(String, Int, Int, CGFloat)

    var description: String {
        switch self {
        case .usage:
            return "Usage: validate_alpha.swift IMAGE.png [IMAGE.png ...]"
        case .load(let path):
            return "Could not load PNG: \(path)"
        case .missingAlpha(let path):
            return "PNG has no alpha channel: \(path)"
        case .opaqueCorner(let path, let x, let y, let alpha):
            return String(format: "Corner is not transparent: %@ (%d,%d) alpha %.4f", path, x, y, alpha)
        }
    }
}

func validate(path: String) throws {
    let url = URL(fileURLWithPath: path)
    guard let data = try? Data(contentsOf: url),
          let bitmap = NSBitmapImageRep(data: data) else {
        throw ValidationError.load(path)
    }
    guard bitmap.hasAlpha else { throw ValidationError.missingAlpha(path) }

    let corners = [
        (0, 0),
        (bitmap.pixelsWide - 1, 0),
        (0, bitmap.pixelsHigh - 1),
        (bitmap.pixelsWide - 1, bitmap.pixelsHigh - 1)
    ]
    var values: [String] = []
    for (x, y) in corners {
        let alpha = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB)?.alphaComponent ?? 1
        guard alpha <= 0.01 else {
            throw ValidationError.opaqueCorner(path, x, y, alpha)
        }
        values.append(String(format: "%.3f", alpha))
    }

    print("PASS \(path): \(bitmap.pixelsWide)x\(bitmap.pixelsHigh), corner alpha [\(values.joined(separator: ", "))]")
}

do {
    let paths = Array(CommandLine.arguments.dropFirst())
    guard !paths.isEmpty else { throw ValidationError.usage }
    for path in paths {
        try validate(path: path)
    }
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
