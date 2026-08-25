import AppKit
import SpriteKit
import SwiftUI

enum MascotPOCState: String, CaseIterable, Identifiable {
    case idle
    case listening
    case speaking

    var id: String { rawValue }

    var title: String {
        switch self {
        case .idle: String(localized: "待机")
        case .listening: String(localized: "聆听")
        case .speaking: String(localized: "说话")
        }
    }

    var status: String {
        switch self {
        case .idle: String(localized: "安静待机 · 未在聆听")
        case .listening: String(localized: "正在聆听 · 等你说完")
        case .speaking: String(localized: "正在回应 · 可以随时打断")
        }
    }

    var assetSummary: String {
        switch self {
        case .idle:
            String(localized: "完整 V8 抱卡角色 · 无耳机")
        case .listening:
            String(localized: "完整连体角色 · 双耳耳机 · 闭口倾听")
        case .speaking:
            String(localized: "完整连体角色 · 双耳耳机 · 小幅开口")
        }
    }
}

private enum MascotPOCBackdrop: String, CaseIterable, Identifiable {
    case warm
    case terracotta
    case graphite

    var id: String { rawValue }

    var title: String {
        switch self {
        case .warm: String(localized: "暖白")
        case .terracotta: String(localized: "陶土")
        case .graphite: String(localized: "深色")
        }
    }

    var color: Color {
        switch self {
        case .warm: Color(red: 0.996, green: 0.976, blue: 0.949)
        case .terracotta: Color(red: 0.898, green: 0.557, blue: 0.427)
        case .graphite: Color(red: 0.105, green: 0.102, blue: 0.098)
        }
    }
}

