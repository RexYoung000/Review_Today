"""A question's answer must never certify an unrelated chapter or old question."""
import copy
import json
import unittest
from unittest.mock import patch

from agent_service.learning_progress import bind_check, bound_check, current_step, set_plan
from agent_service.schemas import ConversationOutput, MasteryEvaluation, CheckBinding
from pydantic import ValidationError
from tests import test_conversation_v2 as fixture
from tests.test_conversation_v2 import intent
from tests import test_teaching_alignment as alignment

LESSON, QUESTION = alignment.LESSON, alignment.QUESTION


class BindingContractTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(task_id="t", content="RAG", context=dict(last_lesson=LESSON, check_question=QUESTION))
        set_plan(self.task, ["为什么需要 RAG", "检索流程"], "理解 RAG", step_conditions=["说明外部资料的作用", "说明流程"])
        self.proposal = dict(step_title="为什么需要 RAG", concepts=["外部资料"], evidence_quotes=[LESSON], scope="concept")

    def test_wrong_step_concepts_or_quotes_do_not_gain_a_binding(self):
        for change in [dict(step_title="检索流程"), dict(concepts=["切块"]), dict(evidence_quotes=["未讲过的知识"])]:
            with self.subTest(change=change):
                self.assertIsNone(bind_check(self.task, QUESTION, dict(self.proposal, **change), ["外部资料"]))
                self.assertIsNone(bound_check(self.task))

    def test_blank_concepts_or_quotes_fail_schema_before_runtime_binding(self):
        for field in ("concepts", "evidence_quotes"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CheckBinding.model_validate(dict(self.proposal, **{field: [" "]}))

    def test_question_reference_plan_changes_invalidate_without_rewriting_history(self):
        for field, change in [("check_question", "另一个问题"), ("last_lesson", "新的讲义")]:
            with self.subTest(field=field):
                task = copy.deepcopy(self.task)
                old = bind_check(task, QUESTION, self.proposal, ["外部资料"])
                task["context"][field] = change
                self.assertIsNone(bound_check(task))
                self.assertEqual(task["context"]["check_binding"], old)
        bind_check(self.task, QUESTION, self.proposal, ["外部资料"])
        set_plan(self.task, ["为什么需要 RAG", "检索流程"], "理解 RAG", step_conditions=["新的能力边界", "说明流程"])
        self.assertIsNone(bound_check(self.task))

    def test_step_scope_without_real_local_condition_is_downgraded(self):
        for step in self.task["context"]["learning_plan"]["steps"]:
            step["completion_condition"] = "理解 RAG"
        value = bind_check(self.task, QUESTION, dict(self.proposal, scope="step"), ["外部资料"])
        self.assertEqual(value["scope"], "concept")

    def test_rendered_emphasis_quotes_bind_without_changing_saved_source(self):
        source = "**字词匹配**：只看字面是否重合。**语义匹配**：看意思是否接近。阈值为 `0.8`，不保证命中。"
        self.task["context"]["last_lesson"] = source
        proposal = dict(self.proposal, evidence_quotes=["字词匹配：只看字面是否重合。", "阈值为 0.8，不保证命中。"])
        self.assertIsNotNone(bind_check(self.task, QUESTION, proposal, ["外部资料"]))
        self.assertEqual(self.task["context"]["last_lesson"], source)
        for changed in ["阈值为 0.9，不保证命中。", "阈值为 0.8，保证命中。", "字词匹配：只看语义是否重合。"]:
            with self.subTest(changed=changed):
                self.assertIsNone(bind_check(self.task, QUESTION, dict(proposal, evidence_quotes=[changed]), ["外部资料"]))


class LearningCheckRegressionTests(unittest.TestCase):
    setUp = alignment.TeachingAlignmentTests.setUp
    tearDown = alignment.TeachingAlignmentTests.tearDown
    send = alignment.TeachingAlignmentTests.send
    state = alignment.TeachingAlignmentTests.state
    model = alignment.TeachingAlignmentTests.model
    start_lesson = alignment.TeachingAlignmentTests.start_lesson
    answer = alignment.TeachingAlignmentTests.answer

    def test_clarifying_question_preserves_binding_step_and_required_action(self):
        task = self.start_lesson()
        context = task["context"]
        binding = copy.deepcopy(context["check_binding"])
        required = copy.deepcopy(task["required_action"])
        calls = []
        base = self.model
        def explain(system, user, schema, **kwargs):
            if issubclass(schema, ConversationOutput):
                calls.append(json.loads(user))
                return ConversationOutput(message="原题问的是新资料怎样帮助回答。\n\n### 想一想\n\n切块应多大？",
                                          check_question="切块应多大？", learning_concepts=["切块"])
            return base(system, user, schema, **kwargs)
        self.decision = intent("followup", workflow="source_learning", scope="continue_goal", clarification_kind="content")
        with patch("agent_service.conversation.parse_model", side_effect=explain):
            self.send("我不理解你的问题")
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(after["context"]["check_binding"], binding)
        self.assertEqual(after["context"]["check_question"], QUESTION)
        self.assertEqual(after["context"]["last_lesson"], LESSON)
        self.assertEqual(after["context"]["learning_plan"], context["learning_plan"])
        self.assertEqual(after["required_action"], required)
        self.assertNotIn("切块应多大", self.state()["messages"][-1]["content"])
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))

    def test_passing_small_question_records_concepts_and_exact_answer_evidence(self):
        task = self.start_lesson()
        self.answer()
        state = self.state()
        after = state["tasks"][task["task_id"]]
        practice = after["context"]["practice"][-1]
        run = state["runs"][practice["run_id"]]
        self.assertEqual(run["evaluated_step_id"], current_step(task)["id"])
        self.assertEqual(run["verified_concepts"], ["外部资料作用"])
        self.assertEqual(run["evaluation_message_id"], practice["message_id"])
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertEqual(after["stage"], "lesson_checked")
        self.assertNotIn("本节其他内容仍未验证", state["messages"][-1]["content"])
        self.assertIsNone(state["draft"])
        self.assertIsNone(state["pending"])

    def test_explicit_whole_step_check_can_complete_only_its_frozen_step(self):
        base = self.model
        def complete_step(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if issubclass(schema, ConversationOutput) and value.check_binding:
                value.check_binding.scope = "step"
            if schema is MasteryEvaluation:
                value.step_completion_demonstrated = True
            return value
        with patch("agent_service.conversation.parse_model", side_effect=complete_step):
            task = self.start_lesson()
            self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "verified")
        self.assertEqual(after["context"]["learning_plan"]["steps"][1]["state"], "pending")
        self.assertNotEqual(after["status"], "completed")

    def test_step_label_alone_does_not_certify_entire_chapter(self):
        base = self.model
        def overclaim(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if issubclass(schema, ConversationOutput) and value.check_binding:
                value.check_binding.scope = "step"
            return value
        with patch("agent_service.conversation.parse_model", side_effect=overclaim):
            task = self.start_lesson()
        self.answer()
        step = current_step(self.state()["tasks"][task["task_id"]])
        self.assertEqual(step["understanding"], "unknown")
        self.assertEqual(step["verified_concepts"][0]["concept"], "外部资料作用")
        self.assertNotIn("这一节的理解检查已通过", self.state()["messages"][-1]["content"])

    def test_first_pass_offers_card_once_without_creating_a_draft(self):
        task = self.start_lesson()
        self.answer()
        first = self.state()["messages"][-1]["content"]
        self.assertNotIn("结束这一段后可确认录入知识卡", first)
        self.assertEqual(len(self.state()['capture_offers']), 1)
        self.assertIsNone(self.state()["draft"])
        self.assertIsNone(self.state()["pending"])
        self.answer()
        self.assertEqual(len(self.state()['capture_offers']), 1)
        after = self.state()["tasks"][task["task_id"]]
        self.assertTrue(after["context"]["knowledge_capture_explained"])
        self.assertNotIn("结束这一段后可确认录入知识卡", self.state()["messages"][-1]["content"])
        self.assertIsNone(self.state()["draft"])
        self.assertIsNone(self.state()["pending"])

    def test_ambiguous_question_is_not_negative_learning_evidence_even_if_model_says_pass(self):
        task = self.start_lesson()
        base = self.model
        def ambiguous(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                return value.model_copy(update={"passed": True, "question_validity": "ambiguous",
                    "feedback": "未指定匹配规则时，你说可能命中其他电池内容是合理的。", "followup_question": "",
                    "followup_binding": None})
            return value
        with patch("agent_service.conversation.parse_model", side_effect=ambiguous):
            self.answer()
        after = self.state()["tasks"][task["task_id"]]
        record = after["context"]["practice"][-1]
        self.assertFalse(record["evaluation"]["passed"])
        self.assertEqual(record["verified_concepts"], [])
        self.assertNotEqual(current_step(after)["understanding"], "verified")
        self.assertIn("不能据此判定你答错", self.state()["messages"][-1]["content"])

    def test_legacy_without_binding_does_not_reuse_current_step_or_previous_pass(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            ctx = data["tasks"][task["task_id"]]["context"]
            del ctx["check_binding"]
            ctx["practice"] = [dict(message_id="older-answer", evaluation=dict(passed=True))]
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        record = after["context"]["practice"][-1]
        run = self.state()["runs"][record["run_id"]]
        self.assertIsNone(run["evaluated_binding"])
        self.assertIsNone(run["evaluated_step_id"])
        self.assertEqual(record["verified_concepts"], [])
        self.assertNotEqual(current_step(after)["understanding"], "verified")
        self.assertIn("尚未核对一致", self.state()["messages"][-1]["content"])


class MasteryDraftCoverageTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    tearDown = fixture.ConversationTests.tearDown
    send = fixture.ConversationTests.send
    state = fixture.ConversationTests.state
    model = fixture.ConversationTests.model

    def test_two_gates_freeze_reference_and_feedback_before_capture_confirmation(self):
        from agent_service.topic_capture import collect_source
        self.decision = intent("question", workflow="problem_solving", scope="learning")
        self.send("RAG 是什么", mode="problem_solving")
        self.decision = intent("answer", workflow="problem_solving", scope="continue_goal")
        self.send("准备工程师面试")
        feedback = ["检索前应考虑资料的访问权限范围。", "找不到可靠材料时应说明证据不足。"]
        base = self.model
        def with_knowledge(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                value.feedback = feedback.pop(0)
            return value
        with patch("agent_service.conversation.parse_model", side_effect=with_knowledge):
            self.send("用户独立作答：先检索再生成")
            first = self.state()["tasks"][self.state()["active_task_id"]]
            self.assertTrue(first["context"]["independent_passed"])
            self.assertFalse(first["context"].get("transfer_passed", False))
            self.assertNotEqual(first["status"], "completed")
            self.assertIsNone(self.state()["draft"])
            self.send("用户迁移作答：没有证据应说明边界")
        state = self.state()
        task = state["tasks"][state["active_task_id"]]
        draft = task["context"]["draft"]["content"]
        self.assertTrue(task["context"]["transfer_passed"])
        self.assertTrue(draft.startswith(task["context"]["reference_answer"]))
        self.assertIn("检索前应考虑资料的访问权限范围。", draft)
        self.assertIn("找不到可靠材料时应说明证据不足。", draft)
        self.assertNotIn("用户独立作答", draft)
        self.assertNotIn("用户迁移作答", draft)
        self.assertEqual(collect_source(self.harness, state, task)["content"], draft)
        task["context"]["practice"][-1]["evaluation"]["feedback"] = "后来被改动的反馈"
        self.assertEqual(collect_source(self.harness, state, task)["content"], draft,
                         "Capture must reuse the delivered draft, not rebuild it after confirmation")
        self.capture.assert_not_called()

    def test_mastery_material_rejects_unbound_foreign_stale_or_invalid_feedback(self):
        from agent_service.learning_progress import mastery_material
        task = dict(task_id="t", content="主题", context=dict(reference_answer="参考基底", check_question="原题"))
        plan = set_plan(task, ["主题"], "理解主题", step_conditions=["说明原理"])
        binding = bind_check(task, "原题", dict(step_title="主题", concepts=["原理"], evidence_quotes=["参考基底"]))
        entry = dict(run_id="r", revision=2, message_id="answer", binding=binding,
                     evaluation=dict(feedback="有效知识补充"), user_answer="用户错答原文")
        task["context"]["practice"] = [entry]
        run = dict(run_id="r", revision=2, status="completed", task_id="t", input_ids=["answer"],
                   evaluated_binding=binding, evaluation_message_id="answer")
        valid = lambda r: not r.get("memory_invalidated")
        self.assertIn("有效知识补充", mastery_material(task, {"r": run}, "current", valid)[0])
        for mutation in [dict(task_id="other"), dict(status="interrupted"), dict(revision=3),
                         dict(evaluated_binding=None), dict(evaluation_message_id="other-answer"),
                         dict(memory_invalidated=True)]:
            with self.subTest(mutation=mutation):
                changed = dict(run, **mutation)
                self.assertEqual(mastery_material(task, {"r": changed}, "current", valid), ("参考基底", []))
        old = copy.deepcopy(task)
        old["context"]["practice"][0]["binding"]["plan_version"] = plan["version"] + 1
        self.assertEqual(mastery_material(old, {"r": run}, "current", valid), ("参考基底", []))


if __name__ == "__main__":
    unittest.main()
