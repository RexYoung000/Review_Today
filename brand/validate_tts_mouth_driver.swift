#!/usr/bin/env swift

import AVFoundation
import Foundation

let text = "我们先来重温今天的第一个知识点。你可以慢慢想，不需要急着回答。即使答错也没关系，我会温柔地提醒你，再陪你把它想清楚。准备好了吗？"
let synthesizer = AVSpeechSynthesizer()
let utterance = AVSpeechUtterance(string: text)
utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
utterance.rate = 0.47
utterance.pitchMultiplier = 1.04
utterance.volume = 0.92

var totalFrames: AVAudioFramePosition = 0
var sampleRate = 0.0
var bands = [Int](repeating: 0, count: 4)
var finished = false

synthesizer.write(utterance) { buffer in
    guard let pcm = buffer as? AVAudioPCMBuffer else { return }
    guard pcm.frameLength > 0 else {
        finished = true
        let duration = sampleRate > 0 ? Double(totalFrames) / sampleRate : 0
        print(String(format: "duration=%.2fs closed=%d small=%d medium=%d wide=%d", duration, bands[0], bands[1], bands[2], bands[3]))
        let passed = (8 ... 16).contains(duration) && bands.allSatisfy { $0 > 0 }
        exit(passed ? 0 : 1)
    }

    totalFrames += AVAudioFramePosition(pcm.frameLength)
    sampleRate = pcm.format.sampleRate
    guard let samples = pcm.floatChannelData?[0] else { return }
    var sum = 0.0
    for index in 0 ..< Int(pcm.frameLength) {
        let value = Double(samples[index])
        sum += value * value
    }
    let rms = sqrt(sum / Double(pcm.frameLength))
    let decibels = 20 * log10(max(rms, 0.000_000_1))
    let level = decibels < -43 ? 0 : min(1, max(0, (decibels + 43) / 34))
    switch level {
    case ..<0.10: bands[0] += 1
    case ..<0.42: bands[1] += 1
    case ..<0.78: bands[2] += 1
    default: bands[3] += 1
    }
}

RunLoop.main.run(until: Date().addingTimeInterval(24))
if !finished {
    fputs("TTS synthesis timed out\n", stderr)
    exit(2)
}
