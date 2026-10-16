"""A same-topic correction can reject saving without losing editable context."""
import copy
import json
import unittest
from unittest.mock import patch

from agent_service.capture_preview import CapturePreview
from agent_service.knowledge_invitation import UPDATE_INSTRUCTION, candidates
from agent_service.schemas import CaptureScopeUpdate, ConversationOutput
from tests import test_knowledge_invitation as fixture
from tests.test_conversation_v2 import intent


class InvitationSaveDeferralTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.KnowledgeInvitationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def update_with_rejected_save(self, *, correction, invalid_quote=False):
        task, old = self.f.start_offer()
        names = ("correction", "reject", "defer") if correction else ("followup", "defer")
        self.f.decision = intent(*names, scope="continue_goal", workflow="source_learning",
            target_task_id=task["task_id"], proposed_actions=[dict(kind="save", disposition="reject",
                target_id=old["id"], version=old["version"], evidence="先不要保存")])
        text = "资料是否适用还要核对发布时间、产品版本和具体使用场景。"
        observations = []
        base = self.f.model

        def response(system, user, schema, **kwargs):
            if not issubclass(schema, ConversationOutput):
                return base(system, user, schema, **kwargs)
            payload = json.loads(user)
            offered = payload["capture_candidates"]
            observations.append(dict(candidates=copy.deepcopy(offered), instruction=UPDATE_INSTRUCTION in system))
            if not offered:
                return ConversationOutput(message=text)
            selected = offered[0]
            quote = "并不在新解释里的引文" if invalid_quote else text
            preview = CapturePreview.model_validate(dict(points=[dict(text=text, evidence_quotes=[text])],
                summary=dict(text=text, evidence_quotes=[text])))
            update = CaptureScopeUpdate(offer_id=selected["id"], version=selected["version"],
                retained_fragment_ids=[] if correction else [f["id"] for f in selected["fragments"]],
                evidence_quotes=[quote], scope_summary=text, preview=preview)
            return ConversationOutput(message=text, learning_concepts=["外部资料作用"], capture_update=update)

        with patch("agent_service.conversation.parse_model", side_effect=response):
            self.f.send("请把刚才的预览补充准确：还要核对发布时间、产品版本和使用场景，先不要保存，也不要进入下一步。")
        return task, old, text, observations

    def test_same_topic_correction_with_rejected_save_replaces_original_preview(self):
        task, old, text, observations = self.update_with_rejected_save(correction=True)
        state = self.f.state()
        updated = self.f.offer()
        self.assertEqual(len(observations), 1)
        self.assertEqual(len(observations[0]["candidates"]), 1)
        self.assertTrue(observations[0]["instruction"])
        self.assertEqual(list(state["capture_offers"]), [old["id"]])
        self.assertGreater(updated["version"], old["version"])
        self.assertEqual(updated["status"], "offered")
        self.assertFalse(updated.get("correction_pending"))
        self.assertEqual(updated["preview"]["points"][0]["text"], text)
        self.assertEqual(updated["preview"]["summary"]["text"], text)
        self.assertIn(text, updated["draft"]["content"])
        self.assertTrue(all(f["kind"] == "explanation" for f in updated["fragments"]))
        self.assertEqual(state["active_task_id"], task["task_id"])
        self.f.capture.assert_not_called()
        self.f.action(old, "capture_save")
        self.f.capture.assert_not_called()
        self.assertNotEqual(self.f.offer()["status"], "saved")

    def test_same_topic_followup_keeps_old_valid_fragments_without_saving(self):
        _, old, text, observations = self.update_with_rejected_save(correction=False)
        updated = self.f.offer()
        self.assertEqual(len(observations[0]["candidates"]), 1)
        self.assertTrue(observations[0]["instruction"])
        self.assertEqual(updated["id"], old["id"])
        self.assertEqual(updated["version"], old["version"] + 1)
        self.assertEqual(updated["status"], "offered")
        self.assertTrue({f["id"] for f in old["fragments"]} <= {f["id"] for f in updated["fragments"]})
        self.assertIn(text, updated["draft"]["content"])
        self.f.capture.assert_not_called()

    def test_rejected_save_does_not_relax_new_quote_check_or_add_repairs(self):
        _, old, _, observations = self.update_with_rejected_save(correction=True, invalid_quote=True)
        state = self.f.state()
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(len(x["candidates"]) == 1 for x in observations))
        run = list(state["runs"].values())[-1]
        self.assertEqual(run["status"], "retryable_failed")
        self.assertEqual(run["error_code"], "RT.MODEL.SCHEMA")
        self.assertEqual(self.f.offer()["id"], old["id"])
        self.assertEqual(self.f.offer()["status"], "invalidated")
        self.assertNotIn("capture_scope_update", run)
        self.f.capture.assert_not_called()

    def test_saving_other_actions_new_topic_and_plain_rejection_stay_separate(self):
        _, old = self.f.start_offer()
        state = self.f.state()
        run = state["runs"][state["messages"][-1]["run_id"]]
        cases = [
            ("save_request", intent("correction", scope="continue_goal", proposed_actions=[dict(kind="save", disposition="request")])),
            ("save_confirm", intent("followup", scope="continue_goal", proposed_actions=[dict(kind="save", disposition="confirm")])),
            ("conditional", intent("correction", scope="continue_goal", proposed_actions=[dict(kind="save", disposition="conditional")])),
            ("other_action", intent("correction", scope="continue_goal", proposed_actions=[dict(kind="set_mode", disposition="reject")])),
            ("plain_reject", intent("reject", "defer", scope="continue_goal", proposed_actions=[dict(kind="save", disposition="reject")])),
            ("different_scope", intent("correction", scope="conversation", proposed_actions=[dict(kind="save", disposition="reject")])),
            ("new_topic", intent("correction", scope="continue_goal", proposed_actions=[dict(kind="save", disposition="reject")]).model_copy(update={"relation": "new_topic"})),
        ]
        for label, decision in cases:
            with self.subTest(case=label):
                self.assertEqual(candidates(self.f.harness, state, run, decision), [])
        self.assertEqual(self.f.offer(), old)
        self.f.capture.assert_not_called()
