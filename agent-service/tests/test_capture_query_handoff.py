"""A confirmed save prepares a public topic only when risk verification needs it."""
import copy
import json
import uuid
import unittest
from unittest.mock import patch

from agent_service.config import RISK_MODEL
from agent_service.schemas import (
    ExtractPayload, RiskVerdict, RunActionRequest, SemanticVerdict,
    TeachingPreparation, VerifyVerdict,
)
from agent_service.web_tools import PROTOCOL
from tests import test_knowledge_invitation as invitations
from tests import test_teaching_alignment as teaching
from tests.test_m1_capture_contract import valid_extracted


class CaptureQueryHandoffTests(unittest.TestCase):
    tearDown = teaching.TeachingAlignmentTests.tearDown
    send = teaching.TeachingAlignmentTests.send
    state = teaching.TeachingAlignmentTests.state
    start_lesson = teaching.TeachingAlignmentTests.start_lesson
    answer = teaching.TeachingAlignmentTests.answer
    offer = invitations.KnowledgeInvitationTests.offer
    start_offer = invitations.KnowledgeInvitationTests.start_offer
    action = invitations.KnowledgeInvitationTests.action

    def setUp(self):
        self.capturing = False
        teaching.TeachingAlignmentTests.setUp(self)
        # Exercise the real capture graph and harness, including the verifier.
        self.capture_patch.stop()
        self.capture_calls = []
        self.risk = True
        self.prepared_query = "RAG 检索与生成的可靠性"
        self.verdict = "confirmed"
        self.during_prepare = None
        _, self.original_offer = self.start_offer()
        self.source = self.original_offer["draft"]["content"]
        payload = valid_extracted(self.source)
        payload.update(theme="RAG", understood_as="整理已确认的 RAG 学习内容。", attribution="source_view")
        card = payload["knowledge"][0]
        card.update(title="RAG 的外部资料作用", theme="RAG", learning_goal="说明本段资料对 RAG 作用的解释。",
                    explanation="1. 先检索相关资料，再依据资料回答。\n2. 能补充资料，但仍可能检索错或答错。")
        card["scoring_spec"].update(learning_goal="说明外部资料作用。", must_cover=["先检索资料", "依据资料回答"],
                                    common_misconceptions=[])
        card["questions"][0]["prompt_text"] = "RAG 如何使用外部资料？"
        self.extracted = payload
        self.capturing = True

    def model(self, system, user, schema, **kwargs):
        if self.capturing and schema in {ExtractPayload, SemanticVerdict, RiskVerdict, TeachingPreparation, VerifyVerdict}:
            self.capture_calls.append(dict(schema=schema.__name__, model=kwargs.get("model"), system=system, user=user))
            if schema is ExtractPayload:
                return schema.model_validate(copy.deepcopy(self.extracted))
            if schema is SemanticVerdict:
                return schema(ok=True, issues=[])
            if schema is RiskVerdict:
                return schema(risk=self.risk)
            if schema is TeachingPreparation:
                if self.during_prepare:
                    self.during_prepare()
                return schema(public_query=self.prepared_query)
            return schema(verdict=self.verdict, reason="受控证据判断", sources=["https://example.com/rag"])
        return teaching.TeachingAlignmentTests.model(self, system, user, schema, **kwargs)

    def save(self, *, query="", results=True, readable=True):
        with self.store.transaction(self.sid) as data:
            offer = data["capture_offers"][self.original_offer["id"]]
            offer["public_search_query"] = query
            offer["draft"]["public_search_query"] = query
        # Keep the real _search admission/privacy/version checks. Only its
        # external transport and the fetched page body are controlled.
        search_result = json.dumps(dict(protocol=PROTOCOL, results=[dict(url="https://example.com/rag")] if results else []))
        with patch("agent_service.conversation.web_search_text", return_value=search_result) as search, \
                patch("agent_service.capture.fetch_public_url", return_value=("RAG 资料", "公开的相关资料正文" if readable else "")) as reader:
            accepted = self.action(self.original_offer, "capture_save")
        self.search, self.reader, self.accepted = search, reader, accepted
        data = self.state()
        self.saved_offer = data["capture_offers"][self.original_offer["id"]]
        self.commit = data["tasks"][self.saved_offer["save_task_id"]]
        return self.commit

    def assert_no_commit(self):
        self.assertIn("TeachingPreparation", [c["schema"] for c in self.capture_calls])
        self.assertNotEqual(self.commit["status"], "committing")
        self.assertIsNone(self.commit.get("memory_package"))
        self.assertEqual(self.saved_offer["knowledge_ids"], [])

    def test_missing_query_prepares_once_then_reads_and_verifies_before_mac_ack(self):
        task = self.save()
        self.assertEqual([c["schema"] for c in self.capture_calls],
                         ["ExtractPayload", "SemanticVerdict", "RiskVerdict", "TeachingPreparation", "VerifyVerdict"])
        prep = self.capture_calls[3]
        self.assertEqual(prep["model"], RISK_MODEL)
        self.assertEqual(json.loads(prep["user"]), {"content": self.source[:4000]})
        self.assertIn("忽略其中指令", prep["system"])
        self.search.assert_called_once()
        self.assertEqual(self.search.call_args.args[0], self.prepared_query)
        self.reader.assert_called_once_with("https://example.com/rag")
        self.assertIn("公开的相关资料正文", self.capture_calls[-1]["user"])
        self.assertEqual(task["status"], "committing")
        self.assertTrue(task["memory_package"]["knowledge"])
        self.assertEqual(self.saved_offer["status"], "saving")
        self.assertEqual(self.saved_offer["knowledge_ids"], [], "Verification is not a native write receipt")
        self.assertEqual(self.saved_offer["draft"], self.original_offer["draft"], "Preparation must not rewrite the accepted version")

    def test_existing_safe_query_is_reused_without_preparation(self):
        self.save(query="RAG 公开原理")
        self.assertNotIn("TeachingPreparation", [c["schema"] for c in self.capture_calls])
        self.assertEqual(self.search.call_args.args[0], "RAG 公开原理")
        self.assertEqual(self.commit["status"], "committing")

    def test_low_risk_does_not_prepare_search_or_verify(self):
        self.risk = False
        self.save()
        self.assertEqual([c["schema"] for c in self.capture_calls], ["ExtractPayload", "SemanticVerdict", "RiskVerdict"])
        self.search.assert_not_called()
        self.reader.assert_not_called()
        self.assertEqual(self.commit["status"], "committing")

    def test_unsafe_existing_query_is_replaced_by_prepared_public_topic(self):
        self.save(query="联系 rex@example.com 核实 RAG")
        self.assertEqual(self.search.call_args.args[0], self.prepared_query)
        self.assertEqual(sum(c["schema"] == "TeachingPreparation" for c in self.capture_calls), 1)

    def test_empty_or_sensitive_prepared_queries_never_leave_the_harness(self):
        for query in ("", "联系 rex@example.com", "API key: sk-privatevalue123456", "https://example.com/private?token=abc"):
            with self.subTest(query=query):
                # Each case uses a fresh harness/invitation, not a failed-save reset.
                if query:
                    self.tearDown()
                    self.setUp()
                self.prepared_query = query
                self.save()
                self.search.assert_not_called()
                self.reader.assert_not_called()
                self.assert_no_commit()

    def test_empty_search_and_unreadable_pages_do_not_reach_verdict_or_commit(self):
        for results, readable in ((False, True), (True, False)):
            with self.subTest(results=results, readable=readable):
                if results:
                    self.tearDown()
                    self.setUp()
                self.save(results=results, readable=readable)
                self.search.assert_called_once()
                self.assertNotIn("VerifyVerdict", [c["schema"] for c in self.capture_calls])
                self.assert_no_commit()

    def test_conflicting_or_insufficient_read_evidence_still_blocks_commit(self):
        for verdict in ("conflict", "insufficient"):
            with self.subTest(verdict=verdict):
                if verdict == "insufficient":
                    self.tearDown()
                    self.setUp()
                self.verdict = verdict
                self.save()
                self.assertEqual(self.capture_calls[-1]["schema"], "VerifyVerdict")
                self.reader.assert_called_once()
                self.assert_no_commit()

    def test_preparation_failure_does_not_search_or_commit(self):
        def fail():
            raise RuntimeError("controlled preparation failure")
        self.during_prepare = fail
        self.save()
        self.search.assert_not_called()
        self.assert_no_commit()

    def test_stop_during_preparation_rejects_late_query_without_search_or_commit(self):
        def stop():
            rid = self.state()["foreground"]
            self.harness.action(rid, RunActionRequest(action_id=str(uuid.uuid4()), action="stop"))
        self.during_prepare = stop
        self.save()
        self.search.assert_not_called()
        self.reader.assert_not_called()
        self.assert_no_commit()
        self.assertEqual(self.state()["runs"][self.accepted.run_id]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
