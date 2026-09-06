from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent_service import main
from agent_service.main import app
from agent_service.review import _grade_input, grade_answer
from agent_service.schemas import GradeRequest, GradeResult

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m1_acceptance.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def grade_request(case: dict, *, hint_used: bool | None = None) -> dict:
    fixture = load_fixture()
    source = fixture["capture_request"]["raw_text"]
    expected_card = fixture["expected_capture"]["card"]
    return {
        "attempt_id": case["attempt_id"],
        "prompt_text": "请解释植物进行光合作用的过程。",
        "scoring_spec": {
            "learning_goal": "解释光合作用如何利用原料生成有机物并释放氧气。",
            "must_cover": [
                point["meaning"] for point in expected_card["required_semantic_points"]
            ],
            "acceptable_paraphrases": [
                phrase
                for point in expected_card["required_semantic_points"]
                for phrase in point["acceptable_phrases"]
            ],
            "common_misconceptions": ["植物从土壤里直接吸收有机物"],
            "evidence": source,
            "order_rules": "不要求固定顺序，但四个关键点都要覆盖。",
        },
        "answer_text": case["answer_text"],
        "hint_used": case["hint_used"] if hint_used is None else hint_used,
        "primary_language": "zh",
    }


class M1ReviewHTTPContractTests(unittest.TestCase):
    def setUp(self) -> None:
        main._grade_results.clear()
        main._grade_acks.clear()
        self.fixture = load_fixture()
        self.correct = self.fixture["grade_cases"][0]
        self.incorrect = self.fixture["grade_cases"][1]
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        main._grade_results.clear()
        main._grade_acks.clear()

    def test_fixed_correct_and_incorrect_answers_keep_the_raw_answer(self) -> None:
        seen_answers: list[str] = []

        def fake_grade(body: GradeRequest) -> GradeResult:
            seen_answers.append(body.answer_text)
            grade = "again" if "直接吸收有机物" in body.answer_text else "good"
            return GradeResult(
                attempt_id=body.attempt_id,
                agent_grade=grade,
                brief_feedback="回答与原文关键点一致。" if grade == "good" else "核心机制与原文相反。",
                hint_used=body.hint_used,
            )

        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch("agent_service.main.grade_answer", side_effect=fake_grade),
        ):
            correct_response = self.client.post(
                "/v1/review/grade", json=grade_request(self.correct)
            )
            incorrect_response = self.client.post(
                "/v1/review/grade", json=grade_request(self.incorrect)
            )

        self.assertEqual(correct_response.status_code, 200)
        self.assertEqual(correct_response.json()["agent_grade"], "good")
        self.assertEqual(incorrect_response.status_code, 200)
        self.assertEqual(incorrect_response.json()["agent_grade"], "again")
        self.assertEqual(
            seen_answers,
            [self.correct["answer_text"], self.incorrect["answer_text"]],
        )
        self.assertEqual(
            set(correct_response.json()),
            {"attempt_id", "agent_grade", "brief_feedback", "hint_used"},
        )

    def test_same_attempt_returns_the_first_valid_result_without_regrading(self) -> None:
        request = grade_request(self.correct)
        first_result = GradeResult(
            agent_grade="good",
            brief_feedback="四个关键点都覆盖到了。",
        )
        second_result = GradeResult(
            agent_grade="again",
            brief_feedback="这条结果不应被调用。",
        )
        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch(
                "agent_service.main.grade_answer",
                side_effect=[first_result, second_result],
            ) as grade,
        ):
            first = self.client.post("/v1/review/grade", json=request)
            second = self.client.post("/v1/review/grade", json=request)
            ack = self.client.post(
                f"/v1/review/attempts/{request['attempt_id']}/ack",
                json={"attempt_id": request["attempt_id"]},
            )
            duplicate_ack = self.client.post(
                f"/v1/review/attempts/{request['attempt_id']}/ack",
                json={"attempt_id": request["attempt_id"]},
            )
            after_ack = self.client.post("/v1/review/grade", json=request)

        self.assertEqual(grade.call_count, 1)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json(), after_ack.json())
        self.assertEqual(first.json()["attempt_id"], request["attempt_id"])
        self.assertEqual(ack.json(), {"attempt_id": request["attempt_id"], "status": "acked"})
        self.assertEqual(duplicate_ack.json(), ack.json())

    def test_ack_rejects_mismatch_and_attempt_without_a_valid_grade(self) -> None:
        attempt_id = self.correct["attempt_id"]
        other_id = self.incorrect["attempt_id"]

        mismatch = self.client.post(
            f"/v1/review/attempts/{attempt_id}/ack",
            json={"attempt_id": other_id},
        )
        unknown = self.client.post(
            f"/v1/review/attempts/{attempt_id}/ack",
            json={"attempt_id": attempt_id},
        )

        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json()["detail"]["error_code"], "RT.REVIEW.ACK_MISMATCH")
        self.assertEqual(unknown.status_code, 409)
        self.assertEqual(unknown.json()["detail"]["error_code"], "RT.REVIEW.UNKNOWN_ATTEMPT")
        self.assertNotIn(attempt_id, main._grade_acks)

    def test_model_failure_does_not_cache_or_ack_and_same_id_can_retry(self) -> None:
        request = grade_request(self.correct)
        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch(
                "agent_service.main.grade_answer",
                side_effect=RuntimeError("provider failed"),
            ),
        ):
            failed = self.client.post("/v1/review/grade", json=request)

        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.json()["detail"]["error_code"], "RT.REVIEW.GRADE_FAILED")
        self.assertNotIn(request["attempt_id"], main._grade_results)

        ack = self.client.post(
            f"/v1/review/attempts/{request['attempt_id']}/ack",
            json={"attempt_id": request["attempt_id"]},
        )
        self.assertEqual(ack.status_code, 409)

        with (
            patch("agent_service.main.openai_key", return_value="test-key"),
            patch(
                "agent_service.main.grade_answer",
                return_value=GradeResult(
                    agent_grade="good",
                    brief_feedback="重试后成功完成判断。",
                ),
            ),
        ):
            retried = self.client.post("/v1/review/grade", json=request)

        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["agent_grade"], "good")

    def test_blank_answer_is_rejected_before_the_model_call(self) -> None:
        request = grade_request(self.correct)
        request["answer_text"] = " \n\t "
        with patch("agent_service.main.grade_answer") as grade:
            response = self.client.post("/v1/review/grade", json=request)

        self.assertEqual(response.status_code, 422)
        grade.assert_not_called()
        self.assertNotIn(request["attempt_id"], main._grade_results)


