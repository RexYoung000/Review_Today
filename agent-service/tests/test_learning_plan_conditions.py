"""Step conditions describe local capabilities without rewriting mastery evidence."""
import copy
import unittest

from pydantic import ValidationError

from agent_service.learning_progress import advance, record_understanding, set_plan
from agent_service.schemas import LearningPlan


TITLES = ["理解检索", "理解生成"]
CONDITIONS = ["说明检索如何找到相关资料", "说明模型如何依据资料生成答案"]


def task():
    return {"task_id": "task", "content": "理解 RAG", "context": {}}


class LearningPlanConditionSchemaTests(unittest.TestCase):
    def test_legacy_cached_plan_remains_readable_without_inventing_conditions(self):
        legacy = {"goal": "理解 RAG", "steps": TITLES, "success_check": "解释完整流程"}
        parsed = LearningPlan.model_validate(legacy)
        self.assertEqual(parsed.step_conditions, [])
        self.assertEqual(LearningPlan.model_validate_json(parsed.model_dump_json()), parsed)

    def test_distinct_conditions_are_kept_in_step_order(self):
        parsed = LearningPlan(goal="理解 RAG", steps=TITLES, success_check="解释完整流程",
                              step_conditions=CONDITIONS)
        self.assertEqual(parsed.step_conditions, CONDITIONS)

    def test_partial_blank_or_oversized_conditions_are_rejected(self):
        for conditions in [[CONDITIONS[0]], [*CONDITIONS, "额外条件"], [" ", CONDITIONS[1]], ["条件"] * 9]:
            with self.subTest(conditions=conditions), self.assertRaises(ValidationError):
                LearningPlan(goal="理解 RAG", steps=TITLES, success_check="整体标准",
                             step_conditions=conditions)


class LearningPlanConditionStateTests(unittest.TestCase):
    def test_new_steps_store_local_conditions_separately_from_global_standard(self):
        plan = set_plan(task(), TITLES, "解释完整流程", step_conditions=CONDITIONS)
        self.assertEqual([step["completion_condition"] for step in plan["steps"]], CONDITIONS)
        self.assertEqual(plan["success_check"], "解释完整流程")
        self.assertTrue(all(step["state"] == "pending" and step["understanding"] == "unknown"
                            for step in plan["steps"]))

    def test_legacy_call_does_not_copy_global_standard_into_new_steps(self):
        for conditions in [None, []]:
            with self.subTest(conditions=conditions):
                plan = set_plan(task(), TITLES, "解释完整流程", step_conditions=conditions)
                self.assertEqual([step["completion_condition"] for step in plan["steps"]], ["", ""])
                self.assertEqual(plan["success_check"], "解释完整流程")

    def test_condition_only_update_versions_plan_and_preserves_evidence(self):
        state = task()
        old = set_plan(state, TITLES, "解释完整流程", step_conditions=CONDITIONS)
        record_understanding(state, "verified")
        old["steps"][0]["message_ids"].append("answer-1")
        before = copy.deepcopy(old)
        revised = ["说明检索如何选出与问题相关的资料", CONDITIONS[1]]
        updated = set_plan(state, TITLES, "解释完整流程", step_conditions=revised)
        self.assertEqual(updated["version"], before["version"] + 1)
        self.assertEqual(updated["current_step_id"], before["current_step_id"])
        for original, changed in zip(before["steps"], updated["steps"]):
            for key in ("id", "state", "understanding", "message_ids"):
                self.assertEqual(changed[key], original[key])
        self.assertEqual(updated["steps"][0]["completion_condition"], revised[0])
        again = set_plan(state, TITLES, "解释完整流程", step_conditions=revised)
        self.assertEqual(again, updated)

    def test_reorder_rename_and_new_step_preserve_identity_and_align_conditions(self):
        state = task()
        old = set_plan(state, TITLES, "解释完整流程", step_conditions=CONDITIONS)
        first, second = [step["id"] for step in old["steps"]]
        record_understanding(state, "verified")
        old["steps"][0]["message_ids"].append("answer-1")
        updated = set_plan(state, [TITLES[1], "相关资料检索", "验证答案"], step_ids=[second, first, ""],
                           step_conditions=[CONDITIONS[1], CONDITIONS[0], "用原始证据核对答案"])
        self.assertEqual(updated["current_step_id"], first)
        self.assertEqual(updated["steps"][1]["id"], first)
        self.assertEqual(updated["steps"][1]["understanding"], "verified")
        self.assertEqual(updated["steps"][1]["message_ids"], ["answer-1"])
        self.assertEqual(updated["steps"][0]["completion_condition"], CONDITIONS[1])
        self.assertEqual(updated["steps"][1]["completion_condition"], CONDITIONS[0])
        self.assertEqual(updated["steps"][2]["understanding"], "unknown")

    def test_missing_new_conditions_preserve_existing_legacy_values_and_evidence(self):
        state = task()
        old = set_plan(state, TITLES, "旧整体标准")
        old["steps"][0]["completion_condition"] = "旧整体标准"
        old["steps"][1].pop("completion_condition")
        record_understanding(state, "verified")
        old["steps"][0]["message_ids"].append("old-answer")
        before = copy.deepcopy(old)
        updated = set_plan(state, TITLES)
        self.assertEqual(updated, before)
        expanded = set_plan(state, [*TITLES, "新增步骤"])
        self.assertEqual(expanded["steps"][:2], before["steps"])
        self.assertEqual(expanded["steps"][2]["completion_condition"], "")

    def test_invalid_conditions_leave_task_unchanged(self):
        state = task()
        set_plan(state, TITLES, "整体标准", step_conditions=CONDITIONS)
        before = copy.deepcopy(state)
        for conditions in [[CONDITIONS[0]], ["", CONDITIONS[1]], [None, CONDITIONS[1]]]:
            with self.subTest(conditions=conditions), self.assertRaisesRegex(ValueError, "INVALID_STEP_CONDITIONS"):
                set_plan(state, TITLES, "新整体标准", step_conditions=conditions)
            self.assertEqual(state, before)

    def test_explicit_conditions_do_not_authorize_advancement_or_mastery(self):
        state = task()
        plan = set_plan(state, TITLES, "整体标准", step_conditions=CONDITIONS)
        first = plan["current_step_id"]
        self.assertFalse(advance(state))
        self.assertEqual(plan["current_step_id"], first)
        record_understanding(state, "unknown")
        self.assertFalse(advance(state))
        self.assertNotEqual(plan["current_step_id"], first)
        self.assertTrue(all(step["understanding"] == "unknown" for step in plan["steps"]))
