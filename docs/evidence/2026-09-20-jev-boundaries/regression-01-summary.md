# Jev 三类边界单项对照

全部是七项原始判断。潜在风险为错误标签的离线影响检查，不是实际 Harness 行为；未校准自动接管阈值。

| 分组 | 有效/计划 | 整例命中 | 标签错误 | 潜在风险例 | 需复核 | 未拦截错误 | 中位数/范围 ms | 调用 | 估算 USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regression/v0 | 55/55 | 43/55 | 16 | 10 | 6 | 6 | 374.2 / 307.8–1010.3 | 55 | 0.004879 |
| regression/v1 | 55/55 | 43/55 | 13 | 10 | 3 | 9 | 371.4 / 315.7–780.0 | 55 | 0.004842 |
| regression/scope | 55/55 | 43/55 | 14 | 8 | 3 | 9 | 394.3 / 322.6–675.9 | 55 | 0.007737 |
| regression/resource | 55/55 | 45/55 | 11 | 8 | 2 | 8 | 386.7 / 305.4–613.3 | 55 | 0.005193 |
| regression/progress | 55/55 | 47/55 | 8 | 7 | 3 | 5 | 369.6 / 312.9–969.6 | 55 | 0.005429 |

## 相对本轮 v1 的变化

- regression/v0：修正 ['A005-coding-capability', 'A010-local-example', 'A015-quoted-request', 'A017-internal-material', 'V005-next-bound-plan', 'V007-anaphoric-errand', 'V022-token-link']；新增错例 ['A013-local-transition', 'A013-foreign-goal-transition', 'A015-mode-and-errand', 'V004-transition-other-goal', 'V006-defer-exercise', 'V010-polite-errand', 'V024-coding-delivery']；新增潜在风险 [{'id': 'A013-local-transition', 'risk': 'substantive_as_social'}, {'id': 'A013-foreign-goal-transition', 'risk': 'substantive_as_social'}, {'id': 'A013-foreign-goal-transition', 'risk': 'wrong_learning_target'}, {'id': 'A015-continue-errand', 'risk': 'resource_boundary_missed'}, {'id': 'A015-mode-and-errand', 'risk': 'wrong_learning_target'}, {'id': 'V004-transition-other-goal', 'risk': 'substantive_as_social'}, {'id': 'V006-defer-exercise', 'risk': 'substantive_as_social'}, {'id': 'V024-coding-delivery', 'risk': 'resource_boundary_false_block'}]。
- regression/scope：修正 ['A005-coding-capability', 'A015-quoted-request', 'A017-internal-material', 'V005-next-bound-plan', 'V011-quoted-controls', 'V022-token-link']；新增错例 ['A015-links-after-promise', 'A015-defer-and-errand', 'V006-defer-exercise', 'V010-polite-errand', 'V019-explicit-restore', 'V024-coding-delivery']；新增潜在风险 [{'id': 'V006-defer-exercise', 'risk': 'substantive_as_social'}, {'id': 'V019-explicit-restore', 'risk': 'resource_boundary_false_block'}, {'id': 'V024-coding-delivery', 'risk': 'resource_boundary_false_block'}]。
- regression/resource：修正 ['A017-internal-material', 'V022-token-link']；新增错例 []；新增潜在风险 []。
- regression/progress：修正 ['A010-local-example', 'A015-continue-errand', 'V005-next-bound-plan', 'V007-anaphoric-errand', 'V011-quoted-controls']；新增错例 ['A017-credential-link']；新增潜在风险 [{'id': 'A017-credential-link', 'risk': 'resource_boundary_false_block'}]。

## 全部差异与回退项

