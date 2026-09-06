import Foundation

enum MessageDeliveryPresentation {
    static func canRetry(_ message: AgentMessage, session: AgentSession?, runtime: AppRuntime = .current) -> Bool {
        runtime.allowsSending && session?.status == "active" && message.deliveryStatus == "local"
            && message.lastDeliveryError == "RT.RUN.INVALID_ACCEPTANCE"
    }

    static func summary(_ message: AgentMessage, session: AgentSession?, monitor: AgentServiceMonitor, runtime: AppRuntime = .current) -> String {
        if runtime.isPreview { return "界面预览不发送消息，内容仅在内存中。" }
        if message.deliveryStatus == "held" { return "已停止发送，内容保留在本机" }
        if monitor.deliveringMessageIDs.contains(message.id) { return "正在发送，输入已保存在本机" }
        if message.lastDeliveryError == "RT.RUN.INVALID_ACCEPTANCE" { return "服务未确认接收，输入已保留；可重试发送。" }
        if message.lastDeliveryError != nil { return "暂时未能送达，输入已保留；连接恢复后继续发送。" }
        if message.runID != nil { return "学习服务已接收" }
        if !monitor.serviceReachable || !monitor.conversationSupported { return "已保存在本机，等待学习服务连接" }
        if let session, session.syncError != nil { return "已保存在本机，会话同步暂未完成" }
        if let session, session.lifecycleRevision != session.lifecycleSyncedRevision || session.memoryPolicyRevision != session.memoryPolicySyncedRevision || session.memoryContentRevision != session.memoryContentSyncedRevision {
            return "已保存在本机，正在同步会话"
        }
        return "已保存在本机，等待发送"
    }
}
