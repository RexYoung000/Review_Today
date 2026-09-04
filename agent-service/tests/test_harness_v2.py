from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import agent_service.harness as harness_module
import agent_service.main as main_module
import agent_service.model_capabilities as capability_module
from agent_service.harness import classify_mode, process_action, process_task, record_action, resume_incomplete_tasks
from agent_service.harness_store import HarnessStore, HarnessTaskRecord
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore
from agent_service.schemas import ProblemCoachBundle, SessionTurnRequest, SourceCandidate, TaskActionRequest


class HarnessStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "harness.sqlite3")
        self.store = HarnessStore(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_record(self, content: str = "我想了解 RAG") -> HarnessTaskRecord:
        return HarnessTaskRecord(
            task_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            client_message_id=str(uuid.uuid4()),
            content=content,
            content_type="text",
            primary_language="zh",
            mode_preset="auto",
        )

    def test_persists_task_events_and_ack_position(self) -> None:
        record, created = self.store.create(self.make_record())
        self.assertTrue(created)
        event = self.store.append_event(
            record.task_id,
            stage="routing",
            state="running",
            node="mode_router",
            user_summary="正在理解你的目标",
        )
        self.assertEqual(event.seq, 1)
        reopened = HarnessStore(self.path)
        self.assertEqual(reopened.get(record.task_id).events[0]["event_id"], event.event_id)
        reopened.acknowledge(record.task_id, 1)
        self.assertEqual(reopened.get(record.task_id).last_acked_seq, 1)

    def test_session_message_is_idempotent(self) -> None:
        record = self.make_record()
        first, created = self.store.create(record)
        duplicate = self.make_record()
        duplicate.session_id = record.session_id
        duplicate.client_message_id = record.client_message_id
        second, created_again = self.store.create(duplicate)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.task_id, second.task_id)


class HarnessRoutingTests(unittest.TestCase):
    def make_record(self, content: str, preset: str = "auto") -> HarnessTaskRecord:
        return HarnessTaskRecord(
            task_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            client_message_id=str(uuid.uuid4()),
            content=content,
            content_type="text",
            primary_language="zh",
            mode_preset=preset,
        )

    def test_common_modes_route_without_a_model_call(self) -> None:
        self.assertEqual(classify_mode(self.make_record("我想了解 RAG")).mode, "topic_exploration")
        self.assertEqual(classify_mode(self.make_record("请解释 RAG 是什么？")).mode, "problem_solving")
        self.assertEqual(classify_mode(self.make_record("岗位职责：负责 RAG；任职要求：熟悉向量数据库")).mode, "problem_solving")
        self.assertEqual(
            classify_mode(self.make_record("我不理解这份资料：" + "资料内容" * 60)).mode,
            "source_learning",
        )
        self.assertEqual(
            classify_mode(self.make_record("这是我已经理解并希望整理的材料。" + "知识内容" * 60)).mode,
            "memory_organization",
        )

    def test_session_preset_wins(self) -> None:
        result = classify_mode(self.make_record("一段零散笔记", preset="memory_organization"))
        self.assertEqual(result.mode, "memory_organization")
        self.assertEqual(result.confidence, 1)

    def test_preset_mode_mismatch_only_suggests_a_switch(self) -> None:
        result = classify_mode(self.make_record("为什么 RAG 需要向量数据库？", preset="memory_organization"))
        self.assertEqual(result.mode, "problem_solving")
        self.assertTrue(result.suggest_switch)

    def test_source_search_does_not_fabricate_urls(self) -> None:
        with patch("agent_service.capture.web_search_text", return_value=""):
            self.assertEqual(harness_module.find_source_candidates("RAG", model="coach"), [])

    def test_advertised_model_is_not_ready_when_generation_probe_fails(self) -> None:
        models = {
            capability_module.ROUTER_MODEL,
            capability_module.COACH_MODEL,
            capability_module.RISK_MODEL,
        }

        def callable_model(model: str) -> bool:
            if model == capability_module.COACH_MODEL:
                raise TimeoutError("probe timeout")
            return True

        with patch.object(capability_module, "openai_key", return_value="test-key"), patch.object(
            capability_module, "available_model_ids", return_value=models
        ), patch.object(capability_module, "model_is_callable", side_effect=callable_model):
            capability_module.probe()
        status = capability_module.snapshot()
        self.assertEqual(status["router"]["status"], "ready")
        self.assertEqual(status["risk"]["status"], "ready")
        self.assertEqual(status["coach"]["status"], "unavailable")
        self.assertIn("TimeoutError", str(status["coach"]["error"]))


class HarnessHTTPContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = HarnessStore(str(Path(self.temp.name) / "harness.sqlite3"))
        self.client = TestClient(main_module.app)
        self.store_patches = [
            patch.object(main_module, "harness_store", self.store),
            patch.object(harness_module, "harness_store", self.store),
            patch.object(main_module, "openai_key", return_value="test-key"),
            patch.object(main_module, "process_task", return_value=None),
            patch.object(main_module, "conversation_harness", ConversationHarness(ConversationStore(self.store))),
        ]
        for item in self.store_patches:
            item.start()
        self.run_start_patch = patch.object(main_module.conversation_harness, "start")
        self.run_start_patch.start()

    def tearDown(self) -> None:
        self.run_start_patch.stop()
        for item in reversed(self.store_patches):
            item.stop()
        self.temp.cleanup()

    def body(self, message_id: str) -> dict:
        return SessionTurnRequest(
            client_message_id=message_id,
            content="我想了解 RAG",
            mode_preset="auto",
        ).model_dump()

    def test_turn_returns_immediately_and_is_idempotent(self) -> None:
        session_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        first = self.client.post(f"/v2/sessions/{session_id}/turns", json=self.body(message_id))
        second = self.client.post(f"/v2/sessions/{session_id}/turns", json=self.body(message_id))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "accepted")
        self.assertEqual(first.json()["task_id"], second.json()["task_id"])

    def test_capability_probe_can_be_requested_again(self) -> None:
        with patch.object(main_module, "start_probe") as start:
            response = self.client.post("/v2/capabilities/probe")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "checking")
        start.assert_called_once_with()

    def test_stream_probe_marks_structured_only_roles_not_applicable(self) -> None:
        states = {
            "router": {"model": "router", "status": "ready", "error": "", "streaming": "checking"},
            "coach": {"model": "coach", "status": "ready", "error": "", "streaming": "checking"},
            "risk": {"model": "risk", "status": "unavailable", "error": "timeout", "streaming": "checking"},
        }
        with patch.object(capability_module, "_state", states), \
             patch.object(capability_module, "probe"), \
             patch.object(capability_module, "model_stream_capability", return_value={"ready": True, "streaming": "streaming"}):
            capability_module.probe_with_streaming()
            result = capability_module.snapshot()
            self.assertEqual(result["router"]["streaming"], "not_applicable")
            self.assertEqual(result["risk"]["streaming"], "not_applicable")
            self.assertEqual(result["coach"]["streaming"], "streaming")

    def test_events_are_incremental_and_actions_are_idempotent(self) -> None:
        session_id = str(uuid.uuid4())
        accepted = self.client.post(
            f"/v2/sessions/{session_id}/turns",
            json=self.body(str(uuid.uuid4())),
        ).json()
        task_id = accepted["task_id"]
        self.store.append_event(
            task_id,
            stage="routing",
            state="running",
            node="mode_router",
            user_summary="正在理解你的目标",
        )
        self.store.append_event(
            task_id,
            stage="clarify_goal",
            state="awaiting_user",
            node="topic_goal",
            user_summary="等你明确学习目标",
            required_action={"type": "respond", "prompt": "你希望学完后做什么？", "options": []},
        )
        page = self.client.get(f"/v2/tasks/{task_id}/events?after_seq=1")
        self.assertEqual([item["seq"] for item in page.json()["events"]], [2])

        action_id = str(uuid.uuid4())
        action = TaskActionRequest(action_id=action_id, action_type="respond", content="能够做项目").model_dump()
        self.client.post(f"/v2/tasks/{task_id}/actions", json=action)
        self.client.post(f"/v2/tasks/{task_id}/actions", json=action)
        self.assertEqual(self.store.get(task_id).processed_action_ids, [action_id])

    def test_memory_ack_must_match_and_completes_once(self) -> None:
        session_id = str(uuid.uuid4())
        accepted = self.client.post(
            f"/v2/sessions/{session_id}/turns",
            json=self.body(str(uuid.uuid4())),
        ).json()
        task_id = accepted["task_id"]
        knowledge_id = str(uuid.uuid4())

        def prepare(record: HarnessTaskRecord) -> None:
            record.status = "committing"
            record.memory_package = {
                "understood_as": "RAG 是检索增强生成",
                "theme": "RAG",
                "attribution": "claim",
                "risk_flagged": False,
                "risk_reason": "",
                "knowledge": [
                    {
                        "id": knowledge_id,
                        "learning_goal": "理解 RAG 的核心流程",
                        "knowledge_type": "concept",
                        "theme": "RAG",
                        "content_language": "zh",
                        "question_language": "zh",
                        "answer_language": "zh",
                        "evidence_excerpt": "RAG 先检索相关信息，再让模型基于信息生成答案。",
                        "evidence_locator": "测试输入",
                        "title": "RAG 核心流程",
                        "explanation": "1. 先检索相关信息\n2. 再基于检索结果生成答案",
                        "scoring_spec": {
                            "learning_goal": "理解 RAG 的核心流程",
                            "must_cover": ["检索", "生成"],
                            "acceptable_paraphrases": [],
                            "common_misconceptions": [],
                            "evidence": "RAG 先检索相关信息，再让模型基于信息生成答案。",
                            "order_rules": "先检索，再生成",
                        },
                        "questions": [{"variant_index": 0, "prompt_text": "RAG 的核心流程是什么？"}],
                    }
                ],
            }

        self.store.mutate(task_id, prepare)
        mismatch = self.client.post(
            f"/v2/tasks/{task_id}/ack",
            json={"last_event_seq": 0, "knowledge_ids": []},
        )
        self.assertEqual(mismatch.status_code, 409)
        ack = self.client.post(
            f"/v2/tasks/{task_id}/ack",
            json={"last_event_seq": 0, "knowledge_ids": [knowledge_id]},
        )
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json()["status"], "completed")


