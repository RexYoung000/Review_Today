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

/// Disposable native prototype for validating complete generated mascot states
/// plus local raster expression overlays driven by real TTS playback levels.
/// This does not own production review state or choose the final animation runtime.
struct MascotAnimationPOCView: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.runway) private var runway

    @State private var state: MascotPOCState = .idle
    @State private var manualVoiceIntensity = 0.0
    @State private var simulateReduceMotion = false
    @State private var backdrop: MascotPOCBackdrop = .warm
    @State private var scene = MascotSpriteScene(size: CGSize(width: 520, height: 520))
    @StateObject private var speech = MascotSpeechDemoController()

    private let speechDemoText = String(localized: "我们先来重温今天的第一个知识点。你可以慢慢想，不需要急着回答。即使答错也没关系，我会温柔地提醒你，再陪你把它想清楚。准备好了吗？")

    private var effectiveReduceMotion: Bool {
        systemReduceMotion || simulateReduceMotion
    }

    private var effectiveVoiceIntensity: Double {
        speech.isAudioDrivingMouth ? speech.level : manualVoiceIntensity
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
        .onDisappear { speech.stop() }
        .onChange(of: state) { _, newState in
            if newState != .speaking {
                speech.stop()
            }
            manualVoiceIntensity = 0
            pushState()
        }
        .onChange(of: manualVoiceIntensity) { _, _ in pushState() }
        .onChange(of: speech.level) { _, _ in pushState() }
        .onChange(of: speech.phase) { _, _ in pushState() }
        .onChange(of: simulateReduceMotion) { _, _ in pushState() }
        .onChange(of: systemReduceMotion) { _, _ in pushState() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text(String(localized: "吉祥物动画 POC"))
                    .font(.title2.weight(.semibold))
                Text(String(localized: "V12 · 真实 TTS 嘴型"))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(red: 0.58, green: 0.25, blue: 0.16))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color(red: 0.96, green: 0.82, blue: 0.75), in: Capsule())
            }
            Text(String(localized: "身体保持完整连体；真实 TTS 播放音量驱动五个 GPT Image 局部嘴型，并加入独立眨眼与克制次级动作。"))
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
                    Text(state == .speaking
                         ? speech.statusText
                         : String(localized: "完整角色轻动效 · 可随时切换或打断"))
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

                        RunwayPrimaryButton(
                            title: speech.isActive
                                ? String(localized: "正在播放测试语音…")
                                : String(localized: "播放真实 TTS"),
                            enabled: !speech.isActive,
                            action: playSpeechDemo
                        )

                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text(speech.statusText)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text("\(Int(speech.level * 100))%")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                            ProgressView(value: speech.isAudioDrivingMouth ? speech.level : manualVoiceIntensity)
                        }

                        Slider(value: $manualVoiceIntensity, in: 0 ... 1) {
                            Text(String(localized: "手动调试嘴型"))
                        } minimumValueLabel: {
                            Image(systemName: "speaker.wave.1")
                        } maximumValueLabel: {
                            Image(systemName: "speaker.wave.3")
                        }
                        .disabled(state != .speaking || speech.isActive)
                        .accessibilityValue("\(Int(manualVoiceIntensity * 100))%")

                        Text(String(localized: "滑杆只用于无音频调试；正式验收以真实 TTS 播放为准。"))
                            .font(.caption)
                            .foregroundStyle(.secondary)

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
                        Text(String(localized: "当前动画资产"))
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
                        Text(String(localized: "减少动态时保留真实语音嘴型和状态文字，但停止持续悬浮、眨眼、倾斜和次级形变。"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func interrupt() {
        guard state == .speaking else { return }
        speech.stop()
        state = .listening
        manualVoiceIntensity = 0
        pushState()
    }

    private func playSpeechDemo() {
        state = .speaking
        manualVoiceIntensity = 0
        speech.play(text: speechDemoText) {
            guard state == .speaking else { return }
            state = .listening
        }
        pushState()
    }

    private func pushState() {
        scene.apply(
            state: state,
            voiceIntensity: effectiveVoiceIntensity,
            reduceMotion: effectiveReduceMotion,
            showToothSmile: speech.isShowingToothSmile
        )
    }
}

private final class MascotSpriteScene: SKScene {
    private let characterNode = SKNode()
    private let idleNode: SKSpriteNode
    private let listeningNode: SKSpriteNode
    private let speakingNode = SKNode()
    private let speakingBaseNode: SKSpriteNode
    private let speakingBlinkNode: SKSpriteNode
    private let mouthNodes: [SKSpriteNode]

    private var state: MascotPOCState = .idle
    private var reduceMotion = false
    private var targetVoiceIntensity: CGFloat = 0
    private var displayedVoiceIntensity: CGFloat = 0
    private var targetAlphas = SIMD3<Double>(1, 0, 0)
    private var displayedAlphas = SIMD3<Double>(1, 0, 0)
    private var targetMouthIndex = 0
    private var displayedMouthAlphas = [CGFloat](repeating: 0, count: 5)
    private var nextBlinkTime: TimeInterval = 2.6
    private var blinkEndTime: TimeInterval = 0
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
        speakingBaseNode = completeSprite(named: "MascotVoiceMouthlessFull", height: 340)
        speakingBlinkNode = completeSprite(named: "MascotVoiceBlinkFull", height: 334.4)
        speakingBlinkNode.position = CGPoint(x: -0.5, y: -1.3)
        mouthNodes = [
            "MascotMouthClosed",
            "MascotMouthSmall",
            "MascotMouthMedium",
            "MascotMouthWide",
            "MascotMouthTooth",
        ].map { name in
            let texture = SKTexture(imageNamed: name)
            texture.filteringMode = .linear
            let node = SKSpriteNode(texture: texture)
            node.size = CGSize(width: 47, height: 28)
            node.position = CGPoint(x: 15, y: -3)
            node.alpha = 0
            return node
        }

        super.init(size: size)
        scaleMode = .resizeFill
        backgroundColor = .clear
        anchorPoint = .zero

        addChild(characterNode)
        characterNode.addChild(idleNode)
        characterNode.addChild(listeningNode)
        characterNode.addChild(speakingNode)
        speakingNode.addChild(speakingBaseNode)
        speakingNode.addChild(speakingBlinkNode)
        mouthNodes.forEach(speakingNode.addChild)

        idleNode.alpha = 1
        listeningNode.alpha = 0
        speakingNode.alpha = 0
        speakingBlinkNode.alpha = 0
        displayedMouthAlphas[0] = 1
        mouthNodes[0].alpha = 1
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

    func apply(state: MascotPOCState, voiceIntensity: Double, reduceMotion: Bool, showToothSmile: Bool) {
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
        targetMouthIndex = showToothSmile ? 4 : mouthIndex(for: targetVoiceIntensity)

        if reduceMotion {
            displayedVoiceIntensity = targetVoiceIntensity
            displayedAlphas = targetAlphas
            displayedMouthAlphas = [CGFloat](repeating: 0, count: 5)
            displayedMouthAlphas[targetMouthIndex] = 1
            render(time: 0)
        }
    }

    override func update(_ currentTime: TimeInterval) {
        let delta = min(max(currentTime - (lastUpdateTime ?? currentTime - 1 / 60), 1 / 240), 1 / 12)
        lastUpdateTime = currentTime
        let response = reduceMotion ? CGFloat(1) : CGFloat(1 - Foundation.exp(-24 * delta))

        displayedVoiceIntensity += (targetVoiceIntensity - displayedVoiceIntensity) * response
        displayedAlphas += (targetAlphas - displayedAlphas) * Double(response)
        let mouthResponse = CGFloat(1 - Foundation.exp(-34 * delta))
        for index in displayedMouthAlphas.indices {
            let target: CGFloat = index == targetMouthIndex ? 1 : 0
            displayedMouthAlphas[index] += (target - displayedMouthAlphas[index]) * mouthResponse
        }
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
        for index in mouthNodes.indices {
            mouthNodes[index].alpha = displayedMouthAlphas[index]
        }

        guard !reduceMotion else {
            speakingBlinkNode.alpha = 0
            characterNode.position = CGPoint(x: size.width / 2, y: size.height / 2 + 18)
            characterNode.zRotation = 0
            characterNode.xScale = min(size.width / 520, size.height / 520)
            characterNode.yScale = characterNode.xScale
            return
        }

        let phase = CGFloat(time)
        let energy = state == .speaking ? displayedVoiceIntensity : 0
        let slowWave = sin(phase * (state == .speaking ? 1.7 : 1.45))
        let voiceBeat = sin(phase * 5.2) * energy
        let baseScale = min(size.width / 520, size.height / 520)
        let bob: CGFloat = state == .listening ? 1.3 : 1.7
        let lean: CGFloat = state == .listening ? -0.012 : 0
        let speakingStretch = energy * 0.004 * voiceBeat

        if state == .speaking {
            if time >= nextBlinkTime {
                blinkEndTime = time + 0.13
                nextBlinkTime = time + 2.8 + Double.random(in: 0 ... 2.2)
            }
            speakingBlinkNode.alpha = time < blinkEndTime ? 1 : 0
        } else {
            speakingBlinkNode.alpha = 0
            nextBlinkTime = time + 2.2
        }

        characterNode.position = CGPoint(
            x: size.width / 2,
            y: size.height / 2 + 18 + slowWave * bob + voiceBeat * 0.45
        )
        characterNode.zRotation = lean + slowWave * (state == .speaking ? 0.004 : 0.003) + voiceBeat * 0.002
        characterNode.xScale = baseScale * (1 - speakingStretch * 0.35)
        characterNode.yScale = baseScale * (1 + speakingStretch)
    }

    private func mouthIndex(for intensity: CGFloat) -> Int {
        switch intensity {
        case ..<0.10: 0
        case ..<0.42: 1
        case ..<0.78: 2
        default: 3
        }
    }
}
