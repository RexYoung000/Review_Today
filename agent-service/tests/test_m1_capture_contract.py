from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent_service.capture import _parse_capture_model
from agent_service.main import app
from agent_service.schemas import ExtractPayload
from agent_service.store import store

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m1_acceptance.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def valid_extracted(source: str) -> dict:
    return {
        "understood_as": "用户想记住光合作用的过程。",
        "theme": "光合作用",
        "attribution": "claim",
        "risk_flagged": False,
        "risk_reason": "",
        "knowledge": [
            {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "learning_goal": "解释光合作用如何利用原料生成有机物并释放氧气。",
                "knowledge_type": "concept",
                "theme": "光合作用",
                "content_language": "zh",
                "question_language": "zh",
                "answer_language": "zh",
                "evidence_excerpt": source,
                "evidence_locator": "",
                "title": "光合作用",
                "explanation": (
                    "1. 植物利用光能。\n"
                    "2. 二氧化碳和水转化为有机物。\n"
                    "3. 这个过程会释放氧气。"
                ),
                "scoring_spec": {
                    "learning_goal": "解释光合作用的过程。",
                    "must_cover": ["光能", "二氧化碳和水", "有机物", "氧气"],
                    "acceptable_paraphrases": [],
                    "common_misconceptions": ["植物直接从土壤吸收有机物"],
                    "evidence": source,
                    "order_rules": "",
                },
                "questions": [
                    {
                        "variant_index": 0,
                        "prompt_text": "请解释植物进行光合作用的过程。",
                    }
                ],
            }
        ],
    }


def committing_result(source: str) -> dict:
    return {
        "events": [],
        "intent": "remember_content",
        "outcome": "committing",
        "user_status": "整理完成",
        "extracted": valid_extracted(source),
    }


