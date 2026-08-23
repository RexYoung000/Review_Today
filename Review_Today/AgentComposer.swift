import AppKit
import SwiftUI

enum CapturePace: String, CaseIterable, Identifiable {
    case turbo
    case standard
    case careful

    var id: String { rawValue }

    var title: String {
        switch self {
        case .turbo: String(localized: "极速")
        case .standard: String(localized: "标准")
        case .careful: String(localized: "仔细")
        }
    }
}

struct AgentComposer: View {
    @Binding var draft: String
    var turns: [CaptureTask]
    var forming: [CaptureTask]
    var pose: CoachPose
    var recorder: VoiceRecorder
    var onSubmit: () -> Void
    var onVoice: () -> Void
    var onOpenInbox: () -> Void
    var onPreview: (UUID) -> Void
    var onOpenKnowledge: (UUID) -> Void
    var receiptLine: (CaptureTask) -> String

    @AppStorage("capturePace") private var paceRaw = CapturePace.standard.rawValue
    @Environment(\.runway) private var runway
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var fieldFocused: Bool
    @State private var showThread = false
    @State private var openThoughts: Set<UUID> = []

    private let contextCap = 4000

    private var pace: CapturePace { CapturePace(rawValue: paceRaw) ?? .standard }

    private var thinking: Bool { !forming.isEmpty }
    private var expanded: Bool { thinking || (showThread && !turns.isEmpty) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !expanded {
                Text(String(localized: "随时可以记下。"))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
            }

            VStack(alignment: .leading, spacing: 0) {
                if expanded {
                    expandedBody
                }
                composerBar
            }
            .background(runway.card, in: RoundedRectangle(cornerRadius: expanded ? Runway.cardRadius : 28, style: .continuous))
            .shadow(color: runway.liftShadow, radius: expanded ? Runway.shadowBlur : 10, y: expanded ? Runway.shadowY : 3)
            .animation(reduceMotion ? nil : Runway.softSpring, value: expanded)
        }
        .onAppear {
            if !turns.isEmpty { showThread = true }
            openThoughts = Set(forming.map(\.id))
        }
        .onChange(of: forming.map(\.id)) { _, ids in
            openThoughts.formUnion(ids)
            if !ids.isEmpty { showThread = true }
        }
    }

    private var expandedBody: some View {
        VStack(alignment: .leading, spacing: 14) {
            if showThread, !turns.isEmpty {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 16) {
                        ForEach(turns, id: \.id) { task in
                            turnBlock(task)
                        }
                    }
                    .padding(.top, 4)
                }
                .frame(maxHeight: 220)
            }

            if let live = forming.first {
                thoughtSpine(live)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 16)
        .padding(.bottom, 8)
        .transition(.asymmetric(
            insertion: .opacity.combined(with: .move(edge: .top)),
            removal: .opacity
        ))
    }

    private var composerBar: some View {
        VStack(alignment: .leading, spacing: expanded ? 10 : 0) {
            TextField(
                String(localized: "输入文字或粘贴链接……"),
                text: $draft,
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(.body)
            .lineLimit(expanded ? 2 ... 6 : 1 ... 2)
            .focused($fieldFocused)
            .onSubmit {
                if NSEvent.modifierFlags.contains(.command) {
                    submit()
                }
            }

            HStack(spacing: 10) {
                iconButton("bubble.left", active: showThread, label: String(localized: "对话")) {
                    withAnimation(reduceMotion ? nil : Runway.softSpring) {
                        showThread.toggle()
                    }
                }
                iconButton(
                    recorder.isRecording ? "stop.fill" : "mic",
                    active: recorder.isRecording,
                    label: recorder.isRecording ? String(localized: "停止录音") : String(localized: "语音")
                ) {
                    onVoice()
                }

                Spacer(minLength: 8)

                paceMenu
                contextMeter
                sendButton
            }
        }
        .padding(.horizontal, expanded ? 16 : 14)
        .padding(.vertical, expanded ? 12 : 10)
    }

    private var paceMenu: some View {
        Menu {
            ForEach(CapturePace.allCases) { item in
                Button(item.title) { paceRaw = item.rawValue }
            }
        } label: {
            HStack(spacing: 3) {
                Text(pace.title)
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        }
        .menuStyle(.borderlessButton)
        .help(String(localized: "整理节奏先记在本机，还不会改服务"))
    }

    private var contextMeter: some View {
        let used = draft.count
        let progress = min(CGFloat(used) / CGFloat(contextCap), 1)
        return HStack(spacing: 6) {
            Capsule()
                .fill(runway.field)
                .frame(width: 36, height: 4)
                .overlay(alignment: .leading) {
                    Capsule()
                        .fill(progress > 0.9 ? Color.orange : runway.agent)
                        .frame(width: max(4, 36 * progress), height: 4)
                }
            Text("\(used)")
                .font(.caption2.monospacedDigit())
                .foregroundStyle(progress > 0.9 ? Color.orange : Color.secondary)
        }
        .accessibilityLabel(String(localized: "上下文长度"))
        .accessibilityValue("\(used) / \(contextCap)")
    }

    private var sendButton: some View {
        let canSend = !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return Button {
            if canSend {
                submit()
            } else {
                onVoice()
            }
        } label: {
            Image(systemName: recorder.isRecording ? "stop.fill" : (canSend ? "arrow.up" : "waveform"))
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(runway.onAction)
                .frame(width: 32, height: 32)
                .background(
                    recorder.isRecording ? Color.orange : runway.action,
                    in: Circle()
                )
        }
        .buttonStyle(.plain)
        .keyboardShortcut(.return, modifiers: [.command])
        .help(canSend ? String(localized: "记住") : String(localized: "语音"))
        .accessibilityLabel(canSend ? String(localized: "记住") : String(localized: "语音"))
    }

    private func thoughtSpine(_ task: CaptureTask) -> some View {
        let steps = CaptureProgress.steps(for: task)
        let open = openThoughts.contains(task.id)
        return HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 0) {
                CoachMark(pose: pose, size: 32)
                if open {
                    Capsule()
                        .fill(runway.agent.opacity(0.35))
                        .frame(width: 2)
                        .frame(maxHeight: .infinity)
                        .padding(.top, 4)
                        .transition(.opacity.combined(with: .scale(scale: 0.2, anchor: .top)))
                }
            }
            .frame(width: 32)

            VStack(alignment: .leading, spacing: 8) {
                Button {
                    withAnimation(reduceMotion ? nil : Runway.softSpring) {
                        if open {
                            openThoughts.remove(task.id)
                        } else {
                            openThoughts.insert(task.id)
                        }
                    }
                } label: {
                    HStack(spacing: 6) {
                        Text(String(localized: "思考过程"))
                            .font(.caption.weight(.medium))
                            .foregroundStyle(runway.copy)
                        Text(task.userStatus)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Image(systemName: open ? "chevron.down" : "chevron.right")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.secondary)
                    }
                }
                .buttonStyle(.plain)

                if open {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                            IconLeadRow(iconWidth: 10, spacing: 8) {
                                Circle()
                                    .fill(index == steps.count - 1 ? runway.agent : Color.secondary.opacity(0.28))
                                    .frame(width: 6, height: 6)
                                    .padding(.top, 4)
                            } content: {
                                Text(step)
                                    .font(.caption)
                                    .foregroundStyle(index == steps.count - 1 ? runway.ink : runway.copy)
                            }
                        }
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

                if task.status == "needs_attention" {
                    Button(String(localized: "去处理"), action: onOpenInbox)
                        .buttonStyle(.plain)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(runway.action)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func turnBlock(_ task: CaptureTask) -> some View {
        let done = task.status == "completed"
        let firstItem = task.source?.knowledgeItems.first
        return VStack(alignment: .leading, spacing: 8) {
            Text(snippet(task))
                .font(.callout)
                .foregroundStyle(runway.ink)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)

            if done {
                Text(receiptLine(task))
                    .font(.callout)
                    .foregroundStyle(runway.copy)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 6) {
                    Spacer(minLength: 0)
                    if let firstItem {
                        Button(String(localized: "试一题")) {
                            onPreview(firstItem.id)
                        }
                        .buttonStyle(.plain)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(runway.ink)
                        Button(String(localized: "查看")) {
                            onOpenKnowledge(firstItem.id)
                        }
                        .buttonStyle(.plain)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func iconButton(_ system: String, active: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: system)
                .font(.body.weight(.medium))
                .foregroundStyle(active ? runway.ink : Color.secondary)
                .frame(width: 28, height: 28)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(label)
        .accessibilityLabel(label)
    }

    private func submit() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        withAnimation(reduceMotion ? nil : Runway.softSpring) {
            showThread = true
        }
        onSubmit()
        fieldFocused = true
    }

    private func snippet(_ task: CaptureTask) -> String {
        if let url = task.source?.url, !url.isEmpty { return url }
        let text = task.source?.rawText.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !text.isEmpty { return text }
        if task.source?.inputType == "voice" { return String(localized: "语音随记") }
        return task.userStatus
    }
}
