import Foundation

/// Presentation only; persisted message text remains the source of truth.
struct AnswerBlock: Identifiable, Equatable {
    var id: Int // Starting source line, stable while the last block streams.
    var kind: Kind
    enum Kind: Equatable {
        case paragraph(String), heading(Int, String), list([ListItem])
        case table([String], [[String]]), quote(String), rule
        case code(String, String), flow([String], complete: Bool), notice(String)
    }
    struct ListItem: Equatable {
        var marker: String
        var text: String
        var indent: Int
    }
}

enum AnswerDocument {
    static func containsQuestion(_ question: String, in answer: String) -> Bool {
        func normalized(_ text: String) -> String {
            text.replacingOccurrences(of: #"[\s*#_>]"#, with: "", options: .regularExpression)
        }
        let key = normalized(question)
        return !key.isEmpty && normalized(answer).contains(key)
    }

    static func parse(_ source: String) -> [AnswerBlock] {
        let lines = source.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var result: [AnswerBlock] = []
        var i = 0
        while i < lines.count {
            let start = i
            let line = lines[i].trimmingCharacters(in: .whitespaces)
            if line.isEmpty { i += 1; continue }
            if ["网页核验暂未完成，先讲基础内容；涉及变化或争议的部分仍需核实。", "网页核验暂未完成，先讲基础内容；需要查证的部分仍待核实。", "部分内容尚待核实。"].contains(line),
               lines.dropFirst(i + 1).allSatisfy({ $0.trimmingCharacters(in: .whitespaces).isEmpty }) {
                result.append(.init(id: start, kind: .notice(line))); i += 1; continue
            }
            if let fence = fenceStart(line) {
                i += 1
                var body: [String] = []
                while i < lines.count && !isFenceEnd(lines[i], fence: fence.marker) {
                    body.append(lines[i]); i += 1
                }
                let closed = i < lines.count
                if closed { i += 1 }
                let text = body.joined(separator: "\n")
                if fence.language.lowercased() == "mermaid",
                   let labels = closed ? linearFlow(text) : flowPreview(text), !labels.isEmpty {
                    result.append(.init(id: start, kind: .flow(labels, complete: closed)))
                } else {
                    result.append(.init(id: start, kind: .code(fence.language, text)))
                }
                continue
            }
            if isRule(line) {
                result.append(.init(id: start, kind: .rule)); i += 1; continue
            }
            if let h = heading(line) {
                result.append(.init(id: start, kind: .heading(h.0, h.1))); i += 1; continue
            }
            if i + 1 < lines.count, let header = cells(line), header.count >= 2,
               let separator = cells(lines[i + 1]), separator.count == header.count,
               separator.allSatisfy({ matches($0, #"^:?-{3,}:?$"#) }) {
                i += 2
                var rows: [[String]] = []
                while i < lines.count, let row = cells(lines[i]), row.count == header.count {
                    rows.append(row); i += 1
                }
                result.append(.init(id: start, kind: .table(header, rows)))
                continue
            }
            if line.hasPrefix(">") {
                var quoted: [String] = []
                while i < lines.count {
                    let value = lines[i].trimmingCharacters(in: .whitespaces)
                    guard value.hasPrefix(">") else { break }
                    quoted.append(String(value.dropFirst()).trimmingCharacters(in: .whitespaces))
                    i += 1
                }
                if quoted.first == "[!NOTE]" {
                    result.append(.init(id: start, kind: .notice(quoted.dropFirst().joined(separator: "\n"))))
                } else {
                    result.append(.init(id: start, kind: .quote(quoted.joined(separator: "\n"))))
                }
                continue
            }
            if listItem(lines[i]) != nil {
                var items: [AnswerBlock.ListItem] = []
                while i < lines.count {
                    if let item = listItem(lines[i]) {
                        items.append(item); i += 1
                    } else if !lines[i].trimmingCharacters(in: .whitespaces).isEmpty,
                              lines[i].hasPrefix("  "), !items.isEmpty {
                        items[items.count - 1].text += "\n" + lines[i].trimmingCharacters(in: .whitespaces)
                        i += 1
                    } else { break }
                }
                result.append(.init(id: start, kind: .list(items)))
                continue
            }
            var paragraph = [lines[i]]
            i += 1
            while i < lines.count {
                let next = lines[i].trimmingCharacters(in: .whitespaces)
                if next.isEmpty || heading(next) != nil || isRule(next) || next.hasPrefix(">") ||
                    fenceStart(next) != nil || listItem(lines[i]) != nil { break }
                if i + 1 < lines.count, let h = cells(next), let s = cells(lines[i + 1]),
                   h.count >= 2, h.count == s.count, s.allSatisfy({ matches($0, #"^:?-{3,}:?$"#) }) { break }
                paragraph.append(lines[i]); i += 1
            }
            result.append(.init(id: start, kind: .paragraph(paragraph.joined(separator: "\n"))))
        }
        return result
    }

    static func matches(_ value: String, _ pattern: String) -> Bool {
        value.range(of: pattern, options: .regularExpression) != nil
    }

    private static func heading(_ line: String) -> (Int, String)? {
        let hashes = line.prefix(while: { $0 == "#" }).count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return (hashes, String(line.dropFirst(hashes + 1)))
    }

    private static func isRule(_ line: String) -> Bool {
        let compact = line.filter { !$0.isWhitespace }
        return compact.count >= 3 && ["-", "*", "_"].contains(String(compact.prefix(1))) && Set(compact).count == 1
    }

    private static func fenceStart(_ line: String) -> (marker: String, language: String)? {
        guard let first = line.first, first == "\u{60}" || first == "~" else { return nil }
        let marker = line.prefix(while: { $0 == first })
        guard marker.count >= 3 else { return nil }
        let language = line.dropFirst(marker.count).trimmingCharacters(in: .whitespaces)
        guard !language.contains("\u{60}") else { return nil }
        return (String(marker), language)
    }

    private static func isFenceEnd(_ line: String, fence: String) -> Bool {
        let clean = line.trimmingCharacters(in: .whitespaces)
        return clean.count >= fence.count && clean.allSatisfy { $0 == fence.first }
    }

    private static func listItem(_ line: String) -> AnswerBlock.ListItem? {
        guard let regex = try? NSRegularExpression(pattern: #"^(\s*)([-+*•]|\d+[.)、])\s+(.+)$"#),
              let match = regex.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)),
              let indent = Range(match.range(at: 1), in: line),
              let marker = Range(match.range(at: 2), in: line),
              let text = Range(match.range(at: 3), in: line) else { return nil }
        return .init(marker: String(line[marker]), text: String(line[text]), indent: min(line[indent].count / 2, 4))
    }

    /// Pipes inside code spans or escaped pipes are content, not column boundaries.
    static func cells(_ line: String) -> [String]? {
        let chars = Array(line.trimmingCharacters(in: .whitespaces))
        var columns: [String] = []
        var value = ""
        var i = 0
        var codeTicks = 0
        var separators = 0
        while i < chars.count {
            if chars[i] == "\\", i + 1 < chars.count {
                if chars[i + 1] == "|" { value.append("|") }
                else { value.append(chars[i]); value.append(chars[i + 1]) }
                i += 2; continue
            }
            if chars[i] == "\u{60}" {
                var end = i
                while end < chars.count && chars[end] == "\u{60}" { end += 1 }
                let count = end - i
                if codeTicks == 0 { codeTicks = count }
                else if codeTicks == count { codeTicks = 0 }
                value += String(repeating: "\u{60}", count: count)
                i = end; continue
            }
            if chars[i] == "|", codeTicks == 0 {
                columns.append(value.trimmingCharacters(in: .whitespaces)); value = ""
                separators += 1
            } else { value.append(chars[i]) }
            i += 1
        }
        guard separators > 0 else { return nil }
        columns.append(value.trimmingCharacters(in: .whitespaces))
        if chars.first == "|" { columns.removeFirst() }
        if chars.last == "|", columns.last == "" { columns.removeLast() }
        return columns
    }

    private static let nodePattern = #"^([A-Za-z][A-Za-z0-9_]*)(?:\[\s*(?:"([^"]*)"|'([^']*)'|([^\]"']+))\s*\])?$"#

    private static func node(_ source: String) -> (String, String?)? {
        let text = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let regex = try? NSRegularExpression(pattern: nodePattern),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let idRange = Range(match.range(at: 1), in: text) else { return nil }
        let label = (2...4).compactMap { index -> String? in
            guard let range = Range(match.range(at: index), in: text) else { return nil }
            return String(text[range]).trimmingCharacters(in: .whitespaces)
        }.first
        guard label == nil || !(label!.isEmpty || label!.contains("<") || label!.contains(">")) else { return nil }
        return (String(text[idRange]), label)
    }

    /// One fully understood directed chain. Unsupported syntax is never partly accepted.
    static func linearFlow(_ source: String) -> [String]? {
        guard let statements = flowStatements(source), !statements.isEmpty else { return nil }
        var labels: [String: String] = [:]
        var declared: Set<String> = []
        var next: [String: String] = [:]
        var previous: [String: String] = [:]
        for statement in statements {
            let pieces = statement.components(separatedBy: "-->")
            var ids: [String] = []
            for piece in pieces {
                guard let (id, label) = node(piece) else { return nil }
                declared.insert(id)
                if let label {
                    if let old = labels[id], old != label { return nil }
                    labels[id] = label
                }
                ids.append(id)
            }
            for index in 0..<max(0, ids.count - 1) {
                let a = ids[index], b = ids[index + 1]
                guard a != b, next[a] == nil || next[a] == b,
                      previous[b] == nil || previous[b] == a else { return nil }
                next[a] = b; previous[b] = a
            }
        }
        guard declared.count >= 2, declared.count <= 24, labels.count == declared.count else { return nil }
        let starts = declared.filter { previous[$0] == nil }
        guard starts.count == 1, var cursor = starts.first else { return nil }
        var visited: Set<String> = []
        var result: [String] = []
        while !visited.contains(cursor) {
            visited.insert(cursor)
            guard let label = labels[cursor] else { return nil }
            result.append(label)
            guard let successor = next[cursor] else { break }
            cursor = successor
        }
        guard visited == declared, next.count == declared.count - 1 else { return nil }
        return result
    }

    private static func flowStatements(_ source: String) -> [String]? {
        let clean = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let header = clean.range(of: #"^flowchart\s+(LR|TD|TB)(?=\s|;|$)"#, options: .regularExpression) else { return nil }
        let body = clean[header.upperBound...]
        var statements: [String] = []
        var current = "", quoted: Character?, depth = 0
        for ch in body {
            if ch == "\"" || ch == "'" {
                if quoted == ch { quoted = nil } else if quoted == nil { quoted = ch }
            }
            if quoted == nil {
                if ch == "[" { depth += 1 }
                if ch == "]" { depth -= 1 }
            }
            if quoted == nil && depth == 0 && (ch == "\n" || ch == ";") {
                if !current.trimmingCharacters(in: .whitespaces).isEmpty { statements.append(current) }
                current = ""
            } else { current.append(ch) }
        }
        guard quoted == nil, depth == 0 else { return nil }
        if !current.trimmingCharacters(in: .whitespaces).isEmpty { statements.append(current) }
        return statements
    }

    private static func flowPreview(_ source: String) -> [String]? {
        guard source.range(of: #"^\s*flowchart\s+(LR|TD|TB)(?=\s|;|$)"#, options: .regularExpression) != nil else { return nil }
        if let full = linearFlow(source) { return full }
        guard let regex = try? NSRegularExpression(pattern: #"[A-Za-z][A-Za-z0-9_]*\[\s*(?:"([^"]*)"|'([^']*)'|([^\]"']+))\s*\]"#) else { return nil }
        var labels: [String] = []
        for match in regex.matches(in: source, range: NSRange(source.startIndex..., in: source)) {
            for index in 1...3 {
                if let range = Range(match.range(at: index), in: source) {
                    labels.append(String(source[range])); break
                }
            }
        }
        if let range = source.range(of: #"\[\s*["']?([^\]\n]*)$"#, options: .regularExpression) {
            let tail = source[range].dropFirst().trimmingCharacters(in: CharacterSet(charactersIn: "\"' "))
            if !tail.isEmpty { labels.append(tail) }
        }
        return labels.isEmpty ? nil : labels
    }
}
