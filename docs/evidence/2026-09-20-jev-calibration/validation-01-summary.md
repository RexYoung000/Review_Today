# Jev 对话输入与问题拆分对照

v0 原版；v1 只整理上下文；v2 整理上下文并拆分问题。v2 的七项结果经过程序组合，不是原始模型输出。
回退检查只发现不确定或部分矛盾，未校准自动接管阈值，也没有执行完整 Harness。

| 分组 | 有效/计划 | 原始判断正确/评分 | 七项契约整例命中 | 七项判断正确/评分 | 需复核 | 未拦截错误/未拦截样例 | 耗时中位数/范围 ms | 请求数 | 估算 USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| validation/v0 | 24/24 | 162/168 | 18/24 | 162/168 | 2 | 4/22 | 389.8 / 305.3–1008.7 | 24 | 0.002126 |
| validation/v1 | 24/24 | 164/168 | 20/24 | 164/168 | 0 | 4/24 | 391.8 / 318.6–526.6 | 24 | 0.002105 |
| validation/v2 | 24/24 | 273/288 | 17/24 | 161/168 | 0 | 7/24 | 418.4 / 359.0–944.1 | 24 | 0.002907 |

## 相对本轮 v0 的整例变化

- development/v1：修正 []；新增错误 []。
- development/v2：修正 []；新增错误 []。
- validation/v1：修正 ['V004-transition-other-goal', 'V006-defer-exercise', 'V010-polite-errand']；新增错误 ['V005-next-bound-plan']。
- validation/v2：修正 ['V006-defer-exercise', 'V007-anaphoric-errand', 'V010-polite-errand']；新增错误 ['V003-official-lookup', 'V005-next-bound-plan', 'V008-cancel-errand-explain', 'V024-coding-delivery']。

## 全部契约差异、失败和回退项

- validation/V003-official-lookup/v2：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；回退原因 []。
- validation/V004-transition-other-goal/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；回退原因 ['social_substantive_conflict']。
- validation/V004-transition-other-goal/v2：ok；差异 [{"question": "knowledge_request", "expected": "no", "actual": "yes"}]；回退原因 []。
- validation/V005-next-bound-plan/v1：ok；差异 [{"question": "knowledge_request", "expected": "no", "actual": "yes"}]；回退原因 []。
- validation/V005-next-bound-plan/v2：ok；差异 [{"question": "knowledge_request", "expected": "no", "actual": "yes"}]；回退原因 []。
- validation/V006-defer-exercise/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；回退原因 []。
- validation/V007-anaphoric-errand/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；回退原因 []。
- validation/V007-anaphoric-errand/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；回退原因 []。
- validation/V008-cancel-errand-explain/v2：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；回退原因 []。
- validation/V010-polite-errand/v0：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "unsure"}]；回退原因 ['uncertain_judgment']。
- validation/V011-quoted-controls/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；回退原因 []。
- validation/V011-quoted-controls/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；回退原因 []。
- validation/V011-quoted-controls/v2：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；回退原因 []。
- validation/V022-token-link/v0：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；回退原因 []。
- validation/V022-token-link/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；回退原因 []。
- validation/V022-token-link/v2：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；回退原因 []。
- validation/V024-coding-delivery/v2：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；回退原因 []。
