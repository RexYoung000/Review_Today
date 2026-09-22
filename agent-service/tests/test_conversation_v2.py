from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from tests.test_m1_capture_contract import committing_result

from agent_service.conversation import ConversationHarness, LABELS
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore
from agent_service.schemas import (ConversationOutput, IntentDecision, MasteryEvaluation, ProblemCoachBundle,
                                   RunActionRequest, SessionMessageRequest, IntentOperation, ConversationSummary, JDAnalysis, SourceCandidate)


def intent(*names, workflow=None, scope=None, **kw):
    if scope is None:
        scope = "learning" if "goal" in names else "conversation"
    return IntentDecision(intents=list(names), workflow=workflow, scope=scope, relation="continuation", rationale="受控测试意图", **kw)


def bundle():
    return ProblemCoachBundle.model_validate(dict(
        analysis=dict(question="RAG 是什么", question_type="concept", calibration_question="你主要准备哪类面试？"),
        answer=dict(direct_answer="先检索相关资料，再基于上下文生成回答。", confidence="high"),
        gap_map=dict(related_knowledge=["检索", "生成"], learning_order=["先检索再生成"]),
        learning_plan=dict(goal="理解 RAG", steps=["理解检索", "理解生成"], success_check="独立回答")))


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks = HarnessStore(str(Path(self.tmp.name) / "test.sqlite3"))
        self.store = ConversationStore(self.tasks)
        self.harness = ConversationHarness(self.store)
        self.sid = str(uuid.uuid4())
        self.decision = intent("greeting")
        self.calls = []
        self.model_patch = patch("agent_service.conversation.parse_model", side_effect=self.model)
        self.model_patch.start()
        self.capture_patch = patch("agent_service.conversation.run_capture")
        self.capture = self.capture_patch.start()
        self.web_patch = patch("agent_service.conversation.web_search_capability", return_value={"status": "unverified", "provider": "test"})
        self.web_patch.start()

    def tearDown(self):
        self.model_patch.stop()
        self.capture_patch.stop()
        self.web_patch.stop()
        self.tmp.cleanup()

    def model(self, system, user, schema, **kwargs):
        self.calls.append((schema, json.loads(user) if user.startswith("{") else user))
        from agent_service.schemas import TeachingPreparation, MemoryChoice, SourceList, EvidenceAssessmentV2
        from agent_service.goal_continuation import ContinuationRequest
        from agent_service.scope_reply import ScopeReply
        if schema is ScopeReply:
            programming = json.loads(user)['boundary']['domain'] == 'programming'
            return ScopeReply(message='这项开发交付我不能直接替你完成。' if programming else '这项资源获取或代办操作我不能替你完成。')
        if schema is ContinuationRequest:
            text = json.loads(user)["request"]
            return ContinuationRequest(evidence=text if text.startswith("继续") else "", topic="")
        if schema is TeachingPreparation:
            return TeachingPreparation(concepts=["RAG"] if self.decision.public_search_query else [], public_query=self.decision.public_search_query)
        if schema is MemoryChoice:
            return MemoryChoice()
        if schema is SourceList:
            return SourceList()
        if schema is EvidenceAssessmentV2:
            return EvidenceAssessmentV2(state="insufficient", summary="部分内容尚待核实。")
        if schema is IntentDecision:
            current = json.loads(user).get("current_inputs", []) if user.startswith("{") else []
            return self.decision.model_copy(update={"answer_evidence": current[-1] if current and "answer" in self.decision.intents else ""})
        if schema is ProblemCoachBundle:
            return bundle()
        if schema is MasteryEvaluation:
            return MasteryEvaluation(passed=True, correctness="正确", completeness="完整", expression="清楚",
                                     transfer="待验证", feedback="本次回答核心正确", followup_question="换一个场景有哪些局限？")
        if schema is ConversationSummary:
            return ConversationSummary(goal="RAG", confirmed_decisions=[], open_questions=["原理"], summary="当前主题是 RAG。")
        if schema is JDAnalysis:
            return JDAnalysis(role_goal="RAG 工程师", competency_map=["检索"], risk_points=["无项目经验"], prioritized_questions=["RAG 是什么？", "如何评估检索？"])
        return ConversationOutput(message="这是本轮真实回答。", check_question="请用自己的话说明原理。")

    def send(self, text="你好", *, mode="auto", delivery="steer", sid=None, drain=True, operation=None):
        body = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text, mode_preset=mode,
                                     delivery=delivery, operation=operation)
        result = self.harness.accept(sid or self.sid, body)
        if drain:
            self.harness.drain(sid or self.sid)
        return result

    def state(self):
        return self.store.get(self.sid)

    def control(self, run_id, action, mode=None):
        return self.harness.action(run_id, RunActionRequest(action_id=str(uuid.uuid4()), action=action, mode=mode))

    def test_every_mode_accepts_greeting_without_task_or_material(self):
        for mode in LABELS:
            sid = str(uuid.uuid4())
            self.send(mode=mode, sid=sid)
            data = self.store.get(sid)
            self.assertEqual(data["tasks"], {})
            self.assertEqual(len([m for m in data["messages"] if m["role"] == "coach"]), 1)
            self.assertEqual(data["mode"], mode)
            run = next(iter(data["runs"].values()))
            self.assertIsNone(run["activity_kind"])
            self.assertIsNone(run["completed_at"])
        self.capture.assert_not_called()

    def test_memory_policy_fences_pending_and_late_output_without_empty_sessions(self):
        origin = str(uuid.uuid4())
        self.harness.memory_policy(origin, allowed=True, policy_version=0, content_version=0)
        self.assertIsNone(self.store.get(origin), "syncing memory policy does not create an empty Session")
        candidate = dict(id="old-lesson", session_id=origin, policy_version=0, content_version=0,
                         concept="检索", excerpt="索引使查找更有效率", kind="explained")
        self.decision = intent("question", memory_selections=[dict(id="old-lesson", relation="analogy")])
        request = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="RAG 如何检索", context={"memory_candidates": [candidate]})
        accepted = self.harness.accept(self.sid, request)
        self.harness.drain(self.sid)
        run = self.state()["runs"][accepted.run_id]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["memory_references"][0]["kind"], "explained")
        with self.store.transaction(self.sid) as data:
            data["runs"][accepted.run_id]["status"] = "running"
            data["pending"] = {"kind": "save"}
            data["draft"] = {"memory_references": [candidate]}
        self.harness.memory_policy(origin, allowed=False, policy_version=1, content_version=0)
        self.assertIsNone(self.state()["pending"])
        self.assertTrue(self.state()["draft"]["invalidated"])
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "interrupted")
        self.assertFalse(self.store.memory_valid([candidate]))
        self.harness.memory_policy(origin, allowed=True, policy_version=2, content_version=0)
        self.assertFalse(self.store.memory_valid([candidate]), "restoring permission cannot revive old versions")
        with self.assertRaisesRegex(ValueError, "VERSION_CONFLICT"):
            self.harness.memory_policy(origin, allowed=True, policy_version=0, content_version=0)

    def test_thinking_preference_persists_and_control_id_conflicts(self):
        body = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="你好", thinking_strength="deep")
        accepted = self.harness.accept(self.sid, body)
        self.harness.drain(self.sid)
        self.assertEqual(self.state()["thinking_strength"], "deep")
        self.send("再问一次")
        self.assertEqual(self.state()["thinking_strength"], "deep", "default next-turn fields cannot reset explicit choice")
        action = RunActionRequest(action_id=str(uuid.uuid4()), action="set_thinking", thinking_strength="smart")
        self.harness.action(accepted.run_id, action)
        self.harness.action(accepted.run_id, action)
        self.assertEqual(self.state()["thinking_strength"], "smart")
        with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_CONFLICT"):
            self.harness.action(accepted.run_id, action.model_copy(update={"thinking_strength": "deep"}))

    def test_memory_dependencies_survive_followup_and_exclusion_removes_model_context(self):
        origin = str(uuid.uuid4())
        self.harness.memory_policy(origin, allowed=True, policy_version=0, content_version=0)
        candidate = dict(id="prior", session_id=origin, policy_version=0, content_version=0, kind="explained",
                         concept="检索", excerpt="旧关联内容")
        self.decision = intent("question", memory_selections=[dict(id="prior", relation="analogy")])
        first = self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="RAG 是什么", context={"memory_candidates": [candidate]}))
        self.harness.drain(self.sid)
        self.decision = intent("followup")
        second = self.send("再举例")
        self.assertEqual(self.state()["runs"][second.run_id]["memory_references"][0]["id"], "prior")
        self.harness.memory_policy(origin, allowed=False, policy_version=1, content_version=0)
        self.calls.clear()
        self.decision = intent("question")
        third = self.send("另一个基础问题")
        self.assertEqual(self.state()["runs"][third.run_id]["status"], "completed")
        routing = next(value for schema, value in self.calls if schema is IntentDecision)
        self.assertNotIn("这是本轮真实回答", json.dumps(routing, ensure_ascii=False))
        self.assertNotIn("related_learning", routing)
        self.assertTrue(any(m.get("run_id") == first.run_id for m in self.state()["messages"]), "history remains")

    def test_stale_memory_candidate_cannot_create_authority_or_strand_run(self):
        candidate = dict(id="missing", session_id=str(uuid.uuid4()), policy_version=0, content_version=0,
                         kind="explained", excerpt="不应进入模型")
        self.decision = intent("question", memory_selections=[dict(id="missing", relation="analogy")])
        result = self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="RAG 是什么", context={"memory_candidates": [candidate]}))
        self.harness.drain(self.sid)
        self.assertEqual(self.state()["runs"][result.run_id]["status"], "completed")
        self.assertEqual(self.state()["runs"][result.run_id]["memory_references"], [])
        self.assertIsNone(self.store.memory_policy(candidate["session_id"]))
        self.assertNotIn("不应进入模型", json.dumps(self.calls[0][1], ensure_ascii=False))

    def test_ordinary_answer_does_not_create_fake_material_or_goal(self):
        self.decision = intent("question", answer_only=True)
        self.send("RAG 是什么")
        self.assertEqual(self.state()["tasks"], {})
        self.assertFalse(any(e.get("payload", {}).get("sources") for e in self.state()["events"]))

    def test_mac_card_version_invalidation_filters_historical_context(self):
        self.decision = intent("question")
        first = self.send("旧问题")
        self.calls.clear()
        second = self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="新的问题",
            context={"invalid_memory_run_ids": [first.run_id], "summary": "失效摘要"}))
        self.harness.drain(self.sid)
        self.assertEqual(self.state()["runs"][second.run_id]["status"], "completed")
        routing = next(value for schema, value in self.calls if schema is IntentDecision)
        self.assertEqual(routing["summary"], "")
        self.assertEqual(routing["recent_messages"], [])
        with self.store.transaction(self.sid) as data:
            data["pending"] = {"kind": "save", "target_id": "fresh-version", "version": 1}
        self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="暂时不要确认",
            context={"invalid_memory_run_ids": [first.run_id]}))
        self.assertEqual(self.state()["pending"]["target_id"], "fresh-version", "replaying an old exclusion cannot clear a new decision")

    def test_schema_repair_is_bounded_and_preserves_deep_strength(self):
        from agent_service.openai_client import ModelCallError
        from agent_service.execution_policy import current_budget
        calls = []
        def malformed_once(system, user, schema, **kwargs):
            current_budget.get().take()
            calls.append(kwargs)
            if len(calls) == 1:
                raise ModelCallError("SCHEMA", "ValidationError")
            return intent("greeting", light_reply="你好")
        with patch("agent_service.conversation.parse_model", side_effect=malformed_once):
            result = self.harness.accept(self.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="你好", thinking_strength="deep"))
            self.harness.drain(self.sid)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c["reasoning_effort"] == "high" for c in calls))
        self.assertEqual(self.state()["runs"][result.run_id]["status"], "completed")

    def test_approved_fallback_shares_budget_but_access_denial_never_switches(self):
        from agent_service.openai_client import ModelCallError
        from agent_service.execution_policy import current_budget
        for error, expected_calls, status in [(ModelCallError("CONNECTION"), 2, "completed"),
                                               (ModelCallError("PROVIDER", "HTTP 403"), 1, "retryable_failed")]:
            calls = []
            def alternate(system, prompt, schema, **kwargs):
                current_budget.get().take()
                calls.append(kwargs)
                if len(calls) == 1:
                    raise error
                return intent("greeting", light_reply="你好")
            sid = str(uuid.uuid4())
            with patch("agent_service.conversation.alternatives", return_value=["approved-fixture"]), \
                 patch("agent_service.conversation.require_model"), \
                 patch("agent_service.conversation.parse_model", side_effect=alternate):
                self.send(sid=sid)
            self.assertEqual(len(calls), expected_calls)
            run = next(iter(self.store.get(sid)["runs"].values()))
            self.assertEqual(run["status"], status)
            if expected_calls == 2:
                self.assertEqual(calls[-1]["model"], "approved-fixture")

    def test_failed_memory_generation_is_retryable_not_false_evidence_conflict(self):
        self.decision = intent("material", workflow="memory_organization", scope="organize")
        self.send("知识资料")
        self.decision = intent("self_report", understanding="self_reported")
        self.send("我理解了")
        draft = self.state()["draft"]
        self.decision = intent("confirm", proposed_actions=[IntentOperation(kind="save", target_id=draft["id"], version=draft["version"], disposition="confirm", evidence="请保存")])
        self.capture.return_value = {"outcome": "retryable_failed", "error_code": "RT.CAPTURE.RISK_CHECK_FAILED"}
        result = self.send("请保存")
        self.assertEqual(self.state()["runs"][result.run_id]["status"], "retryable_failed")
        self.assertFalse(any(t["stage"] == "knowledge_conflict" for t in self.state()["tasks"].values()))
        self.assertTrue(self.capture.call_args.kwargs["confirmed_content"])
        self.assertTrue(callable(self.capture.call_args.kwargs["model_runner"]))

    def test_hint_answer_is_not_independent_verification(self):
        self.decision = intent("question", workflow="problem_solving")
        self.send("RAG 是什么", mode="problem_solving")
        self.decision = intent("hint")
        self.send("给我一点提示")
        with self.store.transaction(self.sid) as data:
            task = next(iter(data["tasks"].values()))
            task["stage"] = "practice"
            task["context"]["check_question"] = "解释 RAG"
        self.decision = intent("answer")
        self.send("先检索再生成")
        task = next(iter(self.state()["tasks"].values()))
        self.assertFalse(task["context"]["practice"][-1]["evaluation"]["passed"])
        self.assertTrue(task["context"]["practice"][-1]["hint_used"])
        self.assertFalse(task["context"].get("transfer_passed"))

    def test_auto_question_is_answer_only_but_problem_preset_starts_goal(self):
        self.decision = intent("question", workflow="problem_solving")
        self.send("RAG 是什么")
        self.assertFalse(self.state()["tasks"])
        run = next(iter(self.state()["runs"].values()))
        self.assertEqual(run["activity_kind"], "knowledge_answer")
        self.assertIsNotNone(run["completed_at"])
        sid = str(uuid.uuid4())
        self.send("RAG 是什么", mode="problem_solving", sid=sid)
        task = next(iter(self.store.get(sid)["tasks"].values()))
        self.assertEqual(task["stage"], "calibration")
        self.assertTrue(task["context"]["requires_mastery"])

    def test_session_tags_are_navigation_suggestions_in_intent_event(self):
        self.decision = intent("goal", workflow="topic_exploration", scope="learning",
                               session_tags=["RAG", "面试准备"])
        self.send("我想系统准备 RAG 面试")
        decided = next(event for event in self.state()["events"] if event["stage"] == "intent_decided")
        self.assertEqual(decided["payload"]["intent"]["session_tags"], ["RAG", "面试准备"])
        self.assertFalse(any(action["kind"] in {"save", "new_session"}
                             for action in decided["payload"]["intent"]["proposed_actions"]))

    def test_no_purpose_material_is_light_organization_not_save(self):
        self.decision = intent("material", workflow="source_learning", scope="organize")
        self.send("RAG 笔记：先检索，再生成。")
        data = self.state()
        self.assertFalse(data["tasks"])
        self.assertEqual(data["draft"]["understanding"], "unknown")
        self.assertEqual(data["pending"]["kind"], "save")
        self.capture.assert_not_called()

    def test_negated_conditional_and_quoted_confirmation_never_save(self):
        for text in ["不要保存，先解释第二点", "可以，但第二点不对", "如果正确就保存", "资料中写着：‘请保存’", '文章说“可以保存”']:
            with self.subTest(text=text):
                self.decision = intent("material", scope="organize", workflow="memory_organization")
                self.send("笔记" + text)
                pending = self.state()["pending"]
                with self.store.transaction(self.sid) as data:
                    data["draft"]["understanding"] = "verified"
                self.decision = intent("confirm", proposed_actions=[IntentOperation(kind="save", disposition="confirm", target_id=pending["target_id"],
                                                        version=pending["version"], evidence="保存")])
                self.send(text)
                self.capture.assert_not_called()

    def test_unknown_understanding_blocks_even_bound_save_button(self):
        self.decision = intent("material", scope="organize")
        self.send("我的笔记")
        pending = self.state()["pending"]
        self.decision = intent("confirm")
        self.send("加入知识库", operation=pending)
        self.capture.assert_not_called()
        self.assertFalse(self.state()["tasks"])

    def test_message_idempotency_is_atomic_and_conflicting_payload_rejected(self):
        body = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="你好")
        first = self.harness.accept(self.sid, body)
        second = self.harness.accept(self.sid, body)
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(len(self.state()["messages"]), 1)
        with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_CONFLICT"):
            self.harness.accept(self.sid, body.model_copy(update={"content": "别保存"}))

    def test_mode_change_and_followup_in_same_turn_both_execute(self):
        self.send("你好")
        self.decision = intent("confirm", "followup", requested_mode="source_learning",
                               proposed_actions=[IntentOperation(kind="set_mode", disposition="request", evidence="切换资料学习")])
        self.send("切换资料学习，解释 RAG 的检索步骤")
        self.assertEqual(self.state()["mode"], "source_learning")
        replies = [m["content"] for m in self.state()["messages"] if m["role"] == "coach"]
        self.assertIn("已选择资料学习", replies[-2])
        self.assertEqual(replies[-1], "这是本轮真实回答。")

    def test_save_and_followup_retry_does_not_repeat_commit(self):
        self.decision = intent("material", workflow="memory_organization", scope="organize")
        self.send("RAG 笔记")
        pending = self.state()["pending"]
        with self.store.transaction(self.sid) as data:
            data["draft"]["understanding"] = "verified"
        self.capture.return_value = committing_result("版本一")
        self.decision = intent("confirm", "followup", proposed_actions=[IntentOperation(kind="save", disposition="confirm",
                               target_id=pending["target_id"], version=pending["version"], evidence="保存这版")])
        def fail_answer(system, user, schema, **kwargs):
            if schema is ConversationOutput:
                from agent_service.openai_client import ModelCallError
                raise ModelCallError("TIMEOUT")
            return self.model(system, user, schema, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=fail_answer):
            accepted = self.send("保存这版，解释第二点")
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "retryable_failed")
        self.control(accepted.run_id, "retry")
        self.harness.drain(self.sid)
        self.capture.assert_called_once()
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "completed")

    def test_natural_queue_moves_idempotency_receipt_with_message(self):
        self.send("解释 RAG", drain=False)
        later = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="稍后解释检索")
        accepted = self.harness.accept(self.sid, later)
        self.decision = intent("queue", "question", answer_only=True)
        self.harness.drain(self.sid)
        resent = self.harness.accept(self.sid, later)
        self.assertNotEqual(accepted.run_id, resent.run_id)
        self.assertEqual(self.state()["runs"][resent.run_id]["input_ids"], [later.client_message_id])

    def test_url_embedded_save_text_is_not_authorization(self):
        self.assertFalse(self.harness._explicit({"evidence": "保存"}, "https://example.test/保存"))

    def test_failed_task_projection_does_not_erase_run_diagnostic(self):
        from agent_service.openai_client import ModelCallError
        self.decision = intent("goal", workflow="problem_solving", scope="learning")
        def fail_problem(system, user, schema, **kwargs):
            if schema is ProblemCoachBundle:
                raise ModelCallError("CONNECTION", "APIConnectionError")
            return self.model(system, user, schema, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=fail_problem):
            result = self.send("RAG 是什么", mode="problem_solving")
        run = self.state()["runs"][result.run_id]
        self.assertEqual(run["error_code"], "RT.MODEL.CONNECTION")
        self.assertEqual(run["stage"], "failed")
        self.assertTrue(any(e["stage"] == "problem_answer" and e["error_code"] and e["model"] and e["duration_ms"] is not None for e in self.state()["events"]))

    def test_crash_after_reply_before_worker_completion_does_not_duplicate(self):
        execute = self.harness._execute
        def crash_after_publish(*args):
            execute(*args)
            raise RuntimeError("simulated interruption after answer commit")
        with patch.object(self.harness, "_execute", side_effect=crash_after_publish):
            result = self.send("你好")
        self.assertTrue(self.state()["runs"][result.run_id]["execution_complete"])
        self.control(result.run_id, "retry")
        self.harness.drain(self.sid)
        self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "coach"]), 1)

    def test_task_id_cannot_cross_session(self):
        self.decision = intent("goal", workflow="topic_exploration", scope="learning")
        self.send("想了解 RAG")
        task_id = self.state()["active_task_id"]
        body = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="继续", task_id=task_id)
        with self.assertRaisesRegex(ValueError, "SESSION_MISMATCH"):
            self.harness.accept(str(uuid.uuid4()), body)

    def test_mode_change_preserves_task_and_progress(self):
        self.decision = intent("goal", workflow="topic_exploration", scope="learning")
        run = self.send("想了解 RAG")
        before = self.state()["active_task_id"]
        self.control(run.run_id, "set_mode", "source_learning")
        data = self.state()
        self.assertEqual(data["active_task_id"], before)
        self.assertEqual(data["tasks"][before]["mode"], "source_learning")
        self.assertEqual(data["tasks"][before]["stage"], "clarify_goal")
        self.control(run.run_id, "set_mode", "auto")
        self.assertEqual(self.state()["mode"], "auto")

    def test_hint_skip_self_report_do_not_count_as_problem_answer(self):
        self.decision = intent("question", workflow="problem_solving", scope="learning")
        self.send("如何回答 RAG", mode="problem_solving")
        for name, text in [("hint", "给个提示"), ("skip_check", "跳过"), ("self_report", "我懂了")]:
            self.decision = intent(name, scope="continue_goal", workflow="problem_solving")
            self.send(text)
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))
        task = next(iter(self.state()["tasks"].values()))
        self.assertNotEqual(task["context"].get("understanding"), "verified")
        self.assertFalse(task["context"].get("transfer_passed"))

    def test_problem_requires_independent_answer_then_transfer(self):
        self.decision = intent("question", workflow="problem_solving", scope="learning")
        self.send("RAG 是什么", mode="problem_solving")
        self.decision = intent("answer", workflow="problem_solving", scope="continue_goal")
        self.send("准备工程师面试")  # calibration, followed by teaching/check
        self.send("先检索再生成")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["stage"], "transfer")
        self.assertNotEqual(task["context"].get("understanding"), "verified")
        self.send("没有相关证据时应明确边界")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["context"]["understanding"], "verified")
        self.assertEqual(self.state()["draft"]["content"], "先检索相关资料，再基于上下文生成回答。")
        self.capture.assert_not_called()

    def test_stop_fences_late_model_and_keeps_queue_paused(self):
        accepted = self.send(drain=False)
        entered, release = threading.Event(), threading.Event()
        def slow_model(*args, **kwargs):
            if args[2] is ConversationOutput:
                entered.set()
                self.assertTrue(release.wait(5))
            return self.model(*args, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=slow_model):
            worker = threading.Thread(target=self.harness.drain, args=(self.sid,))
            worker.start()
            self.assertTrue(entered.wait(5))
            queued = self.send("稍后解释 RAG", delivery="queue", drain=False)
            self.control(accepted.run_id, "stop")
            release.set()
            worker.join(5)
            self.assertFalse(worker.is_alive())
        data = self.state()
        self.assertTrue(data["paused"])
        self.assertFalse(any(m["role"] == "coach" for m in data["messages"]))
        self.assertEqual(data["runs"][queued.run_id]["status"], "queued")

    def test_steering_replaces_current_generation_without_duplicate_reply(self):
        accepted = self.send("解释 RAG", drain=False)
        entered, release = threading.Event(), threading.Event()
        count = 0
        def slow_model(*args, **kwargs):
            nonlocal count
            if args[2] is ConversationOutput:
                count += 1
                if count == 1:
                    entered.set()
                    self.assertTrue(release.wait(5))
            return self.model(*args, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=slow_model):
            worker = threading.Thread(target=self.harness.drain, args=(self.sid,))
            worker.start()
            self.assertTrue(entered.wait(5))
            second = self.send("请用初学者能理解的说法", drain=False)
            self.assertEqual(accepted.run_id, second.run_id)
            release.set()
            worker.join(5)
        self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "coach"]), 1)
        self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "user"]), 2)

    def test_failed_run_retries_without_rerouting_completed_intent(self):
        accepted = self.send(drain=False)
        def failing(*args, **kwargs):
            if args[2] is ConversationOutput:
                raise RuntimeError("RT.MODEL.EMPTY")
            return self.model(*args, **kwargs)
        with patch("agent_service.conversation.parse_model", side_effect=failing):
            self.harness.drain(self.sid)
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "retryable_failed")
        self.control(accepted.run_id, "retry")
        self.harness.drain(self.sid)
        self.assertEqual(self.state()["runs"][accepted.run_id]["status"], "completed")
        self.assertEqual(len([c for c in self.calls if c[0] is IntentDecision]), 1)

    def test_reopen_preserves_messages_runs_and_monotonic_events(self):
        self.send()
        reopened = ConversationStore(HarnessStore(str(self.tasks.path))).get(self.sid)
        self.assertEqual(reopened["messages"], self.state()["messages"])
        self.assertEqual([e["seq"] for e in reopened["events"]], list(range(1, len(reopened["events"]) + 1)))

    def test_all_modes_handle_thanks_followup_and_negative_without_write(self):
        for mode in LABELS:
            sid = str(uuid.uuid4())
            for name, text in [("thanks", "谢谢"), ("followup", "能举个例子吗"), ("reject", "不要保存、切换或新建")]:
                self.decision = intent(name)
                self.send(text, mode=mode, sid=sid)
            self.assertFalse(self.store.get(sid)["tasks"])
        self.capture.assert_not_called()

    def test_natural_save_requires_matching_version_and_understanding(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 笔记")
        pending = self.state()["pending"]
        self.decision = intent("confirm", understanding="self_reported", proposed_actions=[IntentOperation(kind="save", disposition="confirm", evidence="我理解了，请保存", **{k:pending[k] for k in ("target_id","version")})])
        self.capture.return_value = committing_result("这是本轮真实回答。")
        self.send("我理解了，请保存")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["status"], "committing")
        self.assertEqual(self.capture.call_args.args[1], "这是本轮真实回答。")
        self.assertEqual(self.capture.call_count, 1)
        self.assertIsNone(self.state()["pending"])

    def test_pending_version_mismatch_never_writes(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 笔记")
        pending = self.state()["pending"]
        self.decision = intent("confirm", understanding="self_reported")
        self.send("保存", operation={**pending, "version": pending["version"] + 1})
        self.capture.assert_not_called()

    def make_committable(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 笔记")
        pending = self.state()["pending"]
        self.decision = intent("self_report", understanding="self_reported")
        self.send("我理解了")
        self.decision = intent("confirm", understanding="self_reported")
        self.capture.return_value = committing_result("这是本轮真实回答。")
        run = self.send("保存", operation=pending)
        return run, self.state()["active_task_id"]

    def test_new_input_holds_unclaimed_commit_before_model_call(self):
        run, task_id = self.make_committable()
        self.send("不要保存", drain=False)
        with self.assertRaisesRegex(ValueError, "COMMIT_REVOKED"):
            self.harness.claim_commit(task_id)
        self.assertIsNone(self.tasks.get(task_id).memory_package)
        self.decision = intent("reject")
        self.harness.drain(self.sid)
        self.assertEqual(self.tasks.get(task_id).status, "cancelled")

    def test_stop_revokes_unclaimed_but_not_already_claimed_commit(self):
        run, task_id = self.make_committable()
        self.harness.claim_commit(task_id)
        self.control(run.run_id, "stop")
        self.assertEqual(self.tasks.get(task_id).status, "committing")
        self.assertTrue(self.tasks.get(task_id).context["commit_claimed"])

    def test_stop_then_explicit_continue_resumes_but_greeting_does_not_drain_queue(self):
        run = self.send(drain=False)
        self.control(run.run_id, "stop")
        queued = self.send("随后处理", delivery="queue", drain=False)
        self.decision = intent("greeting")
        self.send("你好")
        self.assertTrue(self.state()["paused"])
        self.assertEqual(self.state()["runs"][queued.run_id]["status"], "queued")
        self.decision = intent("continue")
        self.send("继续")
        self.assertFalse(self.state()["paused"])
        self.assertEqual(self.state()["runs"][run.run_id]["status"], "completed")

    def test_source_learning_skip_keeps_unknown_and_generated_provenance(self):
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("直接教我 RAG", mode="source_learning")
        self.decision = intent("skip_check", workflow="source_learning", scope="continue_goal")
        self.send("先别考我，继续")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["context"]["understanding"], "unknown")
        self.assertTrue(any(s["type"] == "agent_generated" for s in task["context"]["sources"]))
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))

    def test_goal_clarifying_answer_starts_teaching_without_source_confirmation(self):
        self.decision = intent("goal", workflow="topic_exploration", scope="learning")
        self.send("我想了解 RAG")
        self.decision = intent("answer", workflow="topic_exploration", scope="continue_goal")
        self.send("用于面试")
        self.assertIsNone(self.state()["pending"])
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["stage"], "teaching")
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))

    def test_jd_emits_map_then_one_selected_question(self):
        self.decision = intent("goal", workflow="problem_solving", scope="learning", is_jd=True)
        self.send("岗位职责：RAG", mode="problem_solving")
        pending = self.state()["pending"]
        self.assertEqual(pending["kind"], "select_question")
        self.assertFalse(any(schema is ProblemCoachBundle for schema, _ in self.calls))
        self.decision = intent("confirm", workflow="problem_solving", scope="continue_goal")
        self.send("RAG 是什么？", operation={k:pending[k] for k in ("kind","target_id","version")} | {"selection":["RAG 是什么？"]})
        self.assertEqual(self.state()["tasks"][self.state()["active_task_id"]]["stage"], "calibration")

    def test_high_risk_no_evidence_is_not_supported(self):
        self.decision = intent("question", needs_verification=True, public_search_query="当前官方贷款基准利率")
        with patch("agent_service.conversation.web_search_text", return_value="") as search:
            self.send("当前贷款利率如何")
            search.assert_called_once()
        self.assertEqual(self.state()["teaching_context"]["evidence"]["state"], "insufficient")

    def test_summary_keeps_raw_transcript_and_is_session_scoped(self):
        for i in range(13):
            self.send(f"你好 {i}")
        with self.store.transaction(self.sid) as data:
            for m in data["messages"]:
                if m["role"] == "user": m["content"] = "a" * 36000
        self.harness.maintain_summary(self.sid)
        data = self.state()
        self.assertEqual(len([m for m in data["messages"] if m["role"] == "user"]), 13)
        self.assertEqual(data["summary_version"], 1)
        other = str(uuid.uuid4())
        self.send("你好", sid=other)
        self.assertEqual(self.store.get(other)["summary"], "")

    def test_greeting_does_not_make_first_real_question_an_unrelated_goal(self):
        self.send("你好")
        self.decision = intent("question", answer_only=True).model_copy(update={"relation": "new_topic"})
        self.send("RAG 是什么")
        self.assertIsNone(self.state()["pending"])
        self.assertFalse(self.state()["tasks"])

    def test_confirm_continue_session_answers_stored_question_without_repetition(self):
        self.decision = intent("goal", scope="learning", workflow="source_learning", direct_teaching=True)
        self.send("带我系统学习 RAG")
        self.decision = intent("goal", scope="learning", workflow="source_learning").model_copy(update={"relation": "new_topic"})
        self.send("请带我系统学习吉他")
        pending = self.state()["pending"]
        self.decision = intent("confirm")
        self.send("继续放在这里", operation={"kind":"continue_session", "target_id":pending["target_id"], "version":pending["version"]})
        self.assertIsNone(self.state()["pending"])
        self.assertEqual(self.state()["focus_goal"], "请带我系统学习吉他")
        last_coach = [c for schema,c in self.calls if schema is ConversationOutput][-1]
        self.assertEqual(last_coach["context"]["current_inputs"], ["请带我系统学习吉他"])

    def test_first_direct_teaching_goal_does_not_require_a_nonexistent_confirmation(self):
        self.decision = intent("goal", "skip_check", workflow="source_learning", scope="learning", direct_teaching=True,
                               proposed_actions=[IntentOperation(kind="change_goal", disposition="request", evidence="直接教我 RAG")])
        self.send("直接教我 RAG，先跳过检查", mode="source_learning")
        task = self.state()["tasks"][self.state()["active_task_id"]]
        self.assertEqual(task["stage"], "teaching")
        self.assertEqual(task["context"]["understanding"], "unknown")

    def test_ack_compaction_does_not_reset_sequence_or_message_idempotency(self):
        original = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="你好，第一条")
        accepted = self.harness.accept(self.sid, original)
        self.harness.drain(self.sid)
        for i in range(20): self.send(f"你好 {i}")
        self.harness.maintain_summary(self.sid)
        with self.store.transaction(self.sid) as data:
            last = self.store.last_seq(data)
            data["last_acked_seq"] = last
            self.store.compact_acknowledged(data)
        self.assertLessEqual(len(self.state()["events"]), 64)
        self.assertEqual(len(self.state()["messages"]), 42, "short conversations must not compact merely because of message count")
        duplicate = self.harness.accept(self.sid, original)
        self.assertEqual(duplicate.run_id, accepted.run_id)
        self.send("之后的新消息")
        self.assertGreater(self.state()["events"][-1]["seq"], last)

    def test_stop_after_reply_then_resume_never_duplicates_completed_answer(self):
        run = self.send()
        self.control(run.run_id, "stop")
        self.control(run.run_id, "resume")
        self.harness.drain(self.sid)
        self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "coach"]), 1)

    def test_correction_invalidates_understanding_and_creates_a_new_draft_version(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 笔记")
        previous = dict(self.state()["pending"])
        self.decision = intent("correction", "followup")
        self.send("第二点不对，请修正")
        self.assertGreater(self.state()["draft"]["version"], previous["version"])
        self.assertEqual(self.state()["draft"]["understanding"], "unknown")
        self.decision = intent("confirm", understanding="self_reported")
        self.send("保存旧版本", operation=previous)
        self.capture.assert_not_called()

    def test_summary_failure_retry_does_not_repeat_an_already_published_answer(self):
        for i in range(11): self.send(f"你好 {i}")
        with self.store.transaction(self.sid) as data:
            for m in data["messages"]:
                if m["role"] == "user": m["content"] = "a" * 42000
        normal = self.model
        def fail_summary(*args, **kwargs):
            if args[2] is ConversationSummary: raise RuntimeError("RT.MODEL.TIMEOUT")
            return normal(*args, **kwargs)
        # This deliberately huge history isolates summary-failure recovery.
        # Whole-turn admission limits are tested separately; allow the raw
        # context fallback here so the already-published-answer invariant runs.
        with patch("agent_service.conversation.parse_model", side_effect=fail_summary), \
             patch("agent_service.run_accounting.ESTIMATED_INPUT_LIMIT", 1_000_000):
            run = self.send("第十二条")
            self.harness.maintain_summary(self.sid)
        self.assertEqual(self.state()["runs"][run.run_id]["status"], "completed")
        self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "coach"]), 12)
        self.harness.maintain_summary(self.sid)
        self.assertEqual(len([m for m in self.state()["messages"] if m["role"] == "coach"]), 12)

    def test_bound_operation_does_not_require_a_second_intent_model_call(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 笔记")
        before = len([c for c in self.calls if c[0] is IntentDecision])
        pending = self.state()["pending"]
        self.send("暂不保存", operation={**pending, "kind":"reject_save"})
        self.assertEqual(len([c for c in self.calls if c[0] is IntentDecision]), before)

    def test_understanding_after_consent_uses_same_draft_without_reasking_consent(self):
        self.decision = intent("material", scope="organize")
        self.send("RAG 笔记")
        self.send("保存", operation=self.state()["pending"])
        self.capture.assert_not_called()
        self.capture.return_value = committing_result("这是本轮真实回答。")
        self.decision = intent("self_report", understanding="self_reported")
        self.send("我理解了")
        self.capture.assert_called_once()

    def test_source_learning_self_report_and_explicit_save_do_not_require_exam(self):
        self.decision = intent("goal", workflow="source_learning", scope="learning", direct_teaching=True)
        self.send("教我 RAG", mode="source_learning")
        self.decision = intent("self_report", "confirm", understanding="self_reported",
                               proposed_actions=[IntentOperation(kind="save", disposition="request", evidence="我理解了，保存刚才这段")])
        self.capture.return_value = committing_result("这是本轮真实回答。")
        self.send("我理解了，保存刚才这段")
        self.capture.assert_called_once()
        self.assertFalse(any(schema is MasteryEvaluation for schema, _ in self.calls))


if __name__ == "__main__":
    unittest.main()
