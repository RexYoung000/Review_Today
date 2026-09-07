import CoreText
import SwiftUI

/// The welcome bubble uses the original Maiyuan font; the rest of the app keeps system typography.
enum BrandTypography {
    private static let maiYuanRegistered: Bool = {
        guard let url = Bundle.main.url(forResource: "KNMaiyuan-Regular", withExtension: "ttf") else {
            assertionFailure("Missing bundled Maiyuan font")
            return false
        }
        return CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    }()

    static func welcome(size: CGFloat) -> Font {
        guard maiYuanRegistered else { return .system(size: size, design: .rounded) }
        return .custom("KNMaiyuan-Regular", fixedSize: size)
    }
}
