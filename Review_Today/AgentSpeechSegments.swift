import Foundation

/// A conservative speech projection of the visible answer, never a summary.
/// Callers own append-only/reset detection and compare the returned Equatable
/// prefix with what has already been queued or played.
struct AgentSpeechSegments {
    enum Kind: Equatable { case speech, visualNotice }
    struct Segment: Equatable {
        let kind: Kind
        let text: String
        /// Exclusive UTF-16 source offset, suitable for NSString/server ranges.
        let sourceEnd: Int
    }

    /// The unfinished last line waits for a newline (or final=true), because a
    /// seemingly ordinary sentence can still become a Markdown table header.
    /// Complete lines yield confirmed sentences; final flushes the remaining
    /// prose. maxCharacters is a UTF-16 limit, with a minimum of 32 for notices.
    static func project(_ accumulatedText: String, final: Bool = false, maxCharacters: Int = 180) -> [Segment] {
        var projector = Projector(accumulatedText, final: final, limit: max(32, maxCharacters))
        return projector.run()
    }

    private struct Unit {
        var char: Character
        var end: Int
    }
    private struct Line {
        let start: Int
        let end: Int
        let after: Int
        let complete: Bool
    }
    private enum Atom {
        case text(Unit)
        case notice(String, Int)
    }
    private struct Projector {
        let units: [Unit]
        let lines: [Line]
        let final: Bool
        let limit: Int
        var output: [Segment] = []
        var paragraph: [Unit] = []

        init(_ source: String, final: Bool, limit: Int) {
            var offset = 0
            var values: [Unit] = []
            var rows: [Line] = []
            var start = 0
            for char in source {
                offset += String(char).utf16.count
                values.append(Unit(char: char, end: offset))
                if char.isNewline {
                    rows.append(Line(start: start, end: values.count - 1, after: values.count, complete: true))
                    start = values.count
                }
            }
            if start < values.count { rows.append(Line(start: start, end: values.count, after: values.count, complete: false)) }
            units = values; lines = rows; self.final = final; self.limit = limit
        }

