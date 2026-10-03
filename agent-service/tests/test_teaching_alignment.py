"""Teaching checks are grounded in the current lesson, not the whole roadmap."""
import json
import unittest
import uuid
from unittest.mock import patch

from pydantic import ValidationError

from agent_service.learning_progress import current_step
from agent_service.openai_client import ModelCallError, schema_diagnostic
from agent_service.schemas import ConversationOutput, LearningPlan, MasteryEvaluation
from tests import test_conversation_v2 as fixture
from tests.test_conversation_v2 import intent


LESSON = "RAG（检索增强生成）像开卷答题：先找到相关资料，再依据资料回答。它能给回答补充模型未学过的资料，但仍可能检索错或答错。"
QUESTION = "公司昨天更新了内部说明，RAG 怎样帮助回答相关问题？"


class TeachingAlignmentTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    tearDown = fixture.ConversationTests.tearDown
    send = fixture.ConversationTests.send
    state = fixture.ConversationTests.state

    def model(self, system, user, schema, **kwargs):
        if schema is ConversationOutput:
            payload = json.loads(user)
            existing = ((payload.get("context", {}).get("task") or {}).get("context", {}).get("learning_plan"))
            return ConversationOutput(message=LESSON if not existing else "本节讲解检索与生成各自的职责。",
                                      check_question=QUESTION if not existing else "检索和生成各负责什么？",
                                      learning_plan=None if existing else LearningPlan(
                                          goal="理解 RAG 的作用和流程", steps=["为什么需要 RAG", "检索与生成的职责"],
                                          success_check="能解释作用并串起完整流程",
                                          step_conditions=["能举例说明外部资料的作用", "能区分检索和生成的职责"]))
        result = fixture.ConversationTests.model(self, system, user, schema, **kwargs)
        if schema is MasteryEvaluation and getattr(self, "partial_answer", False):
            return result.model_copy(update={"passed": False, "feedback": "已经提到外部资料，还缺少如何用资料回答。"})
        return result

    def start_lesson(self):
        self.decision = intent("goal", workflow="source_learning", direct_teaching=True)
        self.send("直接教我 RAG", mode="source_learning")
        data = self.state()
        return data["tasks"][data["active_task_id"]]

    def answer(self):
        self.decision = intent("answer", workflow="source_learning", scope="continue_goal")
        self.send("先查到昨天的新说明，再依据说明回答。")

    def test_daily_grading_receives_current_lesson_and_step_and_verifies_only_that_step(self):
        task = self.start_lesson()
        before_step = current_step(task)
        self.assertEqual(task["context"]["understanding"], "unknown")
        self.answer()
        grading = next(payload for schema, payload in self.calls if schema is MasteryEvaluation)
        self.assertEqual(grading["reference"], LESSON)
        self.assertEqual(grading["question"], QUESTION)
        self.assertEqual(grading["learning_step"]["id"], before_step["id"])
        self.assertEqual(grading["learning_step"]["title"], "为什么需要 RAG")
        self.assertNotIn("completion_condition", grading["learning_step"])
        self.assertNotIn("能区分检索和生成", str(grading))
        task = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(task)["understanding"], "verified")
        self.assertEqual(task["context"]["understanding"], "unknown")
        self.assertEqual(task["context"]["learning_plan"]["steps"][1]["state"], "pending")

    def test_partial_answer_does_not_verify_or_advance(self):
        task = self.start_lesson()
        identity = current_step(task)["id"]
        self.partial_answer = True
        self.answer()
        task = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(task)["id"], identity)
        self.assertEqual(current_step(task)["understanding"], "unknown")
        self.assertFalse(task["context"]["practice"][-1]["evaluation"]["passed"])

    def test_old_global_placeholder_is_not_a_current_step_requirement(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            context = data["tasks"][task["task_id"]]["context"]
            context["reference_answer"] = "旧的宽泛参考，不应覆盖本节讲解。"
            plan = context["learning_plan"]
            for step in plan["steps"]:
                step["completion_condition"] = plan["success_check"]
        self.answer()
        grading = next(payload for schema, payload in self.calls if schema is MasteryEvaluation)
        self.assertEqual(grading["reference"], LESSON)
        self.assertNotIn("completion_condition", grading["learning_step"])
        saved = self.state()["tasks"][task["task_id"]]["context"]["learning_plan"]
        self.assertTrue(all(step["completion_condition"] == saved["success_check"] for step in saved["steps"]))
        payloads = []
        base = self.model
        def capture(system, user, schema, **kwargs):
            if schema is ConversationOutput:
                payloads.append(json.loads(user))
            return base(system, user, schema, **kwargs)
        self.decision = intent("continue", workflow="source_learning", scope="continue_goal")
        with patch("agent_service.conversation.parse_model", side_effect=capture):
            self.send("继续下一节")
        self.assertEqual(payloads[-1]["learning_step"]["completion_condition"], "")
        self.assertEqual(payloads[-1]["learning_step"]["title"], "检索与生成的职责")
        after = self.state()["tasks"][task["task_id"]]["context"]["learning_plan"]
        self.assertTrue(all(step["completion_condition"] == after["success_check"] for step in after["steps"]))

    def test_missing_reference_cannot_grade_or_invent_mastery(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            data["tasks"][task["task_id"]]["context"].pop("last_lesson")
        self.answer()
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))
        task = self.state()["tasks"][task["task_id"]]
        self.assertEqual(task["context"]["understanding"], "unknown")
        self.assertNotEqual(current_step(task)["understanding"], "verified")
        self.assertEqual(task["required_action"]["type"], "respond")
        self.assertNotEqual(task["required_action"]["prompt"], QUESTION)
        self.assertIn("依据", self.state()["messages"][-1]["content"])
        self.assertIn("继续", self.state()["messages"][-1]["content"])

    def test_problem_grading_includes_followup_teaching_and_original_reference(self):
        self.decision = intent("question", workflow="problem_solving", scope="learning")
        self.send("RAG 是什么", mode="problem_solving")
        self.decision = intent("answer", workflow="problem_solving", scope="continue_goal")
        self.send("准备工程师面试")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        reference = task["context"]["reference_answer"]
        lesson = task["context"]["last_lesson"]
        self.assertNotEqual(reference, lesson)
        self.send("检索负责找资料，生成负责依据资料组织答案。")
        grading = next(payload for schema, payload in self.calls if schema is MasteryEvaluation)
        self.assertIn(reference, grading["reference"])
        self.assertIn(lesson, grading["reference"])

    def test_explicit_inline_check_is_bound_to_the_lesson_and_graded(self):
        base = self.model
        def inline_check(system, user, schema, **kwargs):
            result = base(system, user, schema, **kwargs)
            if schema is ConversationOutput:
                return result.model_copy(update={"message": LESSON + "\n\n---\n\n### 想一想\n\n" + QUESTION,
                                                 "check_question": ""})
            return result
        with patch("agent_service.conversation.parse_model", side_effect=inline_check):
            task = self.start_lesson()
        self.assertEqual(task["context"]["check_question"], QUESTION)
        self.assertEqual(task["context"]["last_lesson"], LESSON)
        self.assertEqual(task["required_action"]["prompt"], QUESTION)
        self.assertEqual(self.state()["messages"][-1]["content"].count(QUESTION), 1)
        self.answer()
        grading = next(payload for schema, payload in self.calls if schema is MasteryEvaluation)
        self.assertEqual(grading["question"], QUESTION)
        self.assertEqual(grading["reference"], LESSON)

    def test_skip_and_continue_do_not_grade_or_verify(self):
        task = self.start_lesson()
        identity = current_step(task)["id"]
        self.decision = intent("skip_check", "continue", workflow="source_learning", scope="continue_goal")
        self.send("先不检查，继续下一节")
        task = self.state()["tasks"][task["task_id"]]
        self.assertNotEqual(current_step(task)["id"], identity)
        self.assertTrue(all(s["understanding"] == "unknown" for s in task["context"]["learning_plan"]["steps"]))
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))

    def test_continue_after_partial_answer_targets_the_next_step_despite_old_question(self):
        task = self.start_lesson()
        self.partial_answer = True
        self.answer()
        calls = []
        base = self.model
        def capture(system, user, schema, **kwargs):
            if schema is ConversationOutput:
                calls.append(json.loads(user))
            return base(system, user, schema, **kwargs)
        self.decision = intent("continue", workflow="source_learning", scope="continue_goal")
        with patch("agent_service.conversation.parse_model", side_effect=capture):
            self.send("继续下一节")
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(calls[-1]["learning_step"]["id"], current_step(after)["id"])
        self.assertEqual(calls[-1]["learning_step"]["title"], "检索与生成的职责")
        self.assertIn("不能因历史检查未答或未通过而留在旧步骤", calls[-1]["instruction"])
        self.assertTrue(all(step["understanding"] == "unknown" for step in after["context"]["learning_plan"]["steps"]))

    def test_plan_format_repair_explains_alignment_and_keeps_one_published_lesson(self):
        for defect in ("missing_overall", "misaligned_conditions"):
            with self.subTest(defect=defect):
                self.sid = str(uuid.uuid4())
                systems = []
                def malformed_once(system, user, schema, **kwargs):
                    if schema is ConversationOutput:
                        systems.append(system)
                        if len(systems) == 1:
                            plan = dict(goal="理解 RAG", steps=["作用", "流程"], success_check="说明整体流程",
                                        step_conditions=["说明资料作用", "说明流程顺序"])
                            if defect == "missing_overall":
                                plan.pop("success_check")
                            else:
                                plan["step_conditions"].pop()
                            try:
                                ConversationOutput.model_validate(dict(message=LESSON, learning_plan=plan))
                            except ValidationError as error:
                                raise ModelCallError("SCHEMA", schema_diagnostic(error)) from None
                    return self.model(system, user, schema, **kwargs)
                with patch("agent_service.conversation.parse_model", side_effect=malformed_once):
                    task = self.start_lesson()
                self.assertEqual(len(systems), 2)
                self.assertIn("两个数组元素数量必须相同", systems[-1])
                self.assertIn("step_conditions 不能替代 success_check", systems[-1])
                self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "coach"]), 1)
                self.assertEqual(task["context"]["understanding"], "unknown")
