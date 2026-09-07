import SwiftUI

/// The approved Recall mark. Character poses remain separate from brand identity.
struct BrandMark: View {
    let size: CGFloat

    var body: some View {
        Image("BrandDefaultLogo")
            .renderingMode(.original)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}
