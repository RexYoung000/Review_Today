import Foundation

@main
struct DictationPrototypeTests {
    @MainActor
    static func main() async throws {
        func makeState() -> DictationDemoState {
            DictationDemoState(transcriptionDelay: .milliseconds(12), cleaningDelay: .milliseconds(12))
        }
        func captureSpeech(_ state: DictationDemoState) {
            state.start()
            state.tick(date: .now.addingTimeInterval(0.7))
        }
        func check(_ condition: @autoclosure () -> Bool, _ message: String) {
            precondition(condition(), message)
        }
        func settle() async throws {
            try await Task.sleep(for: .milliseconds(90))
        }

        let cancelled = makeState()
        cancelled.draft = "原有草稿"
        captureSpeech(cancelled)
        cancelled.cancel()
        check(cancelled.draft == "原有草稿" && cancelled.phase == .idle && !cancelled.hasPending,
              "Cancelling a recording must retain the existing draft.")

        let late = makeState()
        late.draft = "保留我"
        captureSpeech(late)
        late.finish()
        check(late.phase == .transcribing, "A voiced recording must begin processing.")
        late.cancel()
        late.start()
        try await settle()
        check(late.draft == "保留我" && late.phase == .recording,
              "A cancelled processing result must not append text or end the next recording.")
        late.cancel()

        let completed = makeState()
        completed.draft = "既有内容"
        captureSpeech(completed)
        completed.finish()
        completed.finish()
        try await settle()
        check(completed.phase == .idle && !completed.hasPending, "Processing must finish and release pending content.")
        check(completed.draft.hasPrefix("既有内容\n") && completed.draft.components(separatedBy: "请帮我").count == 2,
              "Repeated finish must append the transcript exactly once, retaining the existing draft.")
        check(completed.lastSent == nil && completed.notice == "已添加到草稿",
              "Finishing dictation must not send the draft.")
        completed.send()
        check(completed.lastSent?.hasPrefix("既有内容") == true && completed.draft.isEmpty,
              "Only the explicit simulated send action clears the draft.")

        let retry = makeState()
        retry.failNext = true
        captureSpeech(retry)
        retry.finish()
        try await settle()
        check(retry.phase == .failed && retry.hasPending && retry.draft.isEmpty,
              "A failed recording must remain retryable without invented draft text.")
        retry.retry()
        try await settle()
        check(retry.phase == .idle && !retry.draft.isEmpty && retry.lastSent == nil,
              "Retry must reuse pending synthetic speech and return it to the draft.")

        let discard = makeState()
        discard.draft = "已有文字"
        discard.failNext = true
        captureSpeech(discard)
        discard.finish()
        try await settle()
        discard.cancel()
        discard.retry()
        try await settle()
        check(discard.draft == "已有文字" && discard.phase == .idle && !discard.hasPending,
              "Discard must release failed audio and prevent a later retry from restoring it.")

        let silent = makeState()
        silent.draft = "静音前草稿"
        silent.signal = .silent
        captureSpeech(silent)
        check(silent.level(at: 0.7) == 0, "Silent input must have no waveform energy.")
        silent.finish()
        try await settle()
        check(silent.phase == .idle && silent.draft == "静音前草稿" && !silent.hasPending,
              "Silence must not create a synthetic transcript.")

        let limited = makeState()
        captureSpeech(limited)
        check(limited.level(at: 1.6) == 0 && limited.level(at: 0.7) > 0,
              "The synthetic signal must contain real pauses between phrases.")
        limited.tick(date: .now.addingTimeInterval(301))
        check(limited.elapsed == 300 && limited.phase == .transcribing,
              "The five-minute limit must finish a voiced recording automatically.")
        limited.reset()
        try await settle()
        check(limited.draft.isEmpty && limited.phase == .idle && limited.lastSent == nil,
              "Reset must suppress pending processing and restore the empty study.")

        print("PASS: cancellation, late results, draft-only completion, duplicate finish, retry/discard, silence, pauses, duration limit and reset")
    }
}