class TopicExplorationIntegrationTests(unittest.TestCase):
    def test_rag_wish_produces_visible_question_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = HarnessStore(str(Path(temp) / "harness.sqlite3"))
            record = HarnessTaskRecord(
                task_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                client_message_id=str(uuid.uuid4()),
                content="我想了解 RAG",
                content_type="text",
                primary_language="zh",
                mode_preset="auto",
            )
            store.create(record)
            with patch.object(harness_module, "harness_store", store):
                process_task(record.task_id)
            finished = store.get(record.task_id)
            self.assertEqual(finished.mode, "topic_exploration")
            self.assertEqual(finished.status, "awaiting_user")
            self.assertEqual(finished.required_action["type"], "respond")
            self.assertTrue(any(item.get("message") for item in finished.events))

    def test_durable_action_resumes_after_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = HarnessStore(str(Path(temp) / "harness.sqlite3"))
            record = HarnessTaskRecord(
                task_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                client_message_id=str(uuid.uuid4()),
                content="我想了解 RAG",
                content_type="text",
                primary_language="zh",
                mode_preset="auto",
                mode="topic_exploration",
                status="awaiting_user",
                stage="clarify_goal",
                required_action={"type": "respond", "prompt": "学习目标", "options": []},
            )
            store.create(record)
            action = TaskActionRequest(
                action_id=str(uuid.uuid4()),
                action_type="respond",
                content="能够设计基础 RAG 流程",
            )
            with patch.object(harness_module, "harness_store", store):
                record_action(record.task_id, action)
                resume_incomplete_tasks()
            resumed = store.get(record.task_id)
            self.assertIn(action.action_id, resumed.completed_action_ids)
            self.assertEqual(resumed.stage, "choose_source")
            self.assertEqual(resumed.status, "awaiting_user")

    def test_unrelated_topic_suggests_new_session_and_can_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = HarnessStore(str(Path(temp) / "harness.sqlite3"))
            record = HarnessTaskRecord(
                task_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                client_message_id=str(uuid.uuid4()),
                content="请解释二叉树的遍历方式？",
                content_type="text",
                primary_language="zh",
                mode_preset="auto",
                context={"recent_messages": [{"role": "user", "content": "我们继续学习 RAG 检索评估"}]},
            )
            store.create(record)
            relation = harness_module.ModeDecision(
                mode="problem_solving",
                confidence=0.96,
                reason="当前问题从 RAG 转向无关的数据结构主题",
                relation="new_topic",
            )
            with patch.object(harness_module, "harness_store", store), patch.object(
                harness_module, "parse_model", return_value=relation
            ):
                process_task(record.task_id)
                proposed = store.get(record.task_id)
                self.assertEqual(proposed.stage, "confirm_session")
                self.assertEqual(proposed.required_action["type"], "confirm_new_session")

                action = TaskActionRequest(
                    action_id=str(uuid.uuid4()),
                    action_type="create_handoff",
                    content=str(uuid.uuid4()),
                )
                process_action(record.task_id, action)
            handed_off = store.get(record.task_id)
            self.assertEqual(handed_off.status, "completed")
            self.assertEqual(handed_off.stage, "completed")
            self.assertIn(action.content, handed_off.result_summary)

    def test_topic_source_pack_requires_two_real_sources_and_keeps_scope_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = HarnessStore(str(Path(temp) / "harness.sqlite3"))
            record = HarnessTaskRecord(
                task_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                client_message_id=str(uuid.uuid4()),
                content="我想了解 RAG",
                content_type="text",
                primary_language="zh",
                mode_preset="auto",
                mode="topic_exploration",
                status="awaiting_user",
                stage="choose_source",
                result_summary="学习目标：能解释并设计基础 RAG 流程",
                required_action={"type": "respond", "prompt": "请选择资料来源", "options": []},
            )
            store.create(record)
            candidates = [
                SourceCandidate(title="官方概览", url="https://example.com/overview", snippet="基础"),
                SourceCandidate(title="评估指南", url="https://example.org/evaluation", snippet="评估"),
            ]
            action = TaskActionRequest(
                action_id=str(uuid.uuid4()),
                action_type="respond",
                selection="Agent 查找资料",
            )
            with patch.object(harness_module, "harness_store", store), patch.object(
                harness_module, "find_source_candidates", return_value=candidates
            ):
                process_action(record.task_id, action)
            result = store.get(record.task_id)
            self.assertEqual(result.stage, "source_confirmation")
            pack = result.events[-1]["payload"]["source_pack"]
            self.assertEqual(len(pack), 2)
            self.assertTrue(all(item["purpose"] and item["scope"] and item["date_or_version"] for item in pack))

    def test_cancelled_task_ignores_late_model_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = HarnessStore(str(Path(temp) / "harness.sqlite3"))
            record = HarnessTaskRecord(
                task_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                client_message_id=str(uuid.uuid4()),
                content="什么是 RAG？",
                content_type="text",
                primary_language="zh",
                mode_preset="problem_solving",
            )
            store.create(record)
            bundle = ProblemCoachBundle.model_validate(ControlledWorkflowTests.model_result("", "", ProblemCoachBundle))

            def cancel_then_return(*_args, **_kwargs):
                process_action(
                    record.task_id,
                    TaskActionRequest(action_id=str(uuid.uuid4()), action_type="cancel"),
                )
                return bundle

            with patch.object(harness_module, "harness_store", store), patch.object(
                harness_module, "parse_model", side_effect=cancel_then_return
            ):
                process_task(record.task_id)
            result = store.get(record.task_id)
            self.assertEqual(result.status, "cancelled")
            self.assertFalse(any(item.get("state") == "awaiting_user" for item in result.events))


class ControlledWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = HarnessStore(str(Path(self.temp.name) / "harness.sqlite3"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def record(self, content: str, preset: str) -> HarnessTaskRecord:
        row = HarnessTaskRecord(
            task_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            client_message_id=str(uuid.uuid4()),
            content=content,
            content_type="text",
            primary_language="zh",
            mode_preset=preset,
        )
        self.store.create(row)
        return row

    @staticmethod
    def model_result(_system, _user, schema, **_kwargs):
        if schema.__name__ == "CoachTurnOutput":
            return schema.model_validate({
                "message": "先解释核心概念，再检查你是否理解。",
                "stage": "teaching",
                "evidence_state": "scoped",
            })
        if schema.__name__ == "JDAnalysis":
            return schema.model_validate({
                "role_goal": "交付可落地的 RAG 应用",
                "competency_map": ["检索", "评估"],
                "risk_points": ["缺少线上评估经验"],
                "prioritized_questions": ["如何评估 RAG？"],
            })
        if schema.__name__ == "ProblemCoachBundle":
            return schema.model_validate({
                "analysis": {
                    "question": "什么是 RAG？",
                    "question_type": "concept",
                    "assumptions": [],
                    "calibration_question": "你准备把它用于面试还是项目？",
                },
                "answer": {
                    "direct_answer": "RAG 先检索相关资料，再基于资料生成答案。",
                    "spoken_answer": "它把检索和生成串成一条可追溯链路。",
                    "assumptions": [],
                    "confidence": "high",
                },
                "gap_map": {
                    "related_knowledge": ["向量检索", "提示词"],
                    "likely_gaps": ["召回评估"],
                    "learning_order": ["检索", "生成", "评估"],
                },
                "learning_plan": {
                    "goal": "独立解释 RAG",
                    "steps": ["理解流程", "独立作答"],
                    "success_check": "能脱离答案说明取舍",
                },
            })
        raise AssertionError(schema.__name__)

    def test_source_learning_waits_for_understanding_confirmation(self) -> None:
        row = self.record("这是一份需要讲解的资料。" * 20, "source_learning")
        with patch.object(harness_module, "harness_store", self.store), patch.object(
            harness_module, "parse_model", side_effect=self.model_result
        ):
            process_task(row.task_id)
        result = self.store.get(row.task_id)
        self.assertEqual(result.status, "awaiting_user")
        self.assertEqual(result.required_action["type"], "confirm_understanding")
        self.assertIsNone(result.memory_package)

    def test_problem_mode_answers_then_calibrates_before_practice(self) -> None:
        row = self.record("什么是 RAG？", "problem_solving")
        with patch.object(harness_module, "harness_store", self.store), patch.object(
            harness_module, "parse_model", side_effect=self.model_result
        ):
            process_task(row.task_id)
        result = self.store.get(row.task_id)
        self.assertEqual(result.stage, "calibration")
        self.assertEqual(result.required_action["type"], "respond")
        answer = next(
            item["message"]["content"]
            for item in result.events
            if item.get("node") == "problem_answer" and item.get("message")
        )
        self.assertIn("先给你一版可直接使用的答案", answer)
        self.assertNotEqual(result.status, "completed")

    def test_jd_is_split_before_entering_a_question(self) -> None:
        row = self.record("岗位职责：负责 RAG；任职要求：熟悉评估", "problem_solving")
        with patch.object(harness_module, "harness_store", self.store), patch.object(
            harness_module, "parse_model", side_effect=self.model_result
        ):
            process_task(row.task_id)
        result = self.store.get(row.task_id)
        self.assertEqual(result.stage, "jd_analysis")
        self.assertEqual(result.required_action["type"], "choose_question")

    def test_memory_package_waits_for_mac_ack(self) -> None:
        row = self.record("已经理解的内容" * 30, "memory_organization")
        knowledge_id = str(uuid.uuid4())
        payload = {
            "understood_as": "一段已理解内容",
            "theme": "测试主题",
            "attribution": "claim",
            "risk_flagged": False,
            "risk_reason": "",
            "knowledge": [{
                "id": knowledge_id,
                "learning_goal": "复述核心内容",
                "knowledge_type": "concept",
                "theme": "测试主题",
                "content_language": "zh",
                "question_language": "zh",
                "answer_language": "zh",
                "evidence_excerpt": "已经理解的内容",
                "evidence_locator": "用户输入",
                "title": "核心内容",
                "explanation": "1. 这是核心内容\n2. 可以独立复述",
                "scoring_spec": {
                    "learning_goal": "复述核心内容",
                    "must_cover": ["核心内容"],
                    "acceptable_paraphrases": [],
                    "common_misconceptions": [],
                    "evidence": "已经理解的内容",
                    "order_rules": "",
                },
                "questions": [{"variant_index": 0, "prompt_text": "核心内容是什么？"}],
            }],
        }
        with patch.object(harness_module, "harness_store", self.store), patch.object(
            harness_module, "run_capture", return_value={"outcome": "committing", "extracted": payload}
        ):
            process_task(row.task_id)
        result = self.store.get(row.task_id)
        self.assertEqual(result.status, "committing")
        self.assertEqual(result.memory_package["knowledge"][0]["id"], knowledge_id)


if __name__ == "__main__":
    unittest.main()
