import SwiftData
import SwiftUI

struct LearningTaskCard: View {
    let task: LearningTask
    let run: AgentRun?
    let runs: [AgentRun]
    let events: [TaskEventRecord]
    let runEvents: [SessionEventRecord]
    let sessionMessages: [AgentMessage]
    let isSessionActive: Bool
    let developerDiagnostics: Bool
    var onControl: (String) -> Void
    var onRespond: (String) -> Void
    @Environment(\.runway) private var runway

    var body: some View {
        let taskEvents = events.filter { $0.taskID == task.id }.sorted { $0.seq < $1.seq }
        let options = Self.options(task.requiredActionOptionsJSON)
        let taskAnswers = sessionMessages.filter { message in
            message.role != "user" && (message.taskID == task.id || runs.contains { $0.id == message.runID && $0.taskID == task.id })
        }
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                if let run, run.status != "completed" {
                    RunPhaseLine(run: run)
                } else {
                    Circle()
                        .fill(Self.tone(task.status) == .problem ? Color.orange : runway.information)
                        .frame(width: 6, height: 6)
                        .padding(.top, 5)
                    Text(task.userSummary)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            HStack(spacing: 8) {
                MetaTag(title: LearningWorkspace.modeLabel(task.mode))
                if task.conversationManaged {
                    Text(task.understanding == "verified" ? "已验证理解" : task.understanding == "self_reported" ? "自述理解 · 未验证" : "尚未验证理解")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Spacer()
                if isSessionActive && (task.status == "retryable_failed" || task.status == "needs_attention") {
                    Button("重试") { onControl("retry") }
                        .buttonStyle(.borderless)
                    Button("取消目标") { onControl("cancel_task") }
                        .buttonStyle(.borderless)
                }
            }

            if isSessionActive, let prompt = task.requiredActionPrompt, task.pendingActionID == nil {
                if !taskAnswers.contains(where: { AnswerDocument.containsQuestion(prompt, in: $0.content) }) {
                    Text(prompt)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(runway.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !options.isEmpty && !task.conversationManaged {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(options, id: \.self) { option in
                            Button {
                                onRespond(option)
                            } label: {
                                HStack(spacing: 8) {
                                    Text(Self.optionLabel(option))
                                        .font(.callout.weight(.medium))
                                        .foregroundStyle(runway.ink)
                                        .fixedSize(horizontal: false, vertical: true)
                                        .multilineTextAlignment(.leading)
                                    Spacer(minLength: 4)
                                    Image(systemName: "arrow.right")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 9)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(runway.field, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }

            RunDetails(run: run?.status == "completed" ? nil : run) {
                VStack(alignment: .leading, spacing: 8) {
                    let sessionEvents = run.map { item in runEvents.filter { $0.runID == item.id } } ?? []
                    if taskEvents.isEmpty && sessionEvents.isEmpty {
                        Text("暂无运行记录")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(taskEvents, id: \.eventID) { event in
                        HStack(alignment: .top, spacing: 8) {
                            Circle()
                                .fill(event.errorCode == nil ? runway.information : Color.orange)
                                .frame(width: 6, height: 6)
                                .padding(.top, 5)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(event.userSummary)
                                    .font(.caption.weight(.medium))
                                    .fixedSize(horizontal: false, vertical: true)
                                if developerDiagnostics { Text(event.node)
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true) }
                                if developerDiagnostics {
                                ViewThatFits(in: .horizontal) {
                                    eventTiming(event)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(event.occurredAt, format: .dateTime.hour().minute().second())
                                        if let duration = event.durationMS { Text("\(duration) ms") }
                                        if event.attempt > 1 { Text("第 \(event.attempt) 次") }
                                    }
                                }
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                                }
                                if !event.detailSummary.isEmpty && (developerDiagnostics || event.errorCode == nil) {
                                    Text(event.detailSummary)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if developerDiagnostics, let error = event.errorCode {
                                    Text(error)
                                        .font(.caption2.monospaced())
                                        .foregroundStyle(.orange)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                if developerDiagnostics, let recovery = event.recoveryAction {
                                    Text("恢复动作：\(recovery)")
                                        .font(.caption2.monospaced())
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                    }
                    if !sessionEvents.isEmpty {
                        ForEach(sessionEvents, id: \.id) { event in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(event.summary).font(.caption.weight(.medium))
                                if !event.detail.isEmpty && (developerDiagnostics || event.errorCode == nil) { Text(event.detail).font(.caption).foregroundStyle(.secondary) }
                                Text(eventInformation(event))
                                    .font(.caption2.monospaced()).foregroundStyle(.secondary)
                            }.padding(.vertical, 2)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 6)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(runway.field.opacity(0.55), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("学习任务：\(task.userSummary)")
    }

    private func eventTiming(_ event: TaskEventRecord) -> some View {
        HStack(spacing: 6) {
            Text(event.occurredAt, format: .dateTime.hour().minute().second())
            if let duration = event.durationMS { Text("\(duration) ms") }
            if event.attempt > 1 { Text("第 \(event.attempt) 次") }
        }
    }

    private func eventInformation(_ event: SessionEventRecord) -> String {
        var values: [String] = []
        if developerDiagnostics { values += [event.stage, event.model] }
        if event.attempt > 1 { values.append("第 \(event.attempt) 次") }
        if developerDiagnostics, let duration = event.durationMS { values.append("\(duration) ms") }
        return values.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private static func options(_ raw: String?) -> [String] {
        guard let raw, let data = raw.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([String].self, from: data)) ?? []
    }

    private static func optionLabel(_ option: String) -> String {
        guard let url = URL(string: option), let host = url.host else { return option }
        let path = url.lastPathComponent.removingPercentEncoding ?? url.lastPathComponent
        return path.isEmpty ? host : "\(host) · \(String(path.prefix(54)))"
    }

    private static func tone(_ status: String) -> StatusChip.Tone {
        switch status {
        case "completed": return .ready
        case "retryable_failed", "needs_attention", "terminal_failed": return .problem
        case "awaiting_user": return .wait
        default: return .quiet
        }
    }}
