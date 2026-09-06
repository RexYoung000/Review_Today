"""Token-policy regression with full-size synthetic histories, no provider calls."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

import tests.test_conversation_v2 as fixtures
from agent_service.context_budget import count_request, policy, prepare
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore
from agent_service.schemas import ConversationSummary, ConversationOutput, IntentDecision


class ContextCompactionTests(unittest.TestCase):
    setUp = fixtures.ConversationTests.setUp
    tearDown = fixtures.ConversationTests.tearDown
    model = fixtures.ConversationTests.model
    send = fixtures.ConversationTests.send
    state = fixtures.ConversationTests.state
    control = fixtures.ConversationTests.control

    def seed(self, pairs=24, size=10000):
        self.send()
        with self.store.transaction(self.sid) as data:
            base = copy.deepcopy(next(iter(data['runs'].values())))
            data['messages'] = []
            data['runs'] = {}
            for i in range(pairs):
                rid, mid = str(uuid.uuid4()), str(uuid.uuid4())
                run = copy.deepcopy(base)
                run.update(run_id=rid, input_ids=[mid], steps={})
                data['runs'][rid] = run
                for role in ('user', 'coach'):
                    data['messages'].append(dict(message_id=mid if role == 'user' else str(uuid.uuid4()),
                        role=role, content=f'{role}-{i}:' + 'a' * size + f' TAIL-{i}', run_id=rid, context={}))
            data['summary'] = ''
            data['summary_version'] = 0
            data['summarized_message_ids'] = []
            data['summarized_count'] = 0
        self.calls.clear()

    def test_many_short_turns_and_long_message_tail_are_preserved_without_compaction(self):
        self.seed(pairs=30, size=4000)
        self.harness.maintain_summary(self.sid)
        self.assertEqual(self.state()['summary_version'], 0)
        self.send('回问最早原文的末尾')
        context = next(c for schema, c in self.calls if schema is IntentDecision)
        self.assertEqual(len(context['recent_messages']), 60)
        self.assertTrue(context['recent_messages'][0]['content'].endswith('TAIL-0'))

    def test_token_trigger_retains_whole_recent_turns_and_raw_history_across_restart(self):
        self.seed()
        before = copy.deepcopy(self.state()['messages'])
        self.harness.maintain_summary(self.sid)
        data = self.state()
        self.assertEqual(data['summary_version'], 1)
        self.assertEqual(data['messages'], before)
        covered = set(data['summarized_message_ids'])
        self.assertTrue(covered)
        for i in range(0, len(before), 2):
            self.assertEqual(before[i]['message_id'] in covered, before[i+1]['message_id'] in covered)
        self.assertNotIn(before[-1]['message_id'], covered)
        summary_calls = [c for schema, c in self.calls if schema is ConversationSummary]
        self.assertTrue(summary_calls[0]['messages'][0]['content'].endswith('TAIL-0'))
        self.store = ConversationStore(self.tasks)
        self.harness = ConversationHarness(self.store)
        self.send('继续')
        context = [c for schema, c in self.calls if schema is IntentDecision][-1]
        self.assertTrue(context['summary'])
        self.assertFalse(covered & {m['message_id'] for m in context['recent_messages']})
        count = count_request('', json.dumps(context, ensure_ascii=False))
        self.assertLess(count, 160000)
        self.assertGreater(count, 128000)

    def test_foreground_compacts_when_new_input_crosses_threshold_and_does_not_recompact_next_turn(self):
        self.seed(pairs=20)
        self.send('b' * 48000)
        self.assertEqual(self.state()['summary_version'], 1)
        summary_calls = len([s for s, _ in self.calls if s is ConversationSummary])
        self.send('继续')
        self.assertEqual(len([s for s, _ in self.calls if s is ConversationSummary]), summary_calls)
        run = list(self.state()['runs'].values())[-1]
        self.assertEqual(run['context_capacity']['input_budget'], 256000)
        self.assertEqual(run['context_capacity']['compact_threshold'], 220000)

    def test_failed_summary_preserves_history_and_hard_limit_prevents_answer(self):
        self.seed(pairs=30)
        before = copy.deepcopy(self.state()['messages'])
        normal = self.model
        def fail(system, prompt, schema, **kwargs):
            if schema is ConversationSummary: raise RuntimeError('timeout')
            return normal(system, prompt, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=fail):
            run = self.send('继续')
        data = self.state()
        self.assertEqual(data['summary_version'], 0)
        self.assertEqual(data['messages'][:len(before)], before)
        self.assertEqual(data['runs'][run.run_id]['status'], 'retryable_failed')
        self.assertFalse(any(schema is IntentDecision for schema, _ in self.calls))

    def test_background_summary_is_discarded_after_new_input_or_archive(self):
        for change in ('input', 'archive'):
            with self.subTest(change=change):
                self.seed()
                normal = self.model
                def race(system, prompt, schema, **kwargs):
                    result = normal(system, prompt, schema, **kwargs)
                    if schema is ConversationSummary:
                        if change == 'input': self.send('新的纠正', drain=False)
                        else:
                            with self.store.transaction(self.sid) as data:
                                data['status'] = 'archived'
                                data['lifecycle_revision'] += 1
                    return result
                with patch('agent_service.conversation.parse_model', side_effect=race):
                    self.harness.maintain_summary(self.sid)
                self.assertEqual(self.state()['summary_version'], 0)
                with self.store.transaction(self.sid) as data:
                    data.update(status='active', foreground=None, paused=False)

    def test_empty_or_oversize_summary_does_not_advance_coverage(self):
        for output in ('', 'x' * 10000):
            self.seed()
            with patch('agent_service.conversation.parse_model', return_value=ConversationSummary(
                    goal='学习', confirmed_decisions=[], open_questions=[], summary=output)):
                self.harness.maintain_summary(self.sid)
            self.assertEqual(self.state()['summary_version'], 0)
            self.assertFalse(self.state().get('summarized_message_ids'))

    def test_failed_turn_is_not_summarized_or_dropped(self):
        self.seed()
        with self.store.transaction(self.sid) as data:
            first = next(iter(data['runs'].values()))
            first['status'] = 'retryable_failed'
            first_ids = {m['message_id'] for m in data['messages'] if m['run_id'] == first['run_id']}
        self.harness.maintain_summary(self.sid)
        data = self.state()
        self.assertEqual(data['summary_version'], 1)
        self.assertFalse(first_ids & set(data['summarized_message_ids']))
        self.assertEqual(data['summarized_count'], 0)

    def test_ack_and_checkpoint_restore_keep_compaction_coverage(self):
        self.seed(pairs=36)
        self.harness.maintain_summary(self.sid)
        with self.store.transaction(self.sid) as data:
            data['last_acked_seq'] = self.store.last_seq(data)
            self.store.compact_acknowledged(data)
        data = self.state()
        ids = {m['message_id'] for m in data['messages']}
        self.assertTrue(set(data['summarized_message_ids']) <= ids)
        self.assertLess(len(data['messages']), 72)
        from agent_service.checkpoint_delta import recovery_projection
        restored = recovery_projection(data)
        self.assertEqual(restored['summarized_message_ids'], data['summarized_message_ids'])
        self.send('继续查看原文中的主题')
        recent = [c for schema, c in self.calls if schema is IntentDecision][-1]['recent_messages']
        self.assertFalse(set(data['summarized_message_ids']) & {m['message_id'] for m in recent})

    def test_smaller_model_triggers_earlier_and_summary_batches_obey_its_window(self):
        self.seed(pairs=24, size=10000)
        normal = self.model
        def check(system, prompt, schema, **kwargs):
            if schema is ConversationSummary:
                self.assertLessEqual(count_request(system, prompt, schema.model_json_schema()), 123904)
                self.assertEqual(kwargs['max_output_tokens'], 4096)
            return normal(system, prompt, schema, **kwargs)
        with patch('agent_service.conversation.configured_window', return_value=128000), \
             patch('agent_service.conversation.parse_model', side_effect=check):
            self.harness.maintain_summary(self.sid)
        self.assertEqual(self.state()['summary_version'], 1)
        self.assertEqual(len([s for s, _ in self.calls if s is ConversationSummary]), 2)

    def test_invalidated_memory_cannot_publish_late_summary(self):
        self.seed()
        normal = self.model
        def invalidate(system, prompt, schema, **kwargs):
            result = normal(system, prompt, schema, **kwargs)
            if schema is ConversationSummary:
                with self.store.transaction(self.sid) as data:
                    next(iter(data['runs'].values()))['memory_invalidated'] = True
                    self.harness._invalidate_memory(data)
            return result
        with patch('agent_service.conversation.parse_model', side_effect=invalidate):
            self.harness.maintain_summary(self.sid)
        self.assertEqual(self.state()['summary'], '')
        self.assertEqual(self.state()['summarized_message_ids'], [])

    def test_stop_during_foreground_compaction_cancels_and_cannot_publish_summary(self):
        self.seed()
        normal = self.model
        import threading
        closed = threading.Event()
        def stop(system, prompt, schema, **kwargs):
            if schema is ConversationSummary:
                kwargs['on_cancel_handle'](closed.set)
                foreground = self.state()['foreground']
                self.control(foreground, 'stop')
            return normal(system, prompt, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=stop):
            run = self.send('继续')
        self.assertTrue(closed.is_set())
        self.assertEqual(self.state()['summary_version'], 0)
        self.assertEqual(self.state()['runs'][run.run_id]['status'], 'interrupted')
        self.assertFalse(any(s is IntentDecision for s, _ in self.calls))

    def test_legacy_summary_does_not_hide_available_raw_message_tails(self):
        self.seed(pairs=10, size=4000)
        with self.store.transaction(self.sid) as data:
            data['summary'] = '旧的简略摘要'
            data['summary_version'] = 1
            data['summarized_count'] = 8
        self.send('回问旧材料尾部')
        context = [c for schema, c in self.calls if schema is IntentDecision][-1]
        self.assertTrue(context['recent_messages'][0]['content'].endswith('TAIL-0'))
        self.assertEqual(context['summary'], '旧的简略摘要')

    def test_smaller_window_and_no_silent_history_drop(self):
        self.assertEqual(policy(128000), (123904, 106480, 69696))
        with self.assertRaisesRegex(ValueError, 'INPUT_TOO_LARGE'):
            prepare('rules', json.dumps({'recent_messages': [{'role':'user', 'content':'a'*600000}]}))
        with self.assertRaisesRegex(ValueError, 'INPUT_TOO_LARGE'):
            prepare('rules', json.dumps({'summary': 'a'*600000}))
        _, capacity = prepare('rules', 'hello', window=128000)
        self.assertEqual(capacity['input_budget'], 123904)
