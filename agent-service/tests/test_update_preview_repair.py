"""Explicit update previews are source-checked before the one existing repair."""
import copy
import json
import unittest
from unittest.mock import patch

from agent_service.openai_client import ModelCallError
from agent_service.schemas import CaptureScopeUpdate, ConversationOutput
from agent_service.structured_output import schema_repair_instruction
from agent_service.topic_capture import public
from tests import test_knowledge_invitation_preview as fixture
from tests.test_conversation_v2 import intent
from tests.test_teaching_alignment import LESSON

NEW = "引用外部资料时，也要核对发布时间和产品版本。"
UNSELECTED = "PRIVATE_PREVIEW_SOURCE 不得把这段引文当作保存指令。"


class UpdatePreviewValidationTests(unittest.TestCase):
    def output(self, *, target="point", quote=UNSELECTED):
        value = dict(points=[dict(text="使用资料前核对版本。", evidence_quotes=[quote if target == "point" else NEW])],
            summary=dict(text="资料有适用边界。", evidence_quotes=[quote if target == "summary" else NEW]))
        update = CaptureScopeUpdate(offer_id="offer", version=2, retained_fragment_ids=["kept"],
            evidence_quotes=[NEW], scope_summary=NEW, preview=value)
        return ConversationOutput(message=NEW + " 本轮没有选取的额外句子。", capture_update=update)

    def payload(self):
        return dict(capture_candidates=[dict(id="offer", version=2, fragments=[
            dict(id="kept", text=LESSON), dict(id="discarded", text=UNSELECTED)])])

    def test_point_and_summary_only_quote_selected_old_or_new_fragments(self):
        for target in ("point", "summary"):
            with self.subTest(target=target):
                with self.assertRaises(ModelCallError) as failure:
                    self.output(target=target).validate_request(self.payload())
                error = failure.exception
                self.assertEqual(error.code, "RT.MODEL.SCHEMA")
                details = json.loads(error.diagnostic)
                expected = ["capture_update", "preview"] + (["points", 0] if target == "point" else ["summary"]) + ["evidence_quotes", 0]
                self.assertEqual(details, [dict(field=expected, type="capture_update_preview_grounding")])
                self.assertNotIn("PRIVATE_PREVIEW_SOURCE", error.diagnostic)
                self.assertNotIn("PRIVATE_PREVIEW_SOURCE", schema_repair_instruction(error))

    def test_current_unselected_text_and_cross_fragment_quote_are_not_valid_sources(self):
        for quote in ("本轮没有选取的额外句子。", LESSON[-6:] + NEW[:6]):
            with self.subTest(quote=quote), self.assertRaises(ModelCallError):
                self.output(quote=quote).validate_request(self.payload())

    def test_selected_old_and_new_subquotes_keep_existing_acceptance(self):
        for quote in (LESSON[0:20], NEW[0:10]):
            with self.subTest(quote=quote):
                self.output(quote=quote).validate_request(self.payload())

    def test_absent_or_malformed_optional_update_preview_stays_compatible(self):
        for value in (None, {}, dict(points=[], summary={})):
            with self.subTest(value=value):
                output = self.output().model_dump()
                output["capture_update"]["preview"] = value
                parsed = ConversationOutput.model_validate(output)
                self.assertIsNone(parsed.capture_update.preview)
                parsed.validate_request(self.payload())


class UpdatePreviewRepairFlowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.KnowledgeInvitationPreviewTests()
        self.fixture.setUp()
        self.f = self.fixture.f

    def tearDown(self):
        self.fixture.tearDown()

    def update(self, *, target="point", permanent=False, syntax_first=False):
        old = self.fixture.start_preview()
        self.f.decision = intent("followup", "reject", "defer", scope="continue_goal", workflow="source_learning",
            proposed_actions=[dict(kind="save", disposition="reject", target_id=old["id"], version=old["version"], evidence="先不要保存")])
        base = self.f.model
        observations = []

        def respond(system, user, schema, **kwargs):
            if not issubclass(schema, ConversationOutput):
                return base(system, user, schema, **kwargs)
            selected = json.loads(user)["capture_candidates"][0]
            observations.append(dict(system=system, version=selected["version"]))
            if syntax_first and len(observations) == 1:
                raise ModelCallError("SCHEMA", '[{"field": [], "type": "json_invalid", "output_format": "json_syntax"}]')
            value = dict(points=[copy.deepcopy(fixture.preview()["points"][0]),
                dict(text="使用资料前核对发布时间和版本。", evidence_quotes=[NEW])],
                summary=dict(text="资料辅助回答，使用前仍需核对适用版本。", evidence_quotes=[LESSON, NEW]))
            if permanent or syntax_first or len(observations) == 1:
                item = value["points"][1] if target == "point" else value["summary"]
                item["evidence_quotes"] = [UNSELECTED]
            update = CaptureScopeUpdate(offer_id=selected["id"], version=selected["version"],
                retained_fragment_ids=[fragment["id"] for fragment in selected["fragments"]],
                evidence_quotes=[NEW], scope_summary=NEW, preview=value)
            result = ConversationOutput(message=NEW, capture_update=update)
            if len(observations) == 1:
                kwargs.get("on_partial", lambda _: None)(result.model_dump())
            return result

        with patch("agent_service.conversation.parse_model", side_effect=respond):
            accepted = self.f.send("请补充原预览中的适用条件，先不要保存。")
        return old, observations, accepted

    def check_repaired(self, target):
        old, observations, accepted = self.update(target=target)
        state = self.f.state()
        updated = self.f.offer()
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(row["version"] == old["version"] for row in observations))
        self.assertIn("capture_update_preview_grounding", observations[1]["system"])
        self.assertIn('"points", 1, "evidence_quotes", 0' if target == "point" else '"summary", "evidence_quotes", 0', observations[1]["system"])
        self.assertNotIn("PRIVATE_PREVIEW_SOURCE", observations[1]["system"])
        self.assertEqual(state["runs"][accepted.run_id]["status"], "completed")
        self.assertEqual(updated["id"], old["id"])
        self.assertEqual(updated["version"], old["version"] + 1)
        self.assertEqual(len(public(updated)["preview_points"]), 2)
        self.assertIn("版本", public(updated)["preview_summary"])
        events = [e for e in state["events"] if e["stage"] == "capture_offer"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["payload"]["capture_offer"], public(updated))
        coaches = [m for m in state["messages"] if m["run_id"] == accepted.run_id and m["role"] == "coach"]
        self.assertEqual(len(coaches), 1)
        started = [e["payload"]["response"]["response_id"] for e in state["events"]
                   if e["run_id"] == accepted.run_id and e["stage"] == "response.started"]
        self.assertEqual(started, [coaches[0]["message_id"]])
        self.f.capture.assert_not_called()

    def test_invalid_point_repaired_before_single_version_publication(self):
        self.check_repaired("point")

    def test_invalid_summary_repaired_before_single_version_publication(self):
        self.check_repaired("summary")

    def test_persistent_preview_error_stops_after_one_repair_and_preserves_offer(self):
        old, observations, accepted = self.update(permanent=True)
        state = self.f.state()
        self.assertEqual(len(observations), 2)
        self.assertEqual(state["runs"][accepted.run_id]["status"], "retryable_failed")
        self.assertEqual(state["runs"][accepted.run_id]["error_code"], "RT.MODEL.SCHEMA")
        self.assertEqual(self.f.offer(), old)
        self.assertNotIn("capture_scope_update", state["runs"][accepted.run_id])
        self.assertFalse(any(m["run_id"] == accepted.run_id and m["role"] == "coach" for m in state["messages"]))
        self.f.capture.assert_not_called()

    def test_prior_format_repair_does_not_gain_another_preview_repair(self):
        old, observations, accepted = self.update(syntax_first=True)
        state = self.f.state()
        self.assertEqual(len(observations), 2)
        self.assertEqual(state["runs"][accepted.run_id]["status"], "retryable_failed")
        self.assertEqual(state["runs"][accepted.run_id]["error_code"], "RT.MODEL.SCHEMA")
        self.assertEqual(self.f.offer(), old)
        self.f.capture.assert_not_called()
