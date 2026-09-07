import AppKit
import SwiftUI

struct LearningAnswerText: View {
    let content: String
    var availableWidth: CGFloat = 780
    @Environment(\.runway) private var runway
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ForEach(AnswerDocument.parse(content)) { block in
                blockView(block.kind).frame(maxWidth: .infinity, alignment: .leading)
            }
            Button(copied ? "已复制" : "复制", systemImage: copied ? "checkmark" : "doc.on.doc") {
                copyAnswer()
            }
            .font(.caption).buttonStyle(.borderless).foregroundStyle(runway.copy)
            .help("复制完整回答，保留格式与来源链接")
            .accessibilityLabel("复制完整回答")
        }
        .textSelection(.enabled)
        .contextMenu {
            Button("复制完整回答", systemImage: "doc.on.doc") {
                copyAnswer()
            }
        }
        .onChange(of: content) { _, _ in copied = false }
    }

    private func copyAnswer() {
        NSPasteboard.general.clearContents()
        copied = NSPasteboard.general.setString(content, forType: .string)
    }

    private func inline(_ value: String) -> Text {
        if let attributed = try? AttributedString(markdown: value, options:
            .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            return Text(attributed)
        }
        return Text(verbatim: value)
    }

    private func prose(_ value: String) -> some View {
        inline(value).font(.body).lineSpacing(5).fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder private func blockView(_ kind: AnswerBlock.Kind) -> some View {
        switch kind {
        case .paragraph(let value):
            prose(value)
        case .heading(let level, let value):
            inline(value).font(level <= 2 ? .title3.weight(.semibold) : .headline)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, level <= 2 ? 12 : 6).accessibilityAddTraits(.isHeader)
        case .list(let items):
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(["-", "*", "+", "•"].contains(item.marker) ? "•" : item.marker)
                            .monospacedDigit().frame(minWidth: 20, alignment: .trailing)
                            .foregroundStyle(runway.copy)
                        prose(item.text).frame(maxWidth: .infinity, alignment: .leading)
                    }.padding(.leading, CGFloat(item.indent) * 16).accessibilityElement(children: .combine)
                }
            }
        case .table(let headers, let rows):
            answerTable(headers, rows)
        case .quote(let value):
            HStack(alignment: .top, spacing: 14) {
                Rectangle().fill(runway.decorativeAccent.opacity(0.5)).frame(width: 3).accessibilityHidden(true)
                prose(value).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 4)
            }.fixedSize(horizontal: false, vertical: true)
        case .rule:
            Rectangle().fill(runway.hairline).frame(height: 1).padding(.vertical, 6).accessibilityHidden(true)
        case .code(let language, let value):
            VStack(alignment: .leading, spacing: 8) {
                if !language.isEmpty {
                    Text(verbatim: language).font(.caption).foregroundStyle(runway.copy)
                }
                Text(verbatim: value).font(.system(.body, design: .monospaced))
                    .lineSpacing(4).fixedSize(horizontal: false, vertical: true)
            }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
                .background(runway.field, in: RoundedRectangle(cornerRadius: 8))
        case .flow(let labels, let complete):
            flow(labels, complete: complete)
        }
    }

    @ViewBuilder private func answerTable(_ headers: [String], _ rows: [[String]]) -> some View {
        if availableWidth >= CGFloat(headers.count) * 175 {
            Grid(alignment: .topLeading, horizontalSpacing: 16, verticalSpacing: 12) {
                GridRow {
                    ForEach(Array(headers.enumerated()), id: \.offset) { _, heading in
                        inline(heading).font(.callout.weight(.semibold))
                            .frame(maxWidth: .infinity, alignment: .leading).accessibilityAddTraits(.isHeader)
                    }
                }
                Rectangle().fill(runway.hairline).frame(height: 1).gridCellUnsizedAxes(.horizontal).accessibilityHidden(true)
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    GridRow {
                        ForEach(Array(row.enumerated()), id: \.offset) { column, value in
                            prose(value).frame(maxWidth: .infinity, alignment: .leading)
                                .accessibilityLabel(Text("\(headers[column])：\(value)"))
                        }
                    }
                    if index < rows.count - 1 {
                        Rectangle().fill(runway.hairline).frame(height: 1).gridCellUnsizedAxes(.horizontal).accessibilityHidden(true)
                    }
                }
            }
        } else {
            VStack(alignment: .leading, spacing: 14) {
                if rows.isEmpty { prose(headers.joined(separator: " · ")) }
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(row.enumerated()), id: \.offset) { column, value in
                            VStack(alignment: .leading, spacing: 3) {
                                inline(headers[column]).font(.callout.weight(.semibold))
                                prose(value)
                            }.accessibilityElement(children: .combine)
                        }
                    }
                    if index < rows.count - 1 { Divider().accessibilityHidden(true) }
                }
            }
        }
    }

    private func flowNode(_ label: String) -> some View {
        prose(label).padding(.horizontal, 14).padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(runway.field, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(runway.hairline, lineWidth: 1))
    }

    @ViewBuilder private func flow(_ labels: [String], complete: Bool) -> some View {
        if !complete {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(labels.enumerated()), id: \.offset) { index, value in prose("\(index + 1). \(value)") }
            }
        } else if availableWidth >= CGFloat(labels.count) * 150 + CGFloat(labels.count - 1) * 28 {
            HStack(alignment: .center, spacing: 8) {
                ForEach(Array(labels.enumerated()), id: \.offset) { index, value in
                    flowNode(value)
                    if index < labels.count - 1 {
                        Image(systemName: "arrow.right").foregroundStyle(runway.copy).accessibilityHidden(true)
                    }
                }
            }.accessibilityElement(children: .contain)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(labels.enumerated()), id: \.offset) { index, value in
                    flowNode(value)
                    if index < labels.count - 1 {
                        Image(systemName: "arrow.down").foregroundStyle(runway.copy)
                            .padding(.leading, 18).accessibilityHidden(true)
                    }
                }
            }.accessibilityElement(children: .contain)
        }
    }
}
