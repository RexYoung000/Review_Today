import SwiftUI

/// The approved Recall mark. Character poses remain separate from brand identity.
struct BrandMark: View {
    let size: CGFloat
    @Environment(\.runway) private var runway

    var body: some View {
        Image("BrandRecallMark")
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .foregroundStyle(runway.ink)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}