        mutating func run() -> [Segment] {
            let available = final ? lines.count : lines.prefix(while: \.complete).count
            var index = 0
            while index < available {
                let row = lines[index]
                let text = lineText(row)
                let trimmed = text.trimmingCharacters(in: .whitespaces)
                if trimmed.isEmpty {
                    flushParagraph(complete: true); index += 1; continue
                }
                if let fence = fenceStart(trimmed) {
                    flushParagraph(complete: true)
                    var end = index + 1
                    while end < available && !fenceEnd(lineText(lines[end]), fence: fence) { end += 1 }
                    guard end < available || final else { return output }
                    let last = end < available ? lines[end] : lines[available - 1]
                    notice("图表/代码请看文字。", end: sourceEnd(last))
                    index = min(end + 1, available)
                    continue
                }
                if let header = cells(trimmed) {
                    // Even a header containing sentence punctuation must wait.
                    guard index + 1 < available || final else { flushParagraph(complete: false); return output }
                    if index + 1 < available, let separator = cells(lineText(lines[index + 1])),
                       separator.count == header.count, separator.allSatisfy({ matches($0, #"^:?-{3,}:?$"#) }) {
                        flushParagraph(complete: true)
                        var end = index + 2
                        while end < available, let rowCells = cells(lineText(lines[end])), rowCells.count == header.count { end += 1 }
                        guard end < available || final else { return output }
                        notice("图表/代码请看文字。", end: sourceEnd(lines[end - 1]))
                        index = end
                        continue
                    }
                }
                if matches(trimmed, #"^(flowchart|graph)\s+(TB|TD|BT|RL|LR)\b"#) || trimmed == "sequenceDiagram" {
                    flushParagraph(complete: true)
                    var end = index + 1
                    while end < available && !lineText(lines[end]).trimmingCharacters(in: .whitespaces).isEmpty { end += 1 }
                    guard end < available || final else { return output }
                    notice("图表/代码请看文字。", end: sourceEnd(lines[end - 1]))
                    index = end; continue
                }
                if matches(trimmed, #"^\[[^\]]+\]:\s*\S"#) {
                    flushParagraph(complete: true)
                    notice("链接请看文字。", end: sourceEnd(row)); index += 1; continue
                }
                let compact = trimmed.filter { !$0.isWhitespace }
                if compact.count >= 3, let first = compact.first, "-*_".contains(first), compact.allSatisfy({ $0 == first }) {
                    flushParagraph(complete: true); index += 1; continue
                }
                paragraph += proseUnits(row)
                index += 1
            }
            flushParagraph(complete: final)
            return output
        }

        func lineText(_ line: Line) -> String {
            String(units[line.start..<line.end].map(\.char))
        }
        func sourceEnd(_ line: Line) -> Int {
            line.end > line.start ? units[line.end - 1].end : (line.start > 0 ? units[line.start - 1].end : 0)
        }
        func proseUnits(_ line: Line) -> [Unit] {
            var start = line.start
            while start < line.end && units[start].char.isWhitespace { start += 1 }
            while start < line.end && units[start].char == ">" {
                start += 1
                while start < line.end && units[start].char == " " { start += 1 }
            }
            let rest = String(units[start..<line.end].map(\.char))
            if let range = rest.range(of: #"^#{1,6}\s+|^[-+*•]\s+"#, options: .regularExpression) {
                start += rest[range].count
            }
            var result = Array(units[start..<line.end])
            if line.complete { result.append(Unit(char: "\n", end: units[line.after - 1].end)) }
            return result
        }

        mutating func flushParagraph(complete: Bool) {
            guard !paragraph.isEmpty else { return }
            let parsed = inline(paragraph, complete: complete)
            var speech: [Unit] = []
            for atom in parsed.atoms {
                switch atom {
                case .text(let unit): speech.append(unit)
                case .notice(let text, let end):
                    emitSpeech(speech, flush: true); speech.removeAll()
                    notice(text, end: end)
                }
            }
            emitSpeech(speech, flush: complete && parsed.complete)
            paragraph.removeAll()
        }
        mutating func notice(_ text: String, end: Int) {
            output.append(Segment(kind: .visualNotice, text: text, sourceEnd: end))
        }

        /// Inline constructs must close before any of their text is eligible.
        func inline(_ input: [Unit], complete: Bool) -> (atoms: [Atom], complete: Bool) {
            var atoms: [Atom] = []
            var index = 0
            func prefix(_ start: Int) -> String { String(input[start..<min(input.count, start + 8)].map(\.char)) }
            func missing(_ prompt: String) -> (atoms: [Atom], complete: Bool) {
                if complete, let end = input.last?.end { atoms.append(.notice(prompt, end)); return (atoms, true) }
                return (atoms, false)
            }
            while index < input.count {
                let char = input[index].char
                if char == "\\", index + 1 < input.count, "\\`*{}_[]()#+-.!>|~".contains(input[index + 1].char) {
                    atoms.append(.text(input[index + 1])); index += 2; continue
                }
                if char == "`" {
                    let count = input[index...].prefix(while: { $0.char == "`" }).count
                    guard let close = delimiter(input, from: index + count, char: "`", count: count) else { return missing("图表/代码请看文字。") }
                    atoms.append(.notice("图表/代码请看文字。", input[close + count - 1].end))
                    index = close + count; continue
                }
                let image = char == "!" && index + 1 < input.count && input[index + 1].char == "["
                if char == "[" || image {
                    let open = index + (image ? 1 : 0)
                    guard let close = balanced(input, from: open, opening: "[", closing: "]") else { return missing(image ? "图表/代码请看文字。" : "链接请看文字。") }
                    var after = close + 1
                    while after < input.count && input[after].char.isWhitespace { after += 1 }
                    if after == input.count && !complete { return (atoms, false) }
                    var consumed = close
                    if after < input.count && (input[after].char == "(" || input[after].char == "[") {
                        let opening = input[after].char
                        guard let end = balanced(input, from: after, opening: opening, closing: opening == "(" ? ")" : "]") else { return missing(image ? "图表/代码请看文字。" : "链接请看文字。") }
                        consumed = end
                    }
                    if image {
                        atoms.append(.notice("图表/代码请看文字。", input[consumed].end))
                    } else {
                        var label = inline(Array(input[(open + 1)..<close]), complete: true).atoms
                        if label.isEmpty { label = [.notice("链接请看文字。", input[consumed].end)] }
                        else { label[label.count - 1] = withEnd(label[label.count - 1], input[consumed].end) }
                        atoms += label
                    }
                    index = consumed + 1; continue
                }
                if char == "<" {
                    if index + 1 < input.count, urlStart(prefix(index + 1)) {
                        guard let close = input[(index + 1)...].firstIndex(where: { $0.char == ">" }) else { return missing("链接请看文字。") }
                        atoms.append(.notice("链接请看文字。", input[close].end))
                        index = close + 1; continue
                    }
                }
                if urlStart(prefix(index)) || bareAddress(input, at: index) {
                    var end = index
                    while end < input.count && !input[end].char.isWhitespace && !"。！？<>\"“”".contains(input[end].char) { end += 1 }
                    if end == input.count && !complete { return (atoms, false) }
                    atoms.append(.notice("链接请看文字。", input[end - 1].end))
                    index = end; continue
                }
                if "*_~".contains(char), index + 1 < input.count {
                    let count = input[index...].prefix(while: { $0.char == char }).count
                    let content = index + count
                    let intraword = index > 0 && content < input.count
                        && isASCIIWord(input[index - 1].char) && isASCIIWord(input[content].char)
                    if !intraword, content < input.count, !input[content].char.isWhitespace, (char != "~" || count == 2) {
                        if let close = delimiter(input, from: content, char: char, count: count) {
                            if char == "~" { atoms.append(.notice("划去内容请看文字。", input[close + count - 1].end)) }
                            else {
                                var inner = inline(Array(input[content..<close]), complete: true).atoms
                                if !inner.isEmpty { inner[inner.count - 1] = withEnd(inner[inner.count - 1], input[close + count - 1].end) }
                                atoms += inner
                            }
                            index = close + count; continue
                        } else if !complete { return (atoms, false) }
                    }
                }
                atoms.append(.text(input[index])); index += 1
            }
            return (atoms, true)
        }

        mutating func emitSpeech(_ input: [Unit], flush: Bool) {
            var normalized: [Unit] = []
            for unit in input {
                if unit.char.isWhitespace {
                    if normalized.last?.char != " " && !normalized.isEmpty { normalized.append(Unit(char: " ", end: unit.end)) }
                } else { normalized.append(unit) }
            }
            var start = 0
            var index = 0
            while index < normalized.count {
                if sentenceEnd(normalized, at: index) {
                    var end = index + 1
                    while end < normalized.count && "。！？!?…\"”’」』）)]".contains(normalized[end].char) { end += 1 }
                    emitBounded(Array(normalized[start..<end]))
                    start = end; index = end
                } else { index += 1 }
            }
            if flush { emitBounded(Array(normalized[start...])) }
            else {
                // A long unfinished sentence can yield only a stable, safe
                // punctuation/space boundary, never an arbitrary character cut.
                var pending = Array(normalized[start...])
                while utf16Count(pending) > limit, let cut = safeCut(pending) {
                    emit(Array(pending[..<cut])); pending.removeFirst(cut)
                }
            }
        }
        mutating func emitBounded(_ values: [Unit]) {
            var remaining = values
            while utf16Count(remaining) > limit {
                guard let cut = safeCut(remaining) else {
                    if let end = remaining.last?.end { notice("这段内容较长，请看文字。", end: end) }
                    return
                }
                emit(Array(remaining[..<cut])); remaining.removeFirst(cut)
            }
            emit(remaining)
        }
        mutating func emit(_ values: [Unit]) {
            let nonspace = values.drop(while: { $0.char.isWhitespace }).reversed().drop(while: { $0.char.isWhitespace }).reversed()
            guard let end = nonspace.last?.end else { return }
            let text = String(nonspace.map(\.char))
            guard text.contains(where: { $0.isLetter || $0.isNumber }) else { return }
            output.append(Segment(kind: .speech, text: text, sourceEnd: end))
        }
        func safeCut(_ values: [Unit]) -> Int? {
            var length = 0
            var candidate: Int?
            for (index, value) in values.enumerated() {
                length += String(value.char).utf16.count
                if length > limit { break }
                let insideNumber = index > 0 && index + 1 < values.count
                    && values[index - 1].char.isNumber && values[index + 1].char.isNumber
                if index > 0 && !insideNumber && (value.char.isWhitespace || "，、；：,;:".contains(value.char)) { candidate = index + 1 }
            }
            return candidate
        }
        func sentenceEnd(_ values: [Unit], at index: Int) -> Bool {
            let char = values[index].char
            if "。！？!?".contains(char) { return true }
            guard char == "." else { return false }
            let next = index + 1 < values.count ? values[index + 1].char : nil
            if let next, next == "." || next.isNumber || next.isLetter { return false }
            var start = index
            while start > 0 && (isASCIIWord(values[start - 1].char) || values[start - 1].char == ".") { start -= 1 }
            let token = String(values[start..<index].map(\.char)).lowercased()
            if ["mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "u.s", "u.k"].contains(token) { return false }
            if token.count == 1, token.first?.isLetter == true { return false }
            let prefix = values[..<index].drop(while: { $0.char.isWhitespace })
            if !prefix.isEmpty && prefix.allSatisfy({ $0.char.isNumber }) { return false }
            return next == nil || next!.isWhitespace || "\"”’」』）)]".contains(next!)
        }
        func utf16Count(_ values: [Unit]) -> Int { values.reduce(0) { $0 + String($1.char).utf16.count } }
        func isASCIIWord(_ char: Character) -> Bool {
            char.unicodeScalars.count == 1 && char.unicodeScalars.first!.isASCII && (char.isLetter || char.isNumber)
        }
        func withEnd(_ atom: Atom, _ end: Int) -> Atom {
            switch atom { case .text(let unit): .text(Unit(char: unit.char, end: end)); case .notice(let text, _): .notice(text, end) }
        }
        func balanced(_ input: [Unit], from start: Int, opening: Character, closing: Character) -> Int? {
            var depth = 0
            var index = start
            while index < input.count {
                if input[index].char == "\\" { index += 2; continue }
                if input[index].char == opening { depth += 1 }
                if input[index].char == closing { depth -= 1; if depth == 0 { return index } }
                index += 1
            }
            return nil
        }
        func delimiter(_ input: [Unit], from start: Int, char: Character, count: Int) -> Int? {
            var index = start
            while index < input.count {
                if input[index].char == "\\" { index += 2; continue }
                let run = input[index...].prefix(while: { $0.char == char }).count
                if run == count { return index }
                index += max(1, run)
            }
            return nil
        }
        func urlStart(_ value: String) -> Bool {
            let prefix = value.prefix(8).lowercased()
            return prefix.hasPrefix("https://") || prefix.hasPrefix("http://") || prefix.hasPrefix("www.") || prefix.hasPrefix("mailto:")
        }
        func bareAddress(_ input: [Unit], at index: Int) -> Bool {
            guard isASCIIWord(input[index].char),
                  index == 0 || (!isASCIIWord(input[index - 1].char) && !"._%+-".contains(input[index - 1].char)) else { return false }
            let candidate = String(input[index..<min(input.count, index + 256)].map(\.char))
            return matches(candidate, #"^(?:[A-Za-z0-9._%+-]+@)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?=[:/\?#\s。，！？,;)]|$)"#)
        }
        func fenceStart(_ line: String) -> (Character, Int)? {
            guard let first = line.first, first == "`" || first == "~" else { return nil }
            let count = line.prefix(while: { $0 == first }).count
            return count >= 3 ? (first, count) : nil
        }
        func fenceEnd(_ line: String, fence: (Character, Int)) -> Bool {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            return trimmed.count >= fence.1 && trimmed.allSatisfy { $0 == fence.0 }
        }
        func cells(_ line: String) -> [String]? {
            var pieces: [String] = []
            var cell = ""
            var escaped = false
            var pipes = 0
            for char in line.trimmingCharacters(in: .whitespaces) {
                if escaped { cell.append(char); escaped = false; continue }
                if char == "\\" { escaped = true; cell.append(char); continue }
                if char == "|" { pieces.append(cell.trimmingCharacters(in: .whitespaces)); cell = ""; pipes += 1 }
                else { cell.append(char) }
            }
            pieces.append(cell.trimmingCharacters(in: .whitespaces))
            if pieces.first == "" { pieces.removeFirst() }
            if pieces.last == "" { pieces.removeLast() }
            return pipes > 0 && pieces.count >= 2 ? pieces : nil
        }
        func matches(_ text: String, _ pattern: String) -> Bool { text.range(of: pattern, options: .regularExpression) != nil }
    }
}
