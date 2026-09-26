import AppKit
import CryptoKit
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

struct LearningImageAttachment: Codable, Sendable, Equatable {
    let name: String
    let mimeType: String
    let data: Data
    let thumbnail: Data
    let width: Int
    let height: Int

    nonisolated static let maximumBytes = 8 * 1024 * 1024
    nonisolated static let maximumSide = 8192
    nonisolated static let maximumCount = 8

    enum Failure: LocalizedError {
        case format, size, dimensions, count, unavailable, permission
        var errorDescription: String? {
            switch self {
            case .format: "无法读取这张图片，请选择有效的 PNG 或 JPEG。"
            case .size: "图片超过 8 MB，请压缩文件后重新添加。"
            case .dimensions: "图片边长超过 8192 像素，请分段截图后添加。"
            case .count: "每条消息最多添加 8 张图片；这批图片未添加，已有草稿已保留。"
            case .unavailable: "无法读取拖入的图片，请重试，或先保存为 PNG/JPEG 后通过“＋”添加。"
            case .permission: "macOS 未允许读取这张拖入图片。请在来源中复制图片后粘贴，或将图片保存到本地后添加。"
            }
        }
    }

    nonisolated static func load(_ url: URL) throws -> Self {
        try prepare(readFile(url), name: url.lastPathComponent)
    }

    /// Read only the selected file, with a strict allocation bound. A mapped
    /// Data or URL can otherwise outlive the drag's temporary access grant.
    nonisolated static func readFile(_ url: URL, limit: Int = maximumBytes) throws -> Data {
        guard url.isFileURL else { throw Failure.format }
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        var bytes = Data()
        while bytes.count <= limit {
            let chunk = try file.read(upToCount: min(64 * 1024, limit + 1 - bytes.count)) ?? Data()
            if chunk.isEmpty { break }
            bytes.append(chunk)
        }
        guard bytes.count <= limit else { throw Failure.size }
        return bytes
    }

    nonisolated static func prepare(_ raw: Data, name: String, clipboard: Bool = false) throws -> Self {
        guard raw.count <= (clipboard ? 64 * 1024 * 1024 : maximumBytes) else { throw Failure.size }
        guard let source = CGImageSourceCreateWithData(raw as CFData, nil), CGImageSourceGetCount(source) == 1,
              let type = CGImageSourceGetType(source) as String?,
              type == UTType.png.identifier || type == UTType.jpeg.identifier || (clipboard && type == UTType.tiff.identifier),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int else { throw Failure.format }
        guard min(width, height) > 0, max(width, height) <= maximumSide else { throw Failure.dimensions }
        // Apply orientation to pixels and re-encode without private source metadata.
        guard let pixels = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: max(width, height)
        ] as CFDictionary) else { throw Failure.format }
        let jpeg = type == UTType.jpeg.identifier
        let encoded = try encode(pixels, type: jpeg ? UTType.jpeg.identifier : UTType.png.identifier)
        guard encoded.count <= maximumBytes else { throw Failure.size }
        guard let small = CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 240
        ] as CFDictionary) else { throw Failure.format }
        let clean = String(name.filter { !"/\\\n\r\0".contains($0) }.prefix(128))
        return Self(name: clean.isEmpty ? "图片.png" : clean, mimeType: jpeg ? "image/jpeg" : "image/png",
                    data: encoded, thumbnail: try encode(small, type: UTType.png.identifier), width: pixels.width, height: pixels.height)
    }

    nonisolated private static func encode(_ pixels: CGImage, type: String) throws -> Data {
        let bytes = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(bytes, type as CFString, 1, nil) else { throw Failure.format }
        CGImageDestinationAddImage(destination, pixels, [kCGImageDestinationLossyCompressionQuality: 1.0] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw Failure.format }
        return bytes as Data
    }

    var sha256: String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    var encoded: Data? { try? JSONEncoder().encode(self) }
    static func decode(_ data: Data?) -> Self? { data.flatMap { try? JSONDecoder().decode(Self.self, from: $0) } }
    static func decodeAll(_ data: Data?) -> [Self] {
        guard let data else { return [] }
        if let values = try? JSONDecoder().decode([Self].self, from: data) { return values }
        return decode(data).map { [$0] } ?? []
    }
    static func encodeAll(_ images: [Self]) -> Data? {
        guard !images.isEmpty else { return nil }
        return images.count == 1 ? images[0].encoded : try? JSONEncoder().encode(images)
    }
    var request: [String: Any] { ["name": name, "mime_type": mimeType, "data_base64": data.base64EncodedString(), "sha256": sha256] }
}

struct LearningImageGrid: View {
    let images: [LearningImageAttachment]
    var remove: ((Int) -> Void)? = nil

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 180, maximum: 260), spacing: 8)], spacing: 8) {
            ForEach(images.indices, id: \.self) { index in
                LearningImageChip(attachment: images[index], remove: remove.map { action in { action(index) } })
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

struct LearningMessageImages: View {
    let data: Data?
    let maximumWidth: CGFloat
    @State private var images: [LearningImageAttachment] = []

    var body: some View {
        LearningImageGrid(images: images)
            .frame(maxWidth: max(0, min(maximumWidth, CGFloat(images.count) * 268 - 8)), alignment: .trailing)
            .onChange(of: data, initial: true) { _, value in images = LearningImageAttachment.decodeAll(value) }
    }
}

struct LearningImageChip: View {
    let attachment: LearningImageAttachment
    var remove: (() -> Void)? = nil
    @State private var preview = false

    var body: some View {
        HStack(spacing: 10) {
            Button { preview = true } label: {
                HStack(spacing: 10) {
                    if let thumbnail = NSImage(data: attachment.thumbnail) {
                        Image(nsImage: thumbnail).resizable().scaledToFit().frame(width: 60, height: 46)
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(attachment.name).lineLimit(1).truncationMode(.middle)
                        Text("查看图片").font(.caption).foregroundStyle(.secondary)
                    }
                }.contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityLabel("预览图片：\(attachment.name)")
            if let remove {
                Spacer(minLength: 4)
                Button(action: remove) { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }
                    .buttonStyle(.plain).help("移除图片").accessibilityLabel("移除图片：\(attachment.name)")
            }
        }
        .padding(8)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
        .sheet(isPresented: $preview) { LearningImagePreview(attachment: attachment) }
    }
}

private struct LearningImagePreview: View {
    let attachment: LearningImageAttachment
    @State private var actualSize = false
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text(attachment.name).font(.headline).lineLimit(1).truncationMode(.middle)
                Spacer()
                Toggle("实际大小", isOn: $actualSize).toggleStyle(.checkbox)
                Button("完成") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            GeometryReader { geometry in
                let scale = actualSize ? 1 : min(1, min(geometry.size.width / CGFloat(attachment.width), geometry.size.height / CGFloat(attachment.height)))
                ScrollView([.horizontal, .vertical]) {
                    if let picture = NSImage(data: attachment.data) {
                        Image(nsImage: picture).resizable()
                            .frame(width: CGFloat(attachment.width) * scale, height: CGFloat(attachment.height) * scale)
                            .accessibilityLabel("图片原图")
                    }
                }
            }
        }.padding(20).frame(minWidth: 520, idealWidth: 760, minHeight: 400, idealHeight: 620)
    }
}
