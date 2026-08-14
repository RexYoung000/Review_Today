import Foundation

enum UserLanguage {
    /// System preferred language, not the app development region.
    static var primaryCode: String {
        if let preferred = Locale.preferredLanguages.first {
            let code = Locale(identifier: preferred).language.languageCode?.identifier ?? preferred
            if code.lowercased().hasPrefix("zh") { return "zh" }
            if !code.isEmpty { return code }
        }
        return "zh"
    }
}
