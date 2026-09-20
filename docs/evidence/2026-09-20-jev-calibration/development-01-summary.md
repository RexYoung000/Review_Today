# Jev 对话输入与问题拆分对照

v0 原版；v1 只整理上下文；v2 整理上下文并拆分问题。v2 的七项结果经过程序组合，不是原始模型输出。
回退检查只发现不确定或部分矛盾，未校准自动接管阈值，也没有执行完整 Harness。

| 分组 | 有效/计划 | 原始判断正确/评分 | 七项契约整例命中 | 七项判断正确/评分 | 需复核 | 未拦截错误/未拦截样例 | 耗时中位数/范围 ms | 请求数 | 估算 USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| development/v0 | 31/31 | 206/217 | 24/31 | 206/217 | 4 | 3/27 | 385.3 / 330.5–974.2 | 31 | 0.002753 |
| development/v1 | 31/31 | 209/217 | 24/31 | 209/217 | 2 | 5/29 | 388.7 / 320.5–886.1 | 31 | 0.002737 |
| development/v2 | 31/31 | 355/372 | 26/31 | 212/217 | 0 | 5/31 | 409.1 / 333.9–567.2 | 31 | 0.003774 |

## 相对本轮 v0 的整例变化

- development/v1：修正 ['A013-local-transition', 'A013-foreign-goal-transition', 'A015-mode-and-errand']；新增错误 ['A005-coding-capability', 'A010-local-example', 'A015-quoted-request']。
- development/v2：修正 ['A001-defer-active', 'A006-repair-question', 'A013-local-transition', 'A013-foreign-goal-transition', 'A015-continue-errand', 'A015-mode-and-errand']；新增错误 ['A005-coding-capability', 'A007-resume-missing', 'A015-quoted-request', 'A017-credential-link']。
- validation/v1：修正 []；新增错误 []。
- validation/v2：修正 []；新增错误 []。

## 全部契约差异、失败和回退项

- development/A001-defer-active/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；回退原因 []。
- development/A001-defer-active/v1：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；回退原因 []。
- development/A005-coding-capability/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；回退原因 []。
- development/A005-coding-capability/v2：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；回退原因 []。
- development/A006-repair-question/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "knowledge_request", "expected": "yes", "actual": "no"}]；回退原因 ['social_substantive_conflict']。
- development/A006-repair-question/v1：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "knowledge_request", "expected": "yes", "actual": "no"}]；回退原因 ['social_substantive_conflict']。
- development/A007-resume-missing/v2：ok；差异 [{"question": "knowledge_request", "expected": "no", "actual": "yes"}]；回退原因 []。
- development/A010-local-example/v1：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；回退原因 []。
- development/A013-local-transition/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；回退原因 ['social_substantive_conflict']。
- development/A013-foreign-goal-transition/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "progress", "expected": "clarify_next", "actual": "next_current"}]；回退原因 ['social_substantive_conflict', 'missing_current_task']。
- development/A015-capability/v0：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；回退原因 []。
- development/A015-capability/v1：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；回退原因 []。
- development/A015-capability/v2：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；回退原因 []。
- development/A015-continue-errand/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "unsure"}, {"question": "progress", "expected": "none", "actual": "clarify_next"}, {"question": "resource_boundary", "expected": "resource_delivery", "actual": "none"}]；回退原因 ['uncertain_judgment', 'social_substantive_conflict']。
- development/A015-continue-errand/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；回退原因 []。
- development/A015-quoted-request/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；回退原因 ['mixed_request_conflict']。
- development/A015-quoted-request/v2：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；回退原因 []。
- development/A015-mode-and-errand/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；回退原因 []。
- development/A017-credential-link/v2：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；回退原因 []。
