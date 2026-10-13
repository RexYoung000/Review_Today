"""Explicit checks preserve question provenance and never let small quizzes certify a step."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

from agent_service import comprehensive_check
from agent_service.conversation_store import Superseded
from agent_service.learning_progress import (bound_check, current_step, comprehensive_bound,
    completion_requirements, binding_for_model, guard_completion, quote_matches)
from agent_service.schemas import ConversationOutput, MasteryEvaluation, IntentDecision, StepCompletionEvidence, CheckBinding
from tests import test_teaching_alignment as alignment
from tests import test_conversation_v2 as fixture
from tests.test_conversation_v2 import intent


REQUEST = "检查一下我是否掌握这一节"


class ComprehensiveCheckTests(unittest.TestCase):
    tearDown = alignment.TeachingAlignmentTests.tearDown
    send = alignment.TeachingAlignmentTests.send
    state = alignment.TeachingAlignmentTests.state
    start_lesson = alignment.TeachingAlignmentTests.start_lesson
    answer = alignment.TeachingAlignmentTests.answer
    control = fixture.ConversationTests.control

    def setUp(self):
        self.observed = []
        self.claim_whole = False
        self.with_proof = True
        alignment.TeachingAlignmentTests.setUp(self)

    def model(self, system, user, schema, **kwargs):
        self.observed.append((schema, json.loads(user)))
        value = alignment.TeachingAlignmentTests.model(self, system, user, schema, **kwargs)
        if issubclass(schema, ConversationOutput) and value.check_binding:
            value.check_binding.scope = "step"  # Deliberately overclaim every ordinary lesson.
        if schema is MasteryEvaluation:
            value.step_completion_demonstrated = self.claim_whole
            binding = json.loads(user).get("check_binding") or {}
            if self.claim_whole and self.with_proof and binding.get("completion_requirements"):
                value.step_completion_evidence = [StepCompletionEvidence(requirement_index=index,
                    demonstrated=True, answer_quotes=[json.loads(user)["answer"]])
                    for index, _ in enumerate(binding["completion_requirements"])]
        return value

    def request(self, task, text=REQUEST, *, evidence=REQUEST, step_id=None):
        self.decision = intent("question", scope="continue_goal", comprehensive_check=dict(
            step_id=step_id or current_step(task)["id"], evidence=evidence))
        return self.send(text)

    def test_ordinary_pass_and_model_flag_only_record_actual_concepts(self):
        task = self.start_lesson()
        self.claim_whole = True
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(bound_check(after)["scope"], "concept")
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertTrue(current_step(after)["verified_concepts"])
        self.assertFalse(after["context"]["practice"][-1]["evaluation"]["step_completion_demonstrated"])
        self.capture.assert_not_called()

    def test_declared_comprehensive_answer_with_material_label_repairs_before_teaching(self):
        task = self.start_lesson()
        self.request(task)
        self.claim_whole = True
        attempts = []
        base = self.model

        def inconsistent_once(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if schema is IntentDecision:
                attempts.append(system)
                if len(attempts) == 1:
                    value = value.model_copy(update=dict(intents=["goal", "material"],
                        scope="continue_goal", answer_evidence=json.loads(user)["current_inputs"][-1]))
            return value

        self.observed.clear()
        with patch("agent_service.conversation.parse_model", side_effect=inconsistent_once):
            self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(len(attempts), 2)
        self.assertIn("不能误标为 goal/material", attempts[-1])
        self.assertEqual(current_step(after)["understanding"], "verified")
        self.assertEqual(current_step(after)["id"], current_step(task)["id"])
        self.assertEqual([schema for schema, _ in self.observed], [IntentDecision, IntentDecision, MasteryEvaluation])
        self.capture.assert_not_called()

    def test_nonliteral_completion_quote_repairs_without_claiming_user_failure(self):
        task = self.start_lesson()
        self.request(task)
        self.claim_whole = True
        attempts = []
        base = self.model

        def paraphrase_once(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                attempts.append(system)
                if len(attempts) == 1:
                    value.step_completion_evidence[0].answer_quotes = ["我改写拼接的答案依据"]
            return value

        with patch("agent_service.conversation.parse_model", side_effect=paraphrase_once):
            self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(len(attempts), 2)
        self.assertIn("不能拼接分散句子", attempts[-1])
        self.assertEqual(current_step(after)["understanding"], "verified")
        self.assertTrue(after["context"]["practice"][-1]["evaluation"]["passed"])

    def test_request_publishes_full_condition_with_no_coach_or_new_verification_call(self):
        task = self.start_lesson()
        old_context = copy.deepcopy(task["context"])
        old_messages = copy.deepcopy(self.state()["messages"])
        self.observed.clear()
        result = self.request(task)
        state = self.state()
        after = state["tasks"][task["task_id"]]
        binding = bound_check(after)
        self.assertTrue(comprehensive_bound(binding))
        self.assertIn(current_step(after)["completion_condition"], binding["question"])
        self.assertEqual(binding["request_message_id"], result.message_id)
        self.assertEqual(binding["request_run_id"], result.run_id)
        self.assertEqual(binding["request_evidence"], REQUEST)
        self.assertEqual(after["required_action"]["prompt"], binding["question"])
        self.assertEqual(state["messages"][:-2], old_messages)
        for field in ("last_lesson", "lesson_index", "understanding"):
            self.assertEqual(after["context"][field], old_context[field])
        self.assertEqual(current_step(after)["id"], current_step(task)["id"])
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertEqual([schema for schema, _ in self.observed], [IntentDecision])
        self.assertIn("本节综合检查", state["messages"][-1]["content"])
        self.assertIsNone(state["draft"])
        self.assertIsNone(state["pending"])
        self.capture.assert_not_called()

    def test_explicit_comprehensive_full_pass_can_verify_only_current_step(self):
        task = self.start_lesson()
        self.request(task)
        self.claim_whole = True
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "verified")
        self.assertEqual(after["context"]["learning_plan"]["steps"][1]["understanding"], "unknown")
        self.assertEqual(after["context"]["understanding"], "unknown")
        self.assertIsNone(self.state()["draft"])

    def test_pass_without_full_ability_proof_never_certifies_entire_step(self):
        task = self.start_lesson()
        self.request(task)
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertFalse(current_step(after).get("verified_concepts"))

    def test_whole_flag_without_itemized_learner_evidence_cannot_pass(self):
        task = self.start_lesson()
        self.request(task)
        self.claim_whole = True
        self.with_proof = False
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertFalse(after["context"]["practice"][-1]["evaluation"]["passed"])

    def test_literal_subrequirements_are_frozen_and_examples_not_made_mandatory(self):
        condition = "说明模型限制（训练时间边界、私有资料缺失、可能编造），并指出外部资料的作用。"
        self.assertEqual(completion_requirements(condition), [condition, "训练时间边界", "私有资料缺失", "可能编造"])
        example = "能举例说明外部资料（例如内部说明、个人笔记）的作用。"
        self.assertEqual(completion_requirements(example), [example])

    def test_missing_duplicate_negative_and_fabricated_answer_evidence_do_not_pass(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            current_step(data["tasks"][task["task_id"]])["completion_condition"] = "说明限制（时间边界、私有资料），再说明外部资料作用。"
        self.request(self.state()["tasks"][task["task_id"]])
        binding = bound_check(self.state()["tasks"][task["task_id"]])
        answer = "模型有时间边界，私有资料通常没有学到，外部资料能补充这些缺口。"
        valid = [dict(requirement_index=i, demonstrated=True, answer_quotes=[answer]) for i in range(3)]
        invalid = [valid[:-1], [valid[0], valid[0], valid[2]],
                   [valid[0], dict(valid[1], demonstrated=False), valid[2]],
                   [valid[0], dict(valid[1], answer_quotes=["我编造的答案依据"]), valid[2]]]
        for rows in invalid:
            with self.subTest(rows=rows):
                value = MasteryEvaluation(passed=True, correctness="核心正确", completeness="完整",
                    expression="清楚", transfer="待验证", feedback="通过", step_completion_demonstrated=True,
                    step_completion_evidence=rows, capture_feedback_quotes=["通过"], capture_scope_summary="旧反馈范围")
                guard_completion(value, binding, answer)
                self.assertFalse(value.passed)
                self.assertFalse(value.step_completion_demonstrated)
                self.assertFalse(value.capture_feedback_quotes)
                self.assertFalse(value.capture_scope_summary)

    def test_model_quote_projection_preserves_raw_source_and_saved_binding(self):
        source = "外部资料提供**可追溯的依据**，`RAG` 不保证正确。"
        original = dict(evidence_quotes=["外部资料提供可追溯的依据，RAG 不保证正确。"])
        before = copy.deepcopy(original)
        projected = binding_for_model(original, source)
        self.assertEqual(original, before)
        self.assertTrue(all(q in source for q in projected["evidence_quotes"]))
        self.assertEqual(projected["evidence_quotes"], [source])
        self.assertTrue(quote_matches("提供**可追溯的依据", source))
        self.assertFalse(quote_matches("提供可靠的依据", source))
        from agent_service.knowledge_invitation import validate_update
        validate_update(dict(offer_id="offer", version=1, retained_fragment_ids=[],
            evidence_quotes=["提供**可追溯的依据"]), source, [dict(id="offer", version=1, fragments=[])])
        self.assertIsNone(binding_for_model(None, source))

    def test_invalid_followup_after_comprehensive_retains_feedback_without_new_question(self):
        task = self.start_lesson()
        self.request(task)
        self.partial_answer = True
        base = self.model

        def invalid(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                value.followup_question = "无讲义依据的新题？"
                value.followup_binding = CheckBinding(step_title="不存在的步骤", concepts=["未教知识"],
                    evidence_quotes=["虚构的讲义"], scope="concept")
            return value

        with patch("agent_service.conversation.parse_model", side_effect=invalid):
            self.answer()
        state = self.state()
        last_run = list(state["runs"].values())[-1]
        self.assertEqual(last_run["status"], "completed")
        self.assertIn("还缺少", state["messages"][-1]["content"])
        self.assertIn("重新请求本节综合检查", state["messages"][-1]["content"])
        self.assertNotIn("无讲义依据的新题", state["messages"][-1]["content"])
        after = state["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertFalse(after["context"]["check_question"])
        self.assertIsNone(bound_check(after))
        self.assertFalse(after["context"]["practice"][-1]["evaluation"]["passed"])
        self.request(after)
        resumed = self.state()["tasks"][task["task_id"]]
        self.assertTrue(comprehensive_bound(bound_check(resumed)))
        self.assertEqual(current_step(resumed)["understanding"], "unknown")

    def test_failed_comprehensive_and_followup_do_not_inherit_whole_step_scope(self):
        task = self.start_lesson()
        self.request(task)
        self.partial_answer = True
        self.claim_whole = True
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertEqual(bound_check(after)["scope"], "concept")
        self.assertFalse(comprehensive_bound(bound_check(after)))

    def test_hint_prevents_independent_comprehensive_pass(self):
        task = self.start_lesson()
        self.request(task)
        self.decision = intent("hint", workflow="source_learning", scope="continue_goal")
        self.send("给我一点提示")
        self.claim_whole = True
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(current_step(after)["understanding"], "unknown")
        self.assertTrue(after["context"]["practice"][-1]["hint_used"])
        self.assertFalse(after["context"]["practice"][-1]["evaluation"]["step_completion_demonstrated"])

    def test_quoted_negated_and_wrong_object_requests_keep_original_check(self):
        task = self.start_lesson()
        question = task["context"]["check_question"]
        for text, evidence, step_id in [
            ('引用：“' + REQUEST + '”', REQUEST, None),
            ('不要' + REQUEST, '不要' + REQUEST, None),
            ('不要' + REQUEST, REQUEST, None),
            ('如果需要，' + REQUEST, REQUEST, None),
            (REQUEST + '，先不要做', REQUEST, None),
            ('> ' + REQUEST, REQUEST, None),
            (REQUEST, REQUEST, 'not-the-current-step'),
        ]:
            with self.subTest(text=text, step=step_id):
                self.request(task, text, evidence=evidence, step_id=step_id)
                after = self.state()["tasks"][task["task_id"]]
                self.assertEqual(after["context"]["check_question"], question)
                self.assertEqual(bound_check(after)["scope"], "concept")
        self.capture.assert_not_called()

    def test_missing_actual_condition_is_not_invented(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            current_step(data["tasks"][task["task_id"]])["completion_condition"] = ""
        self.request(task)
        self.assertNotIn("本节综合检查", self.state()["messages"][-1]["content"])
        self.assertIn("缺少", self.state()["messages"][-1]["content"])
        self.assertEqual(self.state()["tasks"][task["task_id"]]["context"]["check_question"], task["context"]["check_question"])

    def test_continue_and_skip_keep_unverified_step_and_allow_next_lesson(self):
        for action in ("continue", "skip_check"):
            with self.subTest(action=action):
                self.sid = str(uuid.uuid4())
                task = self.start_lesson()
                self.request(task)
                first = current_step(task)["id"]
                self.decision = intent(action, workflow="source_learning", scope="continue_goal")
                self.send("继续下一节" if action == "continue" else "跳过检查继续")
                after = self.state()["tasks"][task["task_id"]]
                self.assertNotEqual(current_step(after)["id"], first)
                old = next(s for s in after["context"]["learning_plan"]["steps"] if s["id"] == first)
                self.assertEqual(old["understanding"], "unknown")

    def test_legacy_step_binding_projects_as_concept_without_rewriting_saved_binding(self):
        task = self.start_lesson()
        with self.store.transaction(self.sid) as data:
            binding = data["tasks"][task["task_id"]]["context"]["check_binding"]
            binding.update(scope="step", completion_condition=current_step(task)["completion_condition"])
            binding.pop("check_kind", None)
            binding.pop("scope_policy", None)
        original = copy.deepcopy(self.state()["tasks"][task["task_id"]]["context"]["check_binding"])
        self.claim_whole = True
        self.answer()
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(after["context"]["check_binding"], original)
        self.assertEqual(bound_check(after)["scope"], "concept")
        self.assertEqual(current_step(after)["understanding"], "unknown")

    def prepare_direct(self, task):
        accepted = self.send(REQUEST, drain=False)
        with self.store.transaction(self.sid) as data:
            run = data["runs"][accepted.run_id]
            run.update(status="running", task_id=task["task_id"])
            data["foreground"] = accepted.run_id
        data = self.state()
        run = data["runs"][accepted.run_id]
        prepared = comprehensive_check.prepare(data, run, dict(step_id=current_step(task)["id"], evidence=REQUEST))
        return accepted, run["revision"], prepared

    def test_stop_between_prepare_and_publication_has_no_binding_or_question_write(self):
        task = self.start_lesson()
        accepted, revision, prepared = self.prepare_direct(task)
        self.control(accepted.run_id, "stop")
        before = copy.deepcopy(self.state()["tasks"][task["task_id"]]["context"])
        with self.assertRaises(Superseded):
            self.harness._publish(self.sid, accepted.run_id, revision, "", comprehensive=prepared)
        self.assertEqual(self.state()["tasks"][task["task_id"]]["context"], before)

    def test_changed_reference_before_publication_rolls_back_comprehensive_update(self):
        task = self.start_lesson()
        accepted, revision, prepared = self.prepare_direct(task)
        with self.store.transaction(self.sid) as data:
            data["tasks"][task["task_id"]]["context"]["last_lesson"] += "新纠正。"
        before = copy.deepcopy(self.state())
        with self.assertRaisesRegex(RuntimeError, "STALE_CONTEXT"):
            self.harness._publish(self.sid, accepted.run_id, revision, "", comprehensive=prepared)
        after = self.state()
        self.assertEqual(after["tasks"][task["task_id"]]["context"], before["tasks"][task["task_id"]]["context"])
        self.assertEqual(after["messages"], before["messages"])

    def test_problem_solving_keeps_original_independent_and_transfer_gates(self):
        self.decision = intent("goal", workflow="problem_solving", direct_teaching=True)
        self.send("我要攻克 RAG 面试题", mode="problem_solving")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        old = copy.deepcopy(task["context"])
        self.request(task)
        after = self.state()["tasks"][task["task_id"]]
        self.assertEqual(after["context"], old)
        self.assertTrue(after["context"]["requires_mastery"])
        self.assertIn("迁移追问", self.state()["messages"][-1]["content"])

    def test_control_request_does_not_start_comprehensive_check(self):
        task = self.start_lesson()
        old_binding = copy.deepcopy(task["context"]["check_binding"])
        self.decision = intent("pause", scope="continue_goal", comprehensive_check=dict(
            step_id=current_step(task)["id"], evidence="暂停"))
        self.send("暂停")
        after = self.state()
        self.assertTrue(after["paused"])
        self.assertEqual(after["tasks"][task["task_id"]]["context"]["check_binding"], old_binding)
        self.assertNotIn("本节综合检查", after["messages"][-1]["content"])


class ExperimentComprehensiveTests(unittest.TestCase):
    def setUp(self):
        from tests import test_judgment_harness as experimental
        from agent_service.learning_progress import set_plan
        self.f = experimental.HarnessJudgmentTests("test_disabled_uses_unchanged_schema_and_no_jev")
        self.f.setUp()
        self.f.enable()
        self.f.labels["intent"] = "goal"
        self.f.decision = intent("goal", workflow="source_learning", direct_teaching=True)
        self.f.send("直接教我 RAG", mode="source_learning")
        data = self.f.state()
        self.task_id = data["active_task_id"]
        with self.f.store.transaction(self.f.sid) as current:
            task = current["tasks"][self.task_id]
            step = current_step(task)
            set_plan(task, [step["title"]], "说明 RAG 的作用", step_ids=[step["id"]],
                     step_conditions=["说明检索资料与生成回答的关系"])
        self.task = self.f.state()["tasks"][self.task_id]

    def tearDown(self):
        self.f.tearDown()

    def request(self):
        self.f.labels["intent"] = "question"
        self.f.decision = intent("question", scope="continue_goal", comprehensive_check=dict(
            step_id=current_step(self.task)["id"], evidence=REQUEST))
        return self.f.send(REQUEST)

    def test_existing_quality_gate_and_bound_standard_are_kept(self):
        accepted = self.request()
        state = self.f.state()
        self.assertEqual(state["runs"][accepted.run_id]["status"], "completed")
        self.assertTrue(state["runs"][accepted.run_id]["quality_checks"])
        self.assertTrue(all(row["passed"] for row in state["runs"][accepted.run_id]["quality_checks"]))
        task = state["tasks"][self.task_id]
        self.assertTrue(comprehensive_bound(bound_check(task)))
        self.assertEqual(task["context"]["check_standard"]["question"], task["context"]["check_question"])

    def test_quality_failure_keeps_old_question_and_binding(self):
        old = copy.deepcopy(self.f.state()["tasks"][self.task_id]["context"])
        with patch("agent_service.judgment_quality.checked_question", side_effect=RuntimeError("RT.QUESTION.QUALITY_UNRESOLVED")):
            accepted = self.request()
        after = self.f.state()
        self.assertEqual(after["runs"][accepted.run_id]["status"], "retryable_failed")
        context = copy.deepcopy(after["tasks"][self.task_id]["context"])
        self.assertEqual(context.pop("latest_run_id"), accepted.run_id)
        old.pop("latest_run_id", None)
        self.assertEqual(context, old)

    def test_experimental_evaluation_receives_real_comprehensive_binding(self):
        from agent_service.judgment_grading import JudgmentFeedback
        self.request()
        observed = []
        base = self.f.model

        def complete(system, user, schema, **kwargs):
            value = base(system, user, schema, **kwargs)
            if schema is JudgmentFeedback:
                payload = json.loads(user)
                observed.append(payload)
                value.step_completion_demonstrated = True
                value.step_completion_evidence = [StepCompletionEvidence(requirement_index=i,
                    demonstrated=True, answer_quotes=[payload["answer"]])
                    for i, _ in enumerate(payload["check_binding"]["completion_requirements"])]
            return value

        self.f.decision = intent("answer", workflow="source_learning", scope="continue_goal")
        with patch("agent_service.conversation.parse_model", side_effect=complete):
            self.f.send("先检索资料，再用于生成回答。")
        self.assertEqual(len(observed), 1)
        self.assertTrue(comprehensive_bound(observed[0]["check_binding"]))
        self.assertIn(observed[0]["check_binding"]["completion_condition"], observed[0]["question"])
        self.assertEqual(current_step(self.f.state()["tasks"][self.task_id])["understanding"], "verified")
