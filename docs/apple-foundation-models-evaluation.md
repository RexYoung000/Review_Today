# Apple Foundation Models 与 Private Cloud Compute 评估

> 状态：候选技术路线，尚未实施
> 决策：不进入里程碑一；在里程碑二使用固定评测集与当前 OpenAI 路线对比

## 1. 结论

Apple 当前将 AI 建设成 Apple 平台的系统级基础能力：开发者可以通过统一的 Foundation Models Swift API 使用设备端 Apple Foundation Model、Private Cloud Compute（PCC）模型以及符合 Language Model 协议的其他模型。

这对 Review Today 是中长期利好，尤其适合知识卡生成、结构化评分和隐私敏感的回答判断。但 PCC 受系统版本、设备、地区、App Store 资格和用户每日额度约束，也不能直接解决实时语音交互。因此当前不迁移架构，只把它加入里程碑二的模型质量与可用性评测。

## 2. Apple 当前开发者策略

- **设备端优先**：先使用可离线、无请求额度的设备端模型；通过评测证明能力不足后再切换 PCC。
- **统一 Swift 接口**：设备端、PCC 和其他 Language Model 提供者使用同一套会话、结构化输出和工具调用接口。
- **扶持小开发者**：符合条件的小开发者可使用 PCC，开发者无需支付云端 API 费用，也无需管理 PCC 的 API Key 或用户认证。
- **隐私作为基础能力**：PCC 请求数据只用于当次请求，不由 App 自建云端模型服务保存。
- **用评测而非预设选择模型**：Apple 提供 Evaluations 框架，鼓励开发者用真实样本比较设备端与云端模型。
- **平台与商业约束并存**：PCC 通过 App Store、Apple Intelligence、iCloud 用户额度和 managed entitlement 提供，不是无条件开放的通用 REST 云服务。

## 3. 对 Review Today 的帮助

### 高价值场景

1. **知识卡生成**
   - Foundation Models 支持结构化输出，可生成标题、解释、证据、问题和评分规格。
   - PCC 提供 32K 上下文和更强推理，适合较长知识材料。

2. **回答判断**
   - 短问题与短回答有机会优先使用设备端模型，降低成本并增强隐私。
   - 评分规格与结构化判断可以继续沿用当前产品设计，不需要先结构化用户原始回答。

3. **模型评测与切换**
   - 同一业务契约可以对比设备端模型、PCC 与 OpenAI。
   - 如果 Apple 路线质量达标，未来可减少本机 Python 服务承担的简单模型调用。

4. **隐私表达与独立开发者成本**
   - 设备端处理和 PCC 的隐私边界适合个人知识与学习回答场景。
   - PCC 无开发者云端 API 费用，有利于早期独立产品控制推理成本。

### 不能直接解决

- OpenAI Realtime 类的实时双向语音、VAD、打断与低延迟音频链路；
- LangGraph 的任务状态、恢复、幂等、运行事件和业务 Harness；
- FSRS、通知、知识生命周期和本地数据事务；
- Agent 吉祥物、口型和 Spine 动画。

## 4. 关键限制

1. **系统版本**
   - `PrivateCloudComputeLanguageModel` 需要 iOS 27、macOS 27、watchOS 27 或 visionOS 27 及以上。
   - Review Today 当前构建目标是 macOS 26.5，PCC 不能成为当前唯一模型路径。

2. **设备与地区**
   - 用户设备必须支持并启用 Apple Intelligence。
   - PCC 只在 Apple Intelligence 可用地区提供。
   - Apple 官方当前仍说明 Apple Intelligence 在中国大陆相关设备、位置和账户条件下不可用，因此不能把 PCC 作为中国大陆用户的可靠基础设施。

3. **开发者资格**
   - 需要加入 App Store Small Business Program；
   - 任一 App 首次 App 下载次数低于 200 万；
   - Apple 开发者账户获得 PCC managed entitlement；
   - 正式能力需通过 App Store 分发，测试可使用 TestFlight 或 Ad Hoc。

4. **额度与迁移风险**
   - PCC 按用户提供每日额度，用户可通过 iCloud+ 获得更高额度；产品必须处理接近额度、额度耗尽和降级。
   - 如果任一 App 超过 200 万首次下载，或开发者退出 Small Business Program，需要在收到通知后 6 个月内迁移到替代方案。

5. **平台边界**
   - PCC 通过 Apple 的客户端 Foundation Models 框架使用，不是供当前 Python FastAPI 直接调用的通用云 API。
   - 依赖 PCC 会增强 Apple 平台优势，但不能覆盖未来 Android、Web 或非 Apple 服务端场景。

## 5. 当前产品决策

- 里程碑一继续使用现有 OpenAI 链路，完成纯文字真实 App 闭环；
- 不为 PCC 提前重构 LangGraph、FastAPI 或 SwiftData；
- 不把“零 API 费用”当作无限免费，必须保留额度和可用性判断；
- 在里程碑二使用同一固定评测集比较：

```text
Apple 设备端 SystemLanguageModel
vs. Apple PrivateCloudComputeLanguageModel（满足资格和环境时）
vs. 当前 OpenAI 基线
```

- 只有质量、中文能力、延迟、地区覆盖和降级体验都达到门槛后，才决定是否进入 Harness 层的模型适配。

## 6. 里程碑二评测项

- 知识卡忠实度、拆分质量和问题可答性；
- 正确、部分正确、错误和常见误解回答的评分一致性；
- 简体中文输入、指令和输出质量；
- 设备端与 PCC 的上下文限制、延迟和稳定性；
- Apple Intelligence 不可用、网络中断和 PCC 额度耗尽时的降级；
- 隐私边界、开发者资格与未来跨平台成本。

评测通过前，不确定最终模型供应商，也不改变当前最小闭环范围。

## 7. Apple 官方依据

- [访问专用云计算](https://developer.apple.com/cn/private-cloud-compute/)
- [使用 Private Cloud Compute 增加服务端智能](https://developer.apple.com/documentation/FoundationModels/adding-server-side-intelligence-with-private-cloud-compute)
- [Apple Intelligence 开发者能力](https://developer.apple.com/apple-intelligence/)
- [Foundation Models 框架](https://developer.apple.com/documentation/foundationmodels)
- [Apple Intelligence 地区与设备要求](https://support.apple.com/zh-cn/121115)
