import SwiftUI

/// A visible test entrance backed by a different state instance from the review window.
struct PrototypeSummaryPreview: View {
    @Bindable var model: PrototypeState
    @Bindable var capture: PrototypeCapture
    let close: () -> Void
    @State private var complete = false
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                Text("示例小结").font(.caption.weight(.medium))
                Picker("小结示例", selection: $complete) {
                    Text("部分完成").tag(false)
                    Text("全部完成").tag(true)
                }.labelsHidden().pickerStyle(.segmented).frame(width: 194)
                Spacer()
                PrototypeButton(title: "重播动作", symbol: "play") { model.replaySummaryMotion() }
                    .disabled(model.correcting || model.reduced)
                Toggle("减少动态", isOn: $model.reduced).toggleStyle(.checkbox).font(.caption)
            }.padding(.horizontal, 24).padding(.vertical, 12)
            PrototypeReview(model: model, capture: capture, close: close)
        }
        .onChange(of: complete) { _, value in model.loadSummarySample(complete: value) }
    }
}
