import Foundation

/// Continuous pointer coordinates map to discrete, bounded card positions.
enum KnowledgeLocator {
    static func index(y: CGFloat, height: CGFloat, count: Int) -> Int {
        guard count > 1, height > 0 else { return 0 }
        return min(count - 1, max(0, Int((max(0, min(height, y)) / height * CGFloat(count - 1)).rounded())))
    }
    static func y(index: Int, height: CGFloat, count: Int) -> CGFloat {
        guard count > 1 else { return 0 }
        return CGFloat(min(count - 1, max(0, index))) / CGFloat(count - 1) * max(0, height)
    }
}
