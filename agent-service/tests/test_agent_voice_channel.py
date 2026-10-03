"""Voice is an input channel, never a different Agent or permission model."""
import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from agent_service.conversation_model_call import VOICE_PUBLIC_STYLE
from agent_service.schemas import ConversationOutput, IntentDecision, SessionMessageRequest
from tests import test_conversation_v2 as fixtures
from tests.test_conversation_v2 import intent


class VoiceChannelContracts(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ConversationTests()
        self.fixture.setUp()
        self.h = self.fixture.harness
        self.sid = self.fixture.sid

    def tearDown(self):
        self.fixture.tearDown()

    def send(self, channel='text', **kwargs):
        body = SessionMessageRequest(client_message_id=str(uuid4()), content='解释一下光合作用', input_channel=channel, **kwargs)
        return body, self.h.accept(self.sid, body)

    def test_channel_is_independent_of_content_type_and_defaults_to_text(self):
        body = SessionMessageRequest(client_message_id=str(uuid4()), content='你好')
        self.assertEqual((body.input_channel, body.content_type), ('text', 'text'))
        body.input_channel = 'voice'
        self.assertEqual(body.content_type, 'text')
        with self.assertRaises(ValidationError):
            SessionMessageRequest(client_message_id=str(uuid4()), content='你好', input_channel='microphone')

    def test_historical_text_fingerprint_remains_valid_but_channel_replay_conflicts(self):
        body, accepted = self.send()
        expected = hashlib.sha256(json.dumps(dict(content=body.content, operation=None), sort_keys=True).encode()).hexdigest()
        with self.h.store.transaction(self.sid) as data:
            self.assertEqual(data['message_receipts'][body.client_message_id]['fingerprint'], expected)
            data['messages'][0].pop('input_channel')
            data['runs'][accepted.run_id].pop('input_channel')
        self.assertEqual(self.h.accept(self.sid, body).run_id, accepted.run_id)
        with self.assertRaisesRegex(ValueError, 'IDEMPOTENCY_CONFLICT'):
            self.h.accept(self.sid, body.model_copy(update={'input_channel': 'voice'}))

    def test_voice_to_text_replay_conflicts_with_or_without_receipt(self):
        body, _ = self.send('voice')
        self.h.accept(self.sid, body)
        for has_receipt in (True, False):
            if not has_receipt:
                with self.h.store.transaction(self.sid) as data:
                    data['message_receipts'].clear()
            with self.assertRaisesRegex(ValueError, 'IDEMPOTENCY_CONFLICT'):
                self.h.accept(self.sid, body.model_copy(update={'input_channel': 'text'}))

    def test_steering_uses_latest_channel_but_queued_input_keeps_its_own(self):
        first_body, first = self.send('voice')
        self.assertEqual(self.h.store.get(self.sid)['runs'][first.run_id]['voice_input_ids'], [first_body.client_message_id])
        _, steer = self.send('text')
        queued_body, queued = self.send('voice', delivery='queue')
        state = self.h.store.get(self.sid)
        self.assertEqual(first.run_id, steer.run_id)
        self.assertEqual(state['runs'][first.run_id]['input_channel'], 'text')
        self.assertEqual(state['runs'][first.run_id]['voice_input_ids'], [])
        self.assertEqual(state['runs'][queued.run_id]['input_channel'], 'voice')
        self.assertEqual(state['runs'][queued.run_id]['voice_input_ids'], [queued_body.client_message_id])
        self.assertEqual([m['input_channel'] for m in state['messages']], ['voice', 'text', 'voice'])

    def test_model_routed_queue_split_restores_each_original_channel(self):
        self.fixture.decision = intent('queue', 'question')
        _, first = self.send('text')
        later_body, _ = self.send('voice')
        self.h.drain(self.sid)
        state = self.h.store.get(self.sid)
        later_id = state['message_receipts'][later_body.client_message_id]['run_id']
        self.assertNotEqual(first.run_id, later_id)
        self.assertEqual(state['runs'][first.run_id]['input_channel'], 'text')
        self.assertEqual(state['runs'][first.run_id]['voice_input_ids'], [])
        self.assertEqual(state['runs'][later_id]['input_channel'], 'voice')
        self.assertEqual(state['runs'][later_id]['voice_input_ids'], [later_body.client_message_id])

    def test_consumed_stop_input_does_not_change_resumable_answer_channel(self):
        self.fixture.decision = intent('stop')
        _, first = self.send('voice')
        self.send('text')
        self.h.drain(self.sid)
        run = self.h.store.get(self.sid)['runs'][first.run_id]
        self.assertEqual(len(run['input_ids']), 1)
        self.assertEqual(run['input_channel'], 'voice')
        self.assertEqual(run['status'], 'interrupted')

    def test_voice_style_reaches_public_answer_only_and_does_not_leak_into_text(self):
        self.fixture.decision = intent('question')
        systems = []
        def model(system, user, schema, **kwargs):
            systems.append((schema, system))
            return self.fixture.model(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=model):
            self.send('voice')
            self.h.drain(self.sid)
            voice_systems = list(systems)
            systems.clear()
            self.send('text')
            self.h.drain(self.sid)
        self.assertTrue(any(schema is ConversationOutput and VOICE_PUBLIC_STYLE in system for schema, system in voice_systems))
        self.assertTrue(any(schema is IntentDecision for schema, _ in voice_systems))
        self.assertTrue(all(VOICE_PUBLIC_STYLE not in system for schema, system in voice_systems if schema is IntentDecision))
        self.assertTrue(all(VOICE_PUBLIC_STYLE not in system for _, system in systems))

    def test_capture_continuation_keeps_prompt_anchor_but_uses_current_voice_operation(self):
        from agent_service.topic_capture import queue_next
        body, _ = self.send('text')
        current_input = str(uuid4())
        offer = dict(anchor_message_id=body.client_message_id, next_request='继续解释刚才的问题', lifecycle_revision=0,
                     continuation_input_channel='voice', continuation_voice_input_ids=[current_input])
        with self.h.store.transaction(self.sid) as data:
            queue_next(self.h, data, offer)
            continuation = data['runs'][offer['continuation_run_id']]
            self.assertEqual(continuation['input_channel'], 'voice')
            self.assertEqual(continuation['input_ids'], [body.client_message_id])
            self.assertEqual(continuation['voice_input_ids'], [current_input])
            self.assertEqual(continuation['status'], 'queued')
            self.assertIsNone(data['draft'])
            self.assertIsNone(data['pending'])

    def test_voice_continue_binds_restored_run_to_new_input_without_rewriting_prompt(self):
        old_body, old = self.send('text')
        self.fixture.control(old.run_id, 'stop')
        self.fixture.decision = intent('continue')
        body, control = self.send('voice')
        self.h.drain(self.sid)
        state = self.h.store.get(self.sid)
        self.assertNotEqual(old.run_id, control.run_id)
        self.assertEqual(state['runs'][old.run_id]['voice_input_ids'], [body.client_message_id])
        self.assertEqual(state['runs'][old.run_id]['input_ids'], [old_body.client_message_id])
        self.assertEqual(state['runs'][control.run_id]['voice_input_ids'], [body.client_message_id])
        self.assertEqual(state['runs'][old.run_id]['input_channel'], 'voice')

    def capture_fixture(self):
        from tests import test_topic_capture
        case = test_topic_capture.TopicCaptureTests()
        case.f = self.fixture
        return case

    def capture_action(self, offer, action):
        body = SessionMessageRequest(client_message_id=str(uuid4()), content='处理当前收尾', input_channel='voice',
            operation=dict(kind=action, target_id=offer['id'], version=offer['version']))
        accepted = self.h.accept(self.sid, body)
        self.h.drain(self.sid)
        return body, accepted

    def test_capture_later_continuation_is_bound_to_current_voice_action_not_old_anchor(self):
        case = self.capture_fixture()
        offer = case.close('接下来讲 Agent')
        body, _ = self.capture_action(offer, 'capture_later')
        state = self.h.store.get(self.sid)
        continuation = state['runs'][state['capture_offers'][offer['id']]['continuation_run_id']]
        self.assertEqual(continuation['voice_input_ids'], [body.client_message_id])
        self.assertEqual(continuation['input_ids'], [offer['anchor_message_id']])
        self.assertNotEqual(body.client_message_id, offer['anchor_message_id'])

    def test_save_ack_keeps_voice_action_provenance_until_continuation_is_created(self):
        from tests.test_m1_capture_contract import committing_result
        case = self.capture_fixture()
        offer = case.close('接下来讲 Agent')
        self.fixture.capture.return_value = committing_result(offer['draft']['content'])
        body, _ = self.capture_action(offer, 'capture_save')
        saved = self.h.store.get(self.sid)['capture_offers'][offer['id']]
        self.assertEqual(saved['status'], 'saving')
        self.assertNotIn('continuation_run_id', saved)
        case.ack(saved)
        state = self.h.store.get(self.sid)
        continuation = state['runs'][state['capture_offers'][offer['id']]['continuation_run_id']]
        self.assertEqual(continuation['voice_input_ids'], [body.client_message_id])
        self.assertEqual(continuation['input_ids'], [offer['anchor_message_id']])

    def test_voice_origin_is_exposed_in_public_run_events_and_recovery_snapshot(self):
        from agent_service import main
        body, accepted = self.send('voice')
        with patch.object(main, 'conversation_harness', self.h):
            page = main.session_events(self.sid)
            public = main.get_run(accepted.run_id)
        self.assertEqual(public['voice_input_ids'], [body.client_message_id])
        self.assertEqual(page['runs'][0]['voice_input_ids'], [body.client_message_id])
        restored = json.loads(json.dumps(self.h.export_snapshot(self.sid)))
        self.assertEqual(restored['checkpoint']['runs'][accepted.run_id]['voice_input_ids'], [body.client_message_id])


if __name__ == '__main__':
    unittest.main()
