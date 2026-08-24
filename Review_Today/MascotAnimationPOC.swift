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

/// Disposable native prototype for validating generated raster mascot parts.
/// This does not own production review state or choose the final animation runtime.
struct MascotAnimationPOCView: View {
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.runway) private var runway

    @State private var state: MascotPOCState = .idle
    @State private var mouthLevel = 0.0
    @State private var headphonesVisible = false
    @State private var cardsVisible = true
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
            applyDefaults(for: newState)
        }
        .onChange(of: mouthLevel) { _, _ in pushState() }
        .onChange(of: headphonesVisible) { _, _ in pushState() }
        .onChange(of: cardsVisible) { _, _ in pushState() }
        .onChange(of: simulateReduceMotion) { _, _ in pushState() }
        .onChange(of: systemReduceMotion) { _, _ in pushState() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text(String(localized: "吉祥物动画 POC"))
                    .font(.title2.weight(.semibold))
                Text(String(localized: "开发验证"))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(red: 0.58, green: 0.25, blue: 0.16))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color(red: 0.96, green: 0.82, blue: 0.75), in: Capsule())
            }
            Text(String(localized: "分层位图由生成模型产出；SpriteKit 只驱动状态与轻微变形，不连接真实麦克风或 Agent。"))
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
                    Text(String(localized: "标准动态 · 可随时切换或打断"))
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

                        Slider(value: $mouthLevel, in: 0 ... 1) {
                            Text(String(localized: "模拟音量"))
                        } minimumValueLabel: {
                            Image(systemName: "speaker.wave.1")
                        } maximumValueLabel: {
                            Image(systemName: "speaker.wave.3")
                        }
                        .disabled(state != .speaking)
                        .accessibilityValue("\(Int(mouthLevel * 100))%")

                        RunwayPrimaryButton(
                            title: String(localized: "用户打断"),
                            enabled: state == .speaking,
                            action: interrupt
                        )
                        .keyboardShortcut(.escape, modifiers: [])
                    }
                }

                RunwayCard {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(String(localized: "配件与显示"))
                            .font(.headline)
                        Toggle(String(localized: "显示完整双耳耳机"), isOn: $headphonesVisible)
                        Toggle(String(localized: "显示复习卡"), isOn: $cardsVisible)
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
                        Text(String(localized: "模拟开关只用于快速比较；系统设置仍会自动生效。减少动态时停止持续悬浮和弹性伸展，但保留状态文字与配件变化。"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func applyDefaults(for newState: MascotPOCState) {
        switch newState {
        case .idle:
            mouthLevel = 0
            headphonesVisible = false
            cardsVisible = true
        case .listening:
            mouthLevel = 0
            headphonesVisible = true
            cardsVisible = false
        case .speaking:
            mouthLevel = 0.56
            headphonesVisible = true
            cardsVisible = false
        }
        pushState()
    }

    private func interrupt() {
        guard state == .speaking else { return }
        state = .listening
        mouthLevel = 0
        headphonesVisible = true
        cardsVisible = false
        pushState()
    }

    private func pushState() {
        scene.apply(
            state: state,
            mouthLevel: mouthLevel,
            headphonesVisible: headphonesVisible,
            cardsVisible: cardsVisible,
            reduceMotion: effectiveReduceMotion
        )
    }
}

private final class MascotSpriteScene: SKScene {
    private struct AtlasPart {
        var rect: CGRect

        var aspectRatio: CGFloat { rect.height / rect.width }
    }

    private struct Pose {
        var headY: CGFloat
        var headTilt: CGFloat
        var bodyScaleX: CGFloat
        var bodyScaleY: CGFloat
        var leftArmPosition: CGPoint
        var leftArmRotation: CGFloat
        var rightArmPosition: CGPoint
        var rightArmRotation: CGFloat

        static func value(for state: MascotPOCState, cardsVisible: Bool) -> Pose {
            if cardsVisible {
                return Pose(
                    headY: 62,
                    headTilt: -0.01,
                    bodyScaleX: 1,
                    bodyScaleY: 1,
                    leftArmPosition: CGPoint(x: -71, y: -58),
                    leftArmRotation: -0.08,
                    rightArmPosition: CGPoint(x: 72, y: -60),
                    rightArmRotation: 0.08
                )
            }

            switch state {
            case .idle:
                return Pose(
                    headY: 62,
                    headTilt: 0,
                    bodyScaleX: 1,
                    bodyScaleY: 1,
                    leftArmPosition: CGPoint(x: -78, y: -60),
                    leftArmRotation: -0.12,
                    rightArmPosition: CGPoint(x: 78, y: -60),
                    rightArmRotation: 0.12
                )
            case .listening:
                return Pose(
                    headY: 69,
                    headTilt: -0.045,
                    bodyScaleX: 0.985,
                    bodyScaleY: 1.018,
                    leftArmPosition: CGPoint(x: -88, y: -52),
                    leftArmRotation: -0.22,
                    rightArmPosition: CGPoint(x: 88, y: -54),
                    rightArmRotation: 0.22
                )
            case .speaking:
                return Pose(
                    headY: 67,
                    headTilt: 0.018,
                    bodyScaleX: 1.012,
                    bodyScaleY: 1.035,
                    leftArmPosition: CGPoint(x: -93, y: -48),
                    leftArmRotation: -0.31,
                    rightArmPosition: CGPoint(x: 93, y: -50),
                    rightArmRotation: 0.31
                )
            }
        }

        mutating func move(toward target: Pose, amount: CGFloat) {
            headY += (target.headY - headY) * amount
            headTilt += (target.headTilt - headTilt) * amount
            bodyScaleX += (target.bodyScaleX - bodyScaleX) * amount
            bodyScaleY += (target.bodyScaleY - bodyScaleY) * amount
            leftArmPosition.x += (target.leftArmPosition.x - leftArmPosition.x) * amount
            leftArmPosition.y += (target.leftArmPosition.y - leftArmPosition.y) * amount
            leftArmRotation += (target.leftArmRotation - leftArmRotation) * amount
            rightArmPosition.x += (target.rightArmPosition.x - rightArmPosition.x) * amount
            rightArmPosition.y += (target.rightArmPosition.y - rightArmPosition.y) * amount
            rightArmRotation += (target.rightArmRotation - rightArmRotation) * amount
        }
    }

    private static let atlasSide: CGFloat = 1254
    private static let headPart = AtlasPart(rect: CGRect(x: 38, y: 36, width: 326, height: 332))
    private static let bodyPart = AtlasPart(rect: CGRect(x: 404, y: 34, width: 273, height: 348))
    private static let leftArmPart = AtlasPart(rect: CGRect(x: 725, y: 98, width: 181, height: 242))
    private static let rightArmPart = AtlasPart(rect: CGRect(x: 969, y: 97, width: 184, height: 244))
    private static let eyesPart = AtlasPart(rect: CGRect(x: 88, y: 466, width: 188, height: 100))
    private static let blinkPart = AtlasPart(rect: CGRect(x: 353, y: 464, width: 229, height: 101))
    private static let bangsPart = AtlasPart(rect: CGRect(x: 653, y: 438, width: 254, height: 153))
    private static let ahogePart = AtlasPart(rect: CGRect(x: 1002, y: 427, width: 142, height: 164))
    private static let mouthClosedPart = AtlasPart(rect: CGRect(x: 95, y: 730, width: 162, height: 113))
    private static let mouthSmallPart = AtlasPart(rect: CGRect(x: 395, y: 727, width: 122, height: 116))
    private static let mouthMediumPart = AtlasPart(rect: CGRect(x: 691, y: 720, width: 145, height: 124))
    private static let mouthWidePart = AtlasPart(rect: CGRect(x: 995, y: 718, width: 151, height: 130))
    private static let headbandPart = AtlasPart(rect: CGRect(x: 22, y: 882, width: 402, height: 331))
    private static let leftEarcupPart = AtlasPart(rect: CGRect(x: 468, y: 941, width: 151, height: 231))
    private static let rightEarcupPart = AtlasPart(rect: CGRect(x: 653, y: 941, width: 155, height: 231))
    private static let cardsPart = AtlasPart(rect: CGRect(x: 838, y: 905, width: 402, height: 316))

    private let frameNode = SKNode()
    private let characterNode = SKNode()
    private let headAnchor = SKNode()
    private let bodyNode: SKSpriteNode
    private let leftArmNode: SKSpriteNode
    private let rightArmNode: SKSpriteNode
    private let headNode: SKSpriteNode
    private let eyesNode: SKSpriteNode
    private let bangsNode: SKSpriteNode
    private let ahogeNode: SKSpriteNode
    private let mouthNode: SKSpriteNode
    private let headbandNode: SKSpriteNode
    private let leftEarcupNode: SKSpriteNode
    private let rightEarcupNode: SKSpriteNode
    private let cardsNode: SKSpriteNode

    private let openEyesTexture: SKTexture
    private let blinkEyesTexture: SKTexture
    private let mouthTextures: [SKTexture]
    private let mouthParts: [AtlasPart]

    private var state: MascotPOCState = .idle
    private var targetPose = Pose.value(for: .idle, cardsVisible: true)
    private var currentPose = Pose.value(for: .idle, cardsVisible: true)
    private var targetMouthLevel: CGFloat = 0
    private var displayedMouthLevel: CGFloat = 0
    private var targetHeadphonesAlpha: CGFloat = 0
    private var displayedHeadphonesAlpha: CGFloat = 0
    private var targetCardsAlpha: CGFloat = 1
    private var displayedCardsAlpha: CGFloat = 1
    private var reduceMotion = false
    private var lastUpdateTime: TimeInterval?

    override init(size: CGSize) {
        let atlas = SKTexture(imageNamed: "MascotRigParts")
        atlas.filteringMode = .linear

        func texture(for part: AtlasPart) -> SKTexture {
            let rect = part.rect
            let normalized = CGRect(
                x: rect.minX / Self.atlasSide,
                y: 1 - rect.maxY / Self.atlasSide,
                width: rect.width / Self.atlasSide,
                height: rect.height / Self.atlasSide
            )
            let result = SKTexture(rect: normalized, in: atlas)
            result.filteringMode = .linear
            return result
        }

        func node(for part: AtlasPart, width: CGFloat) -> SKSpriteNode {
            let result = SKSpriteNode(texture: texture(for: part))
            result.size = CGSize(width: width, height: width * part.aspectRatio)
            return result
        }

        bodyNode = node(for: Self.bodyPart, width: 164)
        leftArmNode = node(for: Self.leftArmPart, width: 80)
        rightArmNode = node(for: Self.rightArmPart, width: 80)
        headNode = node(for: Self.headPart, width: 268)
        eyesNode = node(for: Self.eyesPart, width: 106)
        bangsNode = node(for: Self.bangsPart, width: 138)
        ahogeNode = node(for: Self.ahogePart, width: 55)
        mouthNode = node(for: Self.mouthClosedPart, width: 58)
        headbandNode = node(for: Self.headbandPart, width: 305)
        leftEarcupNode = node(for: Self.leftEarcupPart, width: 61)
        rightEarcupNode = node(for: Self.rightEarcupPart, width: 61)
        cardsNode = node(for: Self.cardsPart, width: 210)

        openEyesTexture = texture(for: Self.eyesPart)
        blinkEyesTexture = texture(for: Self.blinkPart)
        mouthParts = [Self.mouthClosedPart, Self.mouthSmallPart, Self.mouthMediumPart, Self.mouthWidePart]
        mouthTextures = mouthParts.map(texture(for:))

        super.init(size: size)
        scaleMode = .resizeFill
        backgroundColor = .clear
        anchorPoint = .zero
        setupNodes()
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

    func apply(
        state: MascotPOCState,
        mouthLevel: Double,
        headphonesVisible: Bool,
        cardsVisible: Bool,
        reduceMotion: Bool
    ) {
        self.state = state
        self.reduceMotion = reduceMotion
        targetMouthLevel = state == .speaking ? CGFloat(mouthLevel) : 0
        targetHeadphonesAlpha = headphonesVisible ? 1 : 0
        targetCardsAlpha = cardsVisible ? 1 : 0
        targetPose = Pose.value(for: state, cardsVisible: cardsVisible)

        if reduceMotion {
            currentPose = targetPose
            displayedMouthLevel = targetMouthLevel
            displayedHeadphonesAlpha = targetHeadphonesAlpha
            displayedCardsAlpha = targetCardsAlpha
            render(time: 0)
        }
    }

    override func update(_ currentTime: TimeInterval) {
        let delta = min(max(currentTime - (lastUpdateTime ?? currentTime - 1 / 60), 1 / 240), 1 / 12)
        lastUpdateTime = currentTime
        let response = reduceMotion ? CGFloat(1) : CGFloat(1 - Foundation.exp(-22 * delta))

        currentPose.move(toward: targetPose, amount: response)
        displayedMouthLevel += (targetMouthLevel - displayedMouthLevel) * response
        displayedHeadphonesAlpha += (targetHeadphonesAlpha - displayedHeadphonesAlpha) * response
        displayedCardsAlpha += (targetCardsAlpha - displayedCardsAlpha) * response
        render(time: currentTime)
    }

    private func setupNodes() {
        addChild(frameNode)
        frameNode.addChild(characterNode)

        bodyNode.position = CGPoint(x: 0, y: -86)
        bodyNode.zPosition = 0
        characterNode.addChild(bodyNode)

        leftArmNode.zPosition = 3
        rightArmNode.zPosition = 3
        characterNode.addChild(leftArmNode)
        characterNode.addChild(rightArmNode)

        cardsNode.position = CGPoint(x: 20, y: -74)
        cardsNode.zPosition = 5
        characterNode.addChild(cardsNode)

        headAnchor.zPosition = 2
        characterNode.addChild(headAnchor)

        headbandNode.position = CGPoint(x: 0, y: 16)
        headbandNode.zPosition = -2
        headAnchor.addChild(headbandNode)

        headNode.zPosition = 0
        headAnchor.addChild(headNode)

        eyesNode.position = CGPoint(x: 7, y: 6)
        eyesNode.zPosition = 3
        headAnchor.addChild(eyesNode)

        bangsNode.position = CGPoint(x: -34, y: 71)
        bangsNode.zPosition = 4
        headAnchor.addChild(bangsNode)

        ahogeNode.position = CGPoint(x: 43, y: 132)
        ahogeNode.zPosition = 4
        headAnchor.addChild(ahogeNode)

        mouthNode.position = CGPoint(x: 12, y: -43)
        mouthNode.zPosition = 4
        headAnchor.addChild(mouthNode)

        leftEarcupNode.position = CGPoint(x: -136, y: 15)
        leftEarcupNode.zPosition = 5
        headAnchor.addChild(leftEarcupNode)

        rightEarcupNode.position = CGPoint(x: 136, y: 15)
        rightEarcupNode.zPosition = 5
        headAnchor.addChild(rightEarcupNode)
    }

    private func layoutCharacter() {
        frameNode.position = CGPoint(x: size.width / 2, y: size.height / 2 - 4)
        let fit = min(size.width / 500, size.height / 500)
        frameNode.setScale(fit)
    }

    private func render(time: TimeInterval) {
        let phase = CGFloat(time)
        let speakingEnergy = state == .speaking ? displayedMouthLevel : 0
        let bobAmplitude: CGFloat
        let frequency: CGFloat
        switch state {
        case .idle:
            bobAmplitude = 2.4
            frequency = 1.45
        case .listening:
            bobAmplitude = 1.2
            frequency = 1.8
        case .speaking:
            bobAmplitude = 1.2 + speakingEnergy * 1.7
            frequency = 3.0 + speakingEnergy * 1.8
        }

        let wave = reduceMotion ? CGFloat(0) : sin(phase * frequency)
        characterNode.position.y = wave * bobAmplitude
        characterNode.zRotation = reduceMotion ? 0 : wave * (state == .listening ? 0.004 : 0.007)

        headAnchor.position = CGPoint(x: state == .listening ? -3 : 0, y: currentPose.headY + wave * 0.7)
        headAnchor.zRotation = currentPose.headTilt + (reduceMotion ? 0 : wave * 0.008)

        let breathe = reduceMotion ? CGFloat(0) : wave * (state == .speaking ? 0.014 + speakingEnergy * 0.02 : 0.009)
        bodyNode.xScale = currentPose.bodyScaleX - breathe * 0.4
        bodyNode.yScale = currentPose.bodyScaleY + breathe

        leftArmNode.position = CGPoint(
            x: currentPose.leftArmPosition.x,
            y: currentPose.leftArmPosition.y + wave * 0.6
        )
        leftArmNode.zRotation = currentPose.leftArmRotation - wave * 0.01
        rightArmNode.position = CGPoint(
            x: currentPose.rightArmPosition.x,
            y: currentPose.rightArmPosition.y + wave * 0.55
        )
        rightArmNode.zRotation = currentPose.rightArmRotation + wave * 0.01

        ahogeNode.zRotation = reduceMotion ? 0 : wave * (state == .speaking ? 0.055 : 0.025)
        cardsNode.alpha = displayedCardsAlpha
        cardsNode.yScale = 1 - (reduceMotion ? 0 : wave * 0.004)
        cardsNode.xScale = 1 + (reduceMotion ? 0 : wave * 0.004)

        headbandNode.alpha = displayedHeadphonesAlpha
        leftEarcupNode.alpha = displayedHeadphonesAlpha
        rightEarcupNode.alpha = displayedHeadphonesAlpha

        updateEyes(time: time)
        updateMouth()
    }

    private func updateEyes(time: TimeInterval) {
        let blinking = !reduceMotion && time.truncatingRemainder(dividingBy: 4.4) < 0.12
        eyesNode.texture = blinking ? blinkEyesTexture : openEyesTexture
        let part = blinking ? Self.blinkPart : Self.eyesPart
        let width: CGFloat = blinking ? 118 : 106
        eyesNode.size = CGSize(width: width, height: width * part.aspectRatio)
    }

    private func updateMouth() {
        let index: Int
        if state != .speaking || displayedMouthLevel < 0.14 {
            index = 0
        } else if displayedMouthLevel < 0.4 {
            index = 1
        } else if displayedMouthLevel < 0.72 {
            index = 2
        } else {
            index = 3
        }
        mouthNode.texture = mouthTextures[index]
        let baseWidths: [CGFloat] = [58, 48, 56, 62]
        let width = baseWidths[index]
        mouthNode.size = CGSize(width: width, height: width * mouthParts[index].aspectRatio)
        let energy = state == .speaking ? displayedMouthLevel : 0
        mouthNode.xScale = 1 + energy * 0.04
        mouthNode.yScale = 1 + energy * 0.08
    }
}