/// Disposable native prototype for validating complete generated mascot states.
/// This does not own production review state or choose the final animation runtime.
struct MascotAnimationPOCView: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.runway) private var runway

    @State private var state: MascotPOCState = .idle
    @State private var voiceIntensity = 0.0
    @State private var simulateReduceMotion = false
    @State private var backdrop: MascotPOCBackdrop = .warm
    @State private var scene = MascotSpriteScene(size: CGSize(width: 520, height: 520))

    private var effectiveReduceMotion: Bool {
        systemReduceMotion || simulateReduceMotion
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Runway.gap) {
            header
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: Runway.section) {
                    preview
                    controls
                        .frame(width: 320)
                }
                VStack(spacing: Runway.gap) {
                    preview
                    controls
                }
            }
        }
        .padding(Runway.section)
        .background(PaperSurface())
        .frame(minWidth: 760, minHeight: 600)
        .onAppear { pushState() }
        .onChange(of: state) { _, newState in
            voiceIntensity = newState == .speaking ? 0.56 : 0
            pushState()
        }
        .onChange(of: voiceIntensity) { _, _ in pushState() }
        .onChange(of: simulateReduceMotion) { _, _ in pushState() }
        .onChange(of: systemReduceMotion) { _, _ in pushState() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text(String(localized: "吉祥物动画 POC"))
                    .font(.title2.weight(.semibold))
                Text(String(localized: "完整状态图"))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(red: 0.58, green: 0.25, blue: 0.16))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color(red: 0.96, green: 0.82, blue: 0.75), in: Capsule())
            }
            Text(String(localized: "每个状态使用完整连体位图；SpriteKit 只驱动切换与整体轻动效，不再拼装头、身体和手臂。"))
                .foregroundStyle(.secondary)
        }
    }

    private var preview: some View {
        ZStack(alignment: .bottomLeading) {
            backdrop.color
            SpriteView(scene: scene, options: [.allowsTransparency, .ignoresSiblingOrder])
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(state.status)
                    .font(.headline)
                if effectiveReduceMotion {
                    Text(systemReduceMotion
                         ? String(localized: "系统“减少动态效果”已启用")
                         : String(localized: "正在模拟“减少动态效果”"))
                        .font(.caption)
                } else {
                    Text(String(localized: "完整角色轻动效 · 可随时切换或打断"))
                        .font(.caption)
                }
            }
            .foregroundStyle(backdrop == .graphite ? Color.white : runway.ink)
            .padding(16)
        }
        .frame(minWidth: 390, idealWidth: 520, maxWidth: .infinity, minHeight: 430, idealHeight: 520)
        .clipShape(RoundedRectangle(cornerRadius: Runway.cardRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: Runway.cardRadius, style: .continuous)
                .strokeBorder(backdrop == .graphite ? Color.white.opacity(0.16) : runway.hairline)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(String(localized: "吉祥物状态预览"))
        .accessibilityValue(state.status)
    }

    private var controls: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Runway.gap) {
                RunwayCard {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(String(localized: "状态"))
                            .font(.headline)
                        Picker(String(localized: "角色状态"), selection: $state) {
                            ForEach(MascotPOCState.allCases) { value in
                                Text(value.title).tag(value)
                            }
                        }
                        .pickerStyle(.segmented)

                        Slider(value: $voiceIntensity, in: 0 ... 1) {
                            Text(String(localized: "模拟语音强度"))
                        } minimumValueLabel: {
                            Image(systemName: "speaker.wave.1")
                        } maximumValueLabel: {
                            Image(systemName: "speaker.wave.3")
                        }
                        .disabled(state != .speaking)
                        .accessibilityValue("\(Int(voiceIntensity * 100))%")

                        RunwayPrimaryButton(
                            title: String(localized: "用户打断"),
                            enabled: state == .speaking,
                            action: interrupt
                        )
                        .keyboardShortcut(.escape, modifiers: [])
                    }
                }

                RunwayCard {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(String(localized: "当前完整状态图"))
                            .font(.headline)
                        Text(state.assetSummary)
                            .foregroundStyle(.secondary)
                        Divider()
                        Picker(String(localized: "预览背景"), selection: $backdrop) {
                            ForEach(MascotPOCBackdrop.allCases) { value in
                                Text(value.title).tag(value)
                            }
                        }
                        .pickerStyle(.segmented)
                    }
                }

                RunwayCard {
                    VStack(alignment: .leading, spacing: 8) {
                        Toggle(String(localized: "模拟减少动态效果"), isOn: $simulateReduceMotion)
                        Text(String(localized: "减少动态时直接切换完整状态图，并停止持续悬浮、倾斜和语音强度形变；状态文字仍保留。"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func interrupt() {
        guard state == .speaking else { return }
        state = .listening
        voiceIntensity = 0
        pushState()
    }

    private func pushState() {
        scene.apply(
            state: state,
            voiceIntensity: voiceIntensity,
            reduceMotion: effectiveReduceMotion
        )
    }
}

private final class MascotSpriteScene: SKScene {
    private let characterNode = SKNode()
    private let idleNode: SKSpriteNode
    private let listeningNode: SKSpriteNode
    private let speakingNode: SKSpriteNode

    private var state: MascotPOCState = .idle
    private var reduceMotion = false
    private var targetVoiceIntensity: CGFloat = 0
    private var displayedVoiceIntensity: CGFloat = 0
    private var targetAlphas = SIMD3<Double>(1, 0, 0)
    private var displayedAlphas = SIMD3<Double>(1, 0, 0)
    private var lastUpdateTime: TimeInterval?

    override init(size: CGSize) {
        func completeSprite(named name: String, height: CGFloat) -> SKSpriteNode {
            let texture = SKTexture(imageNamed: name)
            texture.filteringMode = .linear
            let textureSize = texture.size()
            let node = SKSpriteNode(texture: texture)
            node.size = CGSize(width: height * textureSize.width / textureSize.height, height: height)
            return node
        }

        idleNode = completeSprite(named: "MascotIdleFull", height: 420)
        listeningNode = completeSprite(named: "MascotVoiceListeningFull", height: 340)
        speakingNode = completeSprite(named: "MascotVoiceSpeakingFull", height: 340)

        super.init(size: size)
        scaleMode = .resizeFill
        backgroundColor = .clear
        anchorPoint = .zero

        addChild(characterNode)
        characterNode.addChild(idleNode)
        characterNode.addChild(listeningNode)
        characterNode.addChild(speakingNode)

        idleNode.alpha = 1
        listeningNode.alpha = 0
        speakingNode.alpha = 0
        layoutCharacter()
    }

    @available(*, unavailable)
    required init?(coder aDecoder: NSCoder) {
        fatalError("MascotSpriteScene does not support NSCoding")
    }

    override func didMove(to view: SKView) {
        view.allowsTransparency = true
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.clear.cgColor
    }

    override func didChangeSize(_ oldSize: CGSize) {
        layoutCharacter()
    }

    func apply(state: MascotPOCState, voiceIntensity: Double, reduceMotion: Bool) {
        self.state = state
        self.reduceMotion = reduceMotion
        targetVoiceIntensity = state == .speaking ? CGFloat(voiceIntensity) : 0
        switch state {
        case .idle:
            targetAlphas = SIMD3(1, 0, 0)
        case .listening:
            targetAlphas = SIMD3(0, 1, 0)
        case .speaking:
            targetAlphas = SIMD3(0, 0, 1)
        }

        if reduceMotion {
            displayedVoiceIntensity = targetVoiceIntensity
            displayedAlphas = targetAlphas
            render(time: 0)
        }
    }

    override func update(_ currentTime: TimeInterval) {
        let delta = min(max(currentTime - (lastUpdateTime ?? currentTime - 1 / 60), 1 / 240), 1 / 12)
        lastUpdateTime = currentTime
        let response = reduceMotion ? CGFloat(1) : CGFloat(1 - Foundation.exp(-24 * delta))

        displayedVoiceIntensity += (targetVoiceIntensity - displayedVoiceIntensity) * response
        displayedAlphas += (targetAlphas - displayedAlphas) * Double(response)
        render(time: currentTime)
    }

    private func layoutCharacter() {
        characterNode.position = CGPoint(x: size.width / 2, y: size.height / 2 + 18)
        let fit = min(size.width / 520, size.height / 520)
        characterNode.setScale(fit)
    }

    private func render(time: TimeInterval) {
        idleNode.alpha = CGFloat(displayedAlphas.x)
        listeningNode.alpha = CGFloat(displayedAlphas.y)
        speakingNode.alpha = CGFloat(displayedAlphas.z)

        guard !reduceMotion else {
            characterNode.position = CGPoint(x: size.width / 2, y: size.height / 2 + 18)
            characterNode.zRotation = 0
            characterNode.xScale = min(size.width / 520, size.height / 520)
            characterNode.yScale = characterNode.xScale
            return
        }

        let phase = CGFloat(time)
        let energy = state == .speaking ? displayedVoiceIntensity : 0
        let frequency: CGFloat = state == .speaking ? 2.8 + energy * 1.6 : 1.45
        let wave = sin(phase * frequency)
        let baseScale = min(size.width / 520, size.height / 520)
        let bob: CGFloat = state == .listening ? 1.3 : 2.2 + energy * 1.1
        let lean: CGFloat = state == .listening ? -0.012 : 0
        let speakingStretch = energy * 0.012 * wave

        characterNode.position = CGPoint(
            x: size.width / 2,
            y: size.height / 2 + 18 + wave * bob
        )
        characterNode.zRotation = lean + wave * (state == .speaking ? 0.005 : 0.003)
        characterNode.xScale = baseScale * (1 - speakingStretch * 0.35)
        characterNode.yScale = baseScale * (1 + speakingStretch)
    }
}