class M1ReviewSchemaAndPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = load_fixture()
        self.correct = self.fixture["grade_cases"][0]
        self.request = GradeRequest.model_validate(grade_request(self.correct))

    def test_grade_input_contains_all_contract_fields_and_verbatim_answer(self) -> None:
        model_input = _grade_input(self.request)
        payload = json.loads(model_input.split("\n", 1)[1])

        self.assertEqual(payload["answer_text"], self.correct["answer_text"])
        self.assertEqual(payload["prompt_text"], self.request.prompt_text)
        self.assertEqual(payload["learning_goal"], self.request.scoring_spec.learning_goal)
        self.assertEqual(payload["must_cover"], self.request.scoring_spec.must_cover)
        self.assertEqual(
            payload["acceptable_paraphrases"],
            self.request.scoring_spec.acceptable_paraphrases,
        )
        self.assertEqual(
            payload["common_misconceptions"],
            self.request.scoring_spec.common_misconceptions,
        )
        self.assertEqual(payload["evidence"], self.request.scoring_spec.evidence)
        self.assertEqual(payload["order_rules"], self.request.scoring_spec.order_rules)
        self.assertEqual(payload["hint_used"], self.request.hint_used)

    def test_hint_caps_a_model_good_result_to_hard(self) -> None:
        hinted = self.request.model_copy(update={"hint_used": True})
        with patch(
            "agent_service.review.parse_model",
            return_value=GradeResult(
                agent_grade="good",
                brief_feedback="提示后回答正确。",
            ),
        ):
            result = grade_answer(hinted)

        self.assertEqual(result.agent_grade, "hard")
        self.assertTrue(result.hint_used)
        self.assertEqual(result.attempt_id, hinted.attempt_id)

    def test_invalid_grade_blank_feedback_and_wrong_language_fail_closed(self) -> None:
        invalid_outputs = [
            {
                "attempt_id": "",
                "agent_grade": "easy",
                "brief_feedback": "回答正确。",
                "hint_used": False,
            },
            {
                "attempt_id": "",
                "agent_grade": "good",
                "brief_feedback": "   ",
                "hint_used": False,
            },
        ]
        for output in invalid_outputs:
            with self.subTest(output=output):
                with self.assertRaises(ValidationError):
                    GradeResult.model_validate(output)

        english_feedback = SimpleNamespace(
            model_dump=lambda: {
                "attempt_id": "",
                "agent_grade": "good",
                "brief_feedback": "Correct answer.",
                "hint_used": False,
            }
        )
        with patch("agent_service.review.parse_model", return_value=english_feedback):
            with self.assertRaisesRegex(ValueError, "primary language"):
                grade_answer(self.request)


if __name__ == "__main__":
    unittest.main()
