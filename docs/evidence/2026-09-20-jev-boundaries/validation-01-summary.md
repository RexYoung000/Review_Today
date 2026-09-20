# Jev 三类边界单项对照

全部是七项原始判断。潜在风险为错误标签的离线影响检查，不是实际 Harness 行为；未校准自动接管阈值。

| 分组 | 有效/计划 | 整例命中 | 标签错误 | 潜在风险例 | 需复核 | 未拦截错误 | 中位数/范围 ms | 调用 | 估算 USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| validation/v0 | 48/48 | 38/48 | 10 | 8 | 1 | 9 | 370.9 / 306.5–982.6 | 48 | 0.004265 |
| validation/v1 | 48/48 | 35/48 | 14 | 10 | 2 | 11 | 367.2 / 301.8–656.7 | 48 | 0.004243 |
| validation/resource | 48/48 | 38/48 | 10 | 8 | 1 | 9 | 366.7 / 297.6–1032.2 | 48 | 0.004549 |

## 相对本轮 v1 的变化

- validation/v0：修正 ['B003-outer-pause', 'B020-errand-with-plan', 'B024-foreign-topic', 'B027-quote-resumption', 'B038-decline-promise']；新增错例 ['B006-quoted-title-download', 'B023-unnamed-next-topic']；新增潜在风险 [{'id': 'B023-unnamed-next-topic', 'risk': 'substantive_as_social'}]。
- validation/resource：修正 ['B029-coding-capability', 'B031-coding-mixed', 'B038-decline-promise']；新增错例 []；新增潜在风险 []。

## 全部差异与回退项

- validation/B001-transcript-pause/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- validation/B001-transcript-pause/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- validation/B001-transcript-pause/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- validation/B003-outer-pause/v1：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['missed_knowledge']；回退 []。
- validation/B003-outer-pause/resource：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['missed_knowledge']；回退 []。
- validation/B006-quoted-title-download/v0：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "public_lookup"}]；潜在风险 []；回退 []。
- validation/B009-public-note/v0：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "private_material"}]；潜在风险 []；回退 []。
- validation/B009-public-note/v1：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "private_material"}]；潜在风险 []；回退 []。
- validation/B009-public-note/resource：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "private_material"}]；潜在风险 []；回退 []。
- validation/B019-postpone-plan/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 []。
- validation/B019-postpone-plan/v1：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 []。
- validation/B019-postpone-plan/resource：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 []。
- validation/B020-errand-with-plan/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B020-errand-with-plan/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B022-named-next-topic/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B022-named-next-topic/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B022-named-next-topic/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B023-unnamed-next-topic/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；潜在风险 ['substantive_as_social']；回退 ['social_substantive_conflict']。
- validation/B024-foreign-topic/v1：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "unsure"}]；潜在风险 []；回退 ['uncertain_judgment', 'social_substantive_conflict']。
- validation/B024-foreign-topic/resource：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "unsure"}]；潜在风险 []；回退 ['uncertain_judgment', 'social_substantive_conflict']。
- validation/B027-quote-resumption/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B027-quote-resumption/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B029-coding-capability/v0：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- validation/B029-coding-capability/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- validation/B031-coding-mixed/v0：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- validation/B031-coding-mixed/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- validation/B038-decline-promise/v1：ok；差异 [{"question": "conversation_repair", "expected": "no", "actual": "yes"}]；潜在风险 []；回退 []。
- validation/B045-markdown-log/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- validation/B045-markdown-log/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}, {"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['unrequested_defer', 'resource_boundary_false_block']；回退 ['mixed_request_conflict']。
- validation/B045-markdown-log/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- validation/B046-json-controls/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B046-json-controls/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- validation/B046-json-controls/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