- regression/A001-defer-active/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/A001-defer-active/v1：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/A001-defer-active/scope：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/A001-defer-active/resource：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/A001-defer-active/progress：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "companionship"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/A005-coding-capability/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/A005-coding-capability/resource：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/A005-coding-capability/progress：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "capability_question"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/A006-repair-question/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['substantive_as_social', 'missed_knowledge']；回退 ['social_substantive_conflict']。
- regression/A006-repair-question/v1：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['substantive_as_social', 'missed_knowledge']；回退 ['social_substantive_conflict']。
- regression/A006-repair-question/scope：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['substantive_as_social', 'missed_knowledge']；回退 ['social_substantive_conflict']。
- regression/A006-repair-question/resource：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['substantive_as_social', 'missed_knowledge']；回退 ['social_substantive_conflict']。
- regression/A006-repair-question/progress：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 ['social_substantive_conflict']。
- regression/A010-local-example/v1：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['missed_knowledge']；回退 []。
- regression/A010-local-example/scope：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['missed_knowledge']；回退 []。
- regression/A010-local-example/resource：ok；差异 [{"question": "knowledge_request", "expected": "yes", "actual": "no"}]；潜在风险 ['missed_knowledge']；回退 []。
- regression/A013-local-transition/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 ['social_substantive_conflict']。
- regression/A013-foreign-goal-transition/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}, {"question": "progress", "expected": "clarify_next", "actual": "next_current"}]；潜在风险 ['substantive_as_social', 'wrong_learning_target']；回退 ['social_substantive_conflict', 'missing_current_task']。
- regression/A015-capability/v0：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；潜在风险 []；回退 []。
- regression/A015-capability/v1：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；潜在风险 []；回退 []。
- regression/A015-capability/scope：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；潜在风险 []；回退 []。
- regression/A015-capability/resource：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；潜在风险 []；回退 []。
- regression/A015-capability/progress：ok；差异 [{"question": "resource_boundary", "expected": "capability_question", "actual": "resource_delivery"}]；潜在风险 []；回退 []。
- regression/A015-links-after-promise/scope：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "public_lookup"}]；潜在风险 []；回退 []。
- regression/A015-continue-errand/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "unsure"}, {"question": "progress", "expected": "none", "actual": "clarify_next"}, {"question": "resource_boundary", "expected": "resource_delivery", "actual": "none"}]；潜在风险 ['wrong_learning_target', 'resource_boundary_missed']；回退 ['uncertain_judgment', 'social_substantive_conflict']。
- regression/A015-continue-errand/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- regression/A015-continue-errand/scope：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "unsure"}, {"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 ['uncertain_judgment', 'social_substantive_conflict']。
- regression/A015-continue-errand/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- regression/A015-quoted-request/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 ['mixed_request_conflict']。
- regression/A015-quoted-request/resource：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 ['mixed_request_conflict']。
- regression/A015-quoted-request/progress：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 ['mixed_request_conflict']。
- regression/A015-mode-and-errand/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- regression/A015-defer-and-errand/scope：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "public_lookup"}]；潜在风险 []；回退 []。
- regression/A017-internal-material/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 ['mixed_request_conflict']。
- regression/A017-internal-material/progress：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 ['mixed_request_conflict']。
- regression/A017-credential-link/progress：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/V004-transition-other-goal/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 ['social_substantive_conflict']。
- regression/V005-next-bound-plan/v1：ok；差异 [{"question": "knowledge_request", "expected": "no", "actual": "yes"}]；潜在风险 []；回退 []。
- regression/V005-next-bound-plan/resource：ok；差异 [{"question": "knowledge_request", "expected": "no", "actual": "yes"}]；潜在风险 []；回退 []。
- regression/V006-defer-exercise/v0：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/V006-defer-exercise/scope：ok；差异 [{"question": "conversation_kind", "expected": "ordinary", "actual": "social"}]；潜在风险 ['substantive_as_social']；回退 []。
- regression/V007-anaphoric-errand/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "clarify_next"}]；潜在风险 ['wrong_learning_target']；回退 []。
- regression/V007-anaphoric-errand/scope：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- regression/V007-anaphoric-errand/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "resume_prior"}]；潜在风险 ['wrong_learning_target']；回退 []。
- regression/V010-polite-errand/v0：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "unsure"}]；潜在风险 []；回退 ['uncertain_judgment']。
- regression/V010-polite-errand/scope：ok；差异 [{"question": "web_scope", "expected": "no_need", "actual": "unsure"}]；潜在风险 []；回退 ['uncertain_judgment']。
- regression/V011-quoted-controls/v0：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- regression/V011-quoted-controls/v1：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- regression/V011-quoted-controls/resource：ok；差异 [{"question": "progress", "expected": "none", "actual": "defer"}]；潜在风险 ['unrequested_defer']；回退 []。
- regression/V019-explicit-restore/scope：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/V022-token-link/v1：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/V022-token-link/progress：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "mixed_learning"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/V024-coding-delivery/v0：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
- regression/V024-coding-delivery/scope：ok；差异 [{"question": "resource_boundary", "expected": "none", "actual": "resource_delivery"}]；潜在风险 ['resource_boundary_false_block']；回退 []。
