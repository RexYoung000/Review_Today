import Foundation
import SwiftData

@main struct AgentVoiceStoreTests {
    enum Disk: Error { case full }
    @MainActor static func main() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("agent-voice-store-\(UUID())")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let url = folder.appendingPathComponent("test.store")
        let runtime = AppRuntime(mode: .normal)
        var owner = UUID(), messageID = UUID()
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let context = container.mainContext; context.autosaveEnabled = false
            let draft = try AgentComposerStore.prepare(context)
            owner = draft.agentDraftID!
            draft.agentDraftText = "这份原稿要继续修改"
            draft.agentDraftImage = Data([1, 2, 3])
            draft.agentDraftThinking = "deep"
            try context.save()
            let count = try context.fetchCount(FetchDescriptor<AgentSession>())
            precondition(count == 0, "preparing a voice owner must not create an empty chat")
            do {
                _ = try AgentComposerStore.sendFirst("第一句语音", context: context, consumesDraft: false,
                    inputChannel: "voice", runtime: runtime, save: { throw Disk.full })
                preconditionFailure("failed save must throw")
            } catch Disk.full {}
            precondition(draft.agentDraftID == owner && draft.agentDraftText == "这份原稿要继续修改")
            let afterFailure = try context.fetchCount(FetchDescriptor<AgentMessage>())
            precondition(afterFailure == 0)
            let (session, message) = try AgentComposerStore.sendFirst("第一句语音", context: context,
                consumesDraft: false, inputChannel: "voice", runtime: runtime)
            messageID = message.id
            precondition(session.id == owner && message.sessionID == owner)
            precondition(message.inputChannel == "voice" && message.imageAttachment == nil)
            precondition(session.composerDraft == "这份原稿要继续修改" && session.composerImage == Data([1, 2, 3]))
            precondition(session.thinkingStrength == "deep")
            precondition(draft.agentDraftID == nil && draft.agentDraftText.isEmpty && draft.agentDraftImage == nil)
            message.voicePlaybackJSON = AgentVoicePlayback(played: ["第一段。"], interrupted: "第二段。", state: "interrupted").json
            try context.save()
        }
        do {
            let container = try ModelContainer(for: M1DebugFixture.schema, configurations: ModelConfiguration(url: url))
            let context = container.mainContext; context.autosaveEnabled = false
            let session = try context.fetch(FetchDescriptor<AgentSession>()).first!
            let message = try context.fetch(FetchDescriptor<AgentMessage>()).first!
            precondition(session.id == owner && message.id == messageID && message.inputChannel == "voice")
            precondition(session.composerDraft == "这份原稿要继续修改" && session.composerImage == Data([1, 2, 3]))
            let playback = AgentVoicePlayback.read(message.voicePlaybackJSON)!
            precondition(playback.played == ["第一段。"] && playback.interrupted == "第二段。")
            let empty = try AgentComposerStore.createSession(context: context)
            empty.composerDraft = "另一个未发送草稿"; empty.composerImage = Data([4, 5])
            try context.save()
            let voice = try AgentComposerStore.sendInitial("解释一下", in: empty, context: context,
                consumesDraft: false, inputChannel: "voice", runtime: runtime)
            precondition(voice.inputChannel == "voice" && voice.imageAttachment == nil)
            precondition(empty.composerDraft == "另一个未发送草稿" && empty.composerImage == Data([4, 5]))
        }
        print("PASS: first voice atomic promotion, rollback, original text/images and channel preserved across reopen, actual playback metadata roundtrip")
    }
}
