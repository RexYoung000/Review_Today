import Foundation

enum MessageDeliveryPresentation {
    static func canRetry(_ message: AgentMessage, session: AgentSession?, runtime: AppRuntime = .current) -> Bool {
        runtime.allowsSending && session?.status == "active" && message.deliveryStatus == "local"
            && message.lastDeliveryError == "RT.RUN.INVALID_ACCEPTANCE"
    }

    static func summary(_ message: AgentMessage, session: AgentSession?, monitor: AgentServiceMonitor, runtime: AppRuntime = .current) -> String {
        if runtime.isPreview { return "界面预览不发送消息，内容仅在内存中。" }
        if message.deliveryStatus == "held" { return "已停止发送，内容已保留" }
        if monitor.deliveringMessageIDs.contains(message.id) { return "正在发送" }
        if message.lastDeliveryError == "RT.RUN.INVALID_ACCEPTANCE" { return "服务未确认接收，输入已保留；可重试发送。" }
        if message.lastDeliveryError == "RT.IMAGE.SERVICE_UPDATE_REQUIRED" { return "图片已保留，当前学习服务尚未支持识图；请重启应用后重试。" }
        if message.lastDeliveryError == "RT.IMAGE.INVALID_FORMAT" { return "本机图片无法读取，请重新添加；原消息已保留。" }
        if message.lastDeliveryError != nil { return "暂时未能送达，输入已保留；连接恢复后继续发送。" }
        if message.runID != nil { return "学习服务已接收" }
        if !monitor.serviceReachable || !monitor.conversationSupported { return "连接中断，内容已保留；恢复后自动发送" }
        if let session, session.syncError != nil { return "暂时无法发送，内容已保留；同步恢复后自动发送" }
        if let session, session.lifecycleRevision != session.lifecycleSyncedRevision || session.memoryPolicyRevision != session.memoryPolicySyncedRevision || session.memoryContentRevision != session.memoryContentSyncedRevision {
            return "正在发送"
        }
        return "等待发送"
    }
}
