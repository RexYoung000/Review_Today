import SwiftUI

/// Measure one set of controls. ViewThatFits would construct duplicate menus,
/// popover state and observers for the horizontal and stacked alternatives.
struct ComposerControlsLayout: Layout {
    static func size(_ sizes: [CGSize], available: CGFloat?) -> CGSize {
        guard sizes.count == 2 else { return .zero }
        let row = CGSize(width: sizes[0].width + 4 + sizes[1].width, height: max(sizes[0].height, sizes[1].height))
        if available.map({ $0 < row.width }) == true {
            return CGSize(width: max(sizes[0].width, sizes[1].width), height: sizes[0].height + 2 + sizes[1].height)
        }
        return row
    }
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        Self.size(subviews.map { $0.sizeThatFits(.unspecified) }, available: proposal.width)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard subviews.count == 2 else { return }
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        if bounds.width >= sizes[0].width + 4 + sizes[1].width {
            var x = bounds.minX
            for index in 0..<2 {
                subviews[index].place(at: CGPoint(x: x, y: bounds.midY - sizes[index].height / 2), anchor: .topLeading, proposal: ProposedViewSize(sizes[index]))
                x += sizes[index].width + 4
            }
        } else {
            var y = bounds.minY
            for index in 0..<2 {
                subviews[index].place(at: CGPoint(x: bounds.minX, y: y), anchor: .topLeading, proposal: ProposedViewSize(sizes[index]))
                y += sizes[index].height + 2
            }
        }
    }
}