class M1CaptureHTTPContractTests(unittest.TestCase):
    def setUp(self) -> None:
        store._tasks.clear()
        self.fixture = load_fixture()
        self.request = self.fixture["capture_request"]
        self.source = self.request["raw_text"]
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        store._tasks.clear()

    def submit_with_result(self, result: dict):
        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch("agent_service.main.run_capture", return_value=result),
        ):
            return self.client.post("/v1/capture/tasks", json=self.request)

    def test_fixed_fixture_waits_for_matching_ack(self) -> None:
        response = self.submit_with_result(committing_result(self.source))
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            response.json()["status"],
            self.fixture["expected_capture"]["initial_status_allowed"],
        )

        before_ack = self.client.get(f"/v1/capture/tasks/{self.request['task_id']}")
        self.assertEqual(before_ack.status_code, 200)
        body = before_ack.json()
        self.assertEqual(body["status"], "committing")
        self.assertEqual(body["receipt"]["knowledge_count"], 1)
        self.assertEqual(len(body["result"]["knowledge"]), 1)

        card = body["result"]["knowledge"][0]
        stable_card_fields = {
            "id",
            "learning_goal",
            "knowledge_type",
            "theme",
            "content_language",
            "question_language",
            "answer_language",
            "evidence_excerpt",
            "evidence_locator",
            "title",
            "explanation",
            "scoring_spec",
            "questions",
        }
        self.assertTrue(stable_card_fields.issubset(card))
        self.assertIn(card["evidence_excerpt"], self.source)
        self.assertIn(card["scoring_spec"]["evidence"], self.source)
        self.assertEqual(
            [question["variant_index"] for question in card["questions"]].count(0),
            1,
        )

        still_waiting = self.client.get(f"/v1/capture/tasks/{self.request['task_id']}")
        self.assertEqual(still_waiting.json()["status"], "committing")

        wrong_ack = self.client.post(
            f"/v1/capture/tasks/{self.request['task_id']}/ack",
            json={"knowledge_ids": []},
        )
        self.assertEqual(wrong_ack.status_code, 409)
        self.assertEqual(wrong_ack.json()["detail"]["error_code"], "RT.CAPTURE.ACK_MISMATCH")

        correct_ack = self.client.post(
            f"/v1/capture/tasks/{self.request['task_id']}/ack",
            json={"knowledge_ids": [card["id"]]},
        )
        self.assertEqual(correct_ack.status_code, 200)
        self.assertEqual(correct_ack.json()["status"], "completed")

    def test_duplicate_task_does_not_generate_a_second_result(self) -> None:
        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch(
                "agent_service.main.run_capture",
                return_value=committing_result(self.source),
            ) as run_capture,
        ):
            first = self.client.post("/v1/capture/tasks", json=self.request)
            record_identity = id(store.get(self.request["task_id"]))
            second = self.client.post("/v1/capture/tasks", json=self.request)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(run_capture.call_count, 1)
        self.assertEqual(id(store.get(self.request["task_id"])), record_identity)
        self.assertEqual(second.json()["status"], "committing")

    def test_retryable_failure_requeues_the_same_task_once(self) -> None:
        retryable_failure = {
            "events": [],
            "intent": "remember_content",
            "outcome": "retryable_failed",
            "error_code": "RT.CAPTURE.MODEL_FAILED",
            "user_status": "需要重试",
        }
        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch(
                "agent_service.main.run_capture",
                side_effect=[retryable_failure, committing_result(self.source)],
            ) as run_capture,
        ):
            self.client.post("/v1/capture/tasks", json=self.request)
            failed_record = store.get(self.request["task_id"])
            self.assertIsNotNone(failed_record)
            self.assertEqual(failed_record.status, "retryable_failed")
            record_identity = id(failed_record)

            retry = self.client.post("/v1/capture/tasks", json=self.request)
            duplicate_after_success = self.client.post("/v1/capture/tasks", json=self.request)

        self.assertEqual(retry.status_code, 200)
        self.assertEqual(duplicate_after_success.status_code, 200)
        self.assertEqual(run_capture.call_count, 2)
        self.assertEqual(id(store.get(self.request["task_id"])), record_identity)
        self.assertEqual(store.get(self.request["task_id"]).status, "committing")

    def test_reprocess_action_reuses_task_record(self) -> None:
        retryable_failure = {
            "events": [],
            "intent": "remember_content",
            "outcome": "retryable_failed",
            "error_code": "RT.CAPTURE.MODEL_FAILED",
            "user_status": "需要重试",
        }
        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch(
                "agent_service.main.run_capture",
                side_effect=[retryable_failure, committing_result(self.source)],
            ) as run_capture,
        ):
            self.client.post("/v1/capture/tasks", json=self.request)
            record_identity = id(store.get(self.request["task_id"]))
            retry = self.client.post(
                f"/v1/capture/tasks/{self.request['task_id']}/actions",
                json={"action": "reprocess"},
            )
            duplicate = self.client.post(
                f"/v1/capture/tasks/{self.request['task_id']}/actions",
                json={"action": "reprocess"},
            )

        self.assertEqual(retry.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(run_capture.call_count, 2)
        self.assertEqual(id(store.get(self.request["task_id"])), record_identity)
        self.assertEqual(store.get(self.request["task_id"]).status, "committing")

    def test_non_source_evidence_fails_closed(self) -> None:
        for field in ("evidence_excerpt", "scoring_spec.evidence"):
            with self.subTest(field=field):
                store._tasks.clear()
                result = committing_result(self.source)
                card = result["extracted"]["knowledge"][0]
                if field == "evidence_excerpt":
                    card["evidence_excerpt"] = "模型补写的来源事实"
                else:
                    card["scoring_spec"]["evidence"] = "模型补写的评分证据"

                response = self.submit_with_result(result)
                self.assertEqual(response.status_code, 200)
                task = self.client.get(
                    f"/v1/capture/tasks/{self.request['task_id']}"
                ).json()
                self.assertEqual(task["status"], "needs_attention")
                self.assertEqual(task["error_code"], "RT.CAPTURE.SEMANTIC_INVALID")
                self.assertIsNone(task["result"])

    def test_invalid_structure_never_returns_a_committable_result(self) -> None:
        result = committing_result(self.source)
        result["extracted"]["knowledge"][0]["questions"].append(
            {"variant_index": 0, "prompt_text": "重复的主问题"}
        )

        response = self.submit_with_result(result)
        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/v1/capture/tasks/{self.request['task_id']}").json()
        self.assertEqual(task["status"], "retryable_failed")
        self.assertEqual(task["error_code"], "RT.CAPTURE.STRUCTURE_INVALID")
        self.assertIsNone(task["result"])


class M1CaptureSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = load_fixture()["capture_request"]["raw_text"]

    def assert_invalid(self, extracted: dict) -> None:
        with self.assertRaises(ValidationError):
            ExtractPayload.model_validate(extracted)

    def test_rejects_invalid_ids_duplicate_ids_and_invalid_questions(self) -> None:
        cases: dict[str, dict] = {}

        invalid_uuid = valid_extracted(self.source)
        invalid_uuid["knowledge"][0]["id"] = "not-a-uuid"
        cases["invalid UUID"] = invalid_uuid

        duplicate_ids = valid_extracted(self.source)
        duplicate_ids["knowledge"].append(deepcopy(duplicate_ids["knowledge"][0]))
        cases["duplicate knowledge IDs"] = duplicate_ids

        duplicate_question_indices = valid_extracted(self.source)
        duplicate_question_indices["knowledge"][0]["questions"].append(
            {"variant_index": 0, "prompt_text": "重复的主问题"}
        )
        cases["duplicate question indices"] = duplicate_question_indices

        missing_main_question = valid_extracted(self.source)
        missing_main_question["knowledge"][0]["questions"][0]["variant_index"] = 1
        cases["missing main question"] = missing_main_question

        empty_scoring_evidence = valid_extracted(self.source)
        empty_scoring_evidence["knowledge"][0]["scoring_spec"]["evidence"] = ""
        cases["empty scoring evidence"] = empty_scoring_evidence

        for label, extracted in cases.items():
            with self.subTest(case=label):
                self.assert_invalid(extracted)

    def test_capture_node_retries_one_empty_structured_response(self) -> None:
        parsed = object()
        with patch(
            "agent_service.capture.parse_model",
            side_effect=[RuntimeError("RT.CAPTURE.MODEL_FAILED"), parsed],
        ) as parse_model:
            result = _parse_capture_model("system", "user", ExtractPayload)

        self.assertIs(result, parsed)
        self.assertEqual(parse_model.call_count, 2)

    def test_capture_node_does_not_retry_other_runtime_errors(self) -> None:
        with patch(
            "agent_service.capture.parse_model",
            side_effect=RuntimeError("provider unavailable"),
        ) as parse_model:
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                _parse_capture_model("system", "user", ExtractPayload)

        self.assertEqual(parse_model.call_count, 1)


if __name__ == "__main__":
    unittest.main()
