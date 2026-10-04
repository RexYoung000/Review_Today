"""Optional previews follow actual invitation publication, scope and receipts."""
import copy
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import agent_service.main as main
from agent_service.capture_preview import CapturePreview, grounded_fields
from agent_service.judgment_grading import JudgmentFeedback, evaluate
from agent_service.schemas import CaptureScopeUpdate, ConversationOutput, MasteryEvaluation
from agent_service.topic_capture import public
from tests import test_capture_evaluation_quotes as quotes_fixture
from tests import test_knowledge_invitation as fixture
from tests.test_conversation_v2 import intent
from tests.test_m1_capture_contract import committing_result
from tests.test_teaching_alignment import LESSON


def preview(text='RAG 用找到的资料辅助回答，但仍需核对结果。', quote=LESSON):
    return dict(points=[dict(text='检索到的资料可以作为回答依据。', evidence_quotes=[quote])],
                summary=dict(text=text, evidence_quotes=[quote]))


class PreviewSchemaTests(unittest.TestCase):
    def feedback(self, **changes):
        return dict(correctness='正确', completeness='足够', expression='清楚', transfer='未检查',
                    feedback='答对了。', **changes)

    def test_legacy_scoring_and_update_outputs_need_no_preview(self):
        for value in (MasteryEvaluation(passed=True, **self.feedback()), JudgmentFeedback(**self.feedback())):
            self.assertIsNone(value.capture_preview)
            value.validate_request({})
        old = CaptureScopeUpdate(offer_id='offer', version=1, evidence_quotes=['真实补充'], scope_summary='真实补充')
        self.assertIsNone(old.preview)

    def test_malformed_optional_preview_does_not_fail_answer_or_scope_selection(self):
        invalid = [42, '一句话', {}, dict(points=[], summary={}),
                   dict(points=[dict(text=' ', evidence_quotes=['真实'])], summary=dict(text='总结', evidence_quotes=['真实'])),
                   dict(points=[dict(text='真实', evidence_quotes=[''])], summary=dict(text='总结', evidence_quotes=['真实'])),
                   dict(points=[dict(text='过长' * 100, evidence_quotes=['真实'])], summary=dict(text='总结', evidence_quotes=['真实']))]
        for raw in invalid:
            with self.subTest(raw=raw):
                value = MasteryEvaluation(passed=True, **self.feedback(capture_preview=raw))
                self.assertTrue(value.passed)
                self.assertIsNone(value.capture_preview)
                self.assertIsNone(JudgmentFeedback(**self.feedback(capture_preview=raw)).capture_preview)
                update = CaptureScopeUpdate(offer_id='offer', version=1, evidence_quotes=['真实补充'],
                                            scope_summary='真实补充', preview=raw)
                self.assertIsNone(update.preview)

    def test_every_point_and_summary_requires_its_own_current_fragment_witness(self):
        value = preview()
        self.assertEqual(grounded_fields(value, [dict(text=LESSON)])['preview_summary'], value['summary']['text'])
        for target in ('point', 'summary'):
            bad = copy.deepcopy(value)
            item = bad['points'][0] if target == 'point' else bad['summary']
            item['evidence_quotes'] = ['未选中的旧错误']
            with self.subTest(target=target):
                self.assertEqual(grounded_fields(bad, [dict(text=LESSON)]), {})
        self.assertEqual(grounded_fields(value, [dict(text=None)]), {})

    def test_jev_keeps_preview_in_the_existing_single_feedback_call(self):
        f = quotes_fixture.RubricFallbackScopeTests()
        task = f.task()
        quote = '参考答案：语义匹配比较含义。'
        value = quotes_fixture.feedback_values(capture_quotes=[quote], capture_preview=preview('语义匹配比较意思。', quote))
        h, calls, _, _ = f.harness(task, value)
        output = evaluate(h, 'session', 'run', 1, task, '比较含义。', '原判题规则')
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(output.capture_preview)
        self.assertEqual(output.capture_preview.summary.text, '语义匹配比较意思。')


class KnowledgeInvitationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.KnowledgeInvitationTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def start_preview(self, value=None):
        self.f.start_lesson()
        base = self.f.model
        def score(system, user, schema, **kwargs):
            output = base(system, user, schema, **kwargs)
            if schema is MasteryEvaluation:
                output.capture_quotes = [LESSON]
                output.capture_preview = CapturePreview.model_validate(value if value is not None else preview())
            return output
        with patch('agent_service.conversation.parse_model', side_effect=score):
            self.f.answer()
        return self.f.offer()

    def followup(self, text, value, *, correction=False):
        self.f.decision = intent('correction' if correction else 'followup', scope='continue_goal', workflow='source_learning')
        base = self.f.model
        def response(system, user, schema, **kwargs):
            if issubclass(schema, ConversationOutput):
                selected = json.loads(user)['capture_candidates'][0]
                update = CaptureScopeUpdate(offer_id=selected['id'], version=selected['version'],
                    retained_fragment_ids=[] if correction else [f['id'] for f in selected['fragments']],
                    evidence_quotes=[text], scope_summary=text, preview=value)
                return ConversationOutput(message=text, learning_concepts=['外部资料作用'], capture_update=update)
            return base(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=response):
            return self.f.send('请纠正刚才的说法' if correction else '继续解释这个知识点')

    def test_first_preview_reaches_actual_event_and_http_poll_without_card_generation(self):
        offer = self.start_preview()
        state = self.f.state()
        expected = public(offer)
        self.assertEqual(expected['preview_points'], ['检索到的资料可以作为回答依据。'])
        self.assertEqual(expected['preview_summary'], preview()['summary']['text'])
        self.assertNotIn('preview', expected)
        self.assertNotIn('preview_version', expected)
        event = next(e for e in reversed(state['events']) if e['stage'] == 'capture_offer')
        self.assertEqual(event['payload']['capture_offer'], expected)
        # Do not enter the app lifespan: startup probes/recovery are outside this
        # isolated HTTP contract and could call configured external providers.
        with patch.object(main, 'conversation_harness', self.f.harness):
            client = TestClient(main.app)
            try:
                page = client.get(f'/v2/sessions/{self.f.sid}/events').json()
            finally:
                client.close()
        self.assertEqual(page['capture_offers'], [expected])
        self.assertEqual(sum(schema is MasteryEvaluation for schema, _ in self.f.calls), 1)
        self.assertIsNone(state['draft'])
        self.f.capture.assert_not_called()

    def test_natural_summary_is_not_required_to_be_a_literal_source_sentence(self):
        offer = self.start_preview()
        self.assertNotIn(offer['preview_summary'], LESSON)
        self.assertEqual(offer['preview_version'], offer['version'])

    def test_followup_replaces_preview_with_new_scope_in_same_version(self):
        old = self.start_preview()
        text = '外部资料可能过时，引用时还要核对版本。'
        value = dict(points=[preview()['points'][0], dict(text='引用资料前核对版本。', evidence_quotes=[text])],
                     summary=dict(text='资料可以辅助回答，使用时需核对内容和版本。', evidence_quotes=[LESSON, text]))
        self.followup(text, value)
        updated = self.f.offer()
        self.assertEqual(updated['version'], old['version'] + 1)
        self.assertEqual(updated['preview_version'], updated['version'])
        self.assertIn('版本', public(updated)['preview_summary'])
        self.assertEqual(len(updated['preview_points']), 2)
        self.assertIn(text, updated['draft']['content'])
        self.assertNotIn('preview_points', updated['draft'])
        self.f.action(old, 'capture_save')
        self.f.capture.assert_not_called()

    def test_correction_excludes_old_preview_and_old_witnesses_without_losing_reply(self):
        old = self.start_preview()
        text = '只有可访问且检索到的资料才可能帮助回答。'
        # A structurally valid old witness is not allowed after its fragment is removed.
        self.followup(text, preview('不能沿用旧概括。'), correction=True)
        updated = self.f.offer()
        self.assertEqual(updated['id'], old['id'])
        self.assertGreater(updated['version'], old['version'])
        self.assertNotIn('preview_points', public(updated))
        self.assertNotIn(LESSON, updated['draft']['content'])
        self.assertEqual(updated['scope_summary'], text)
        self.assertEqual(self.f.state()['messages'][-1]['content'], text)
        self.assertEqual(self.f.state()['runs'][self.f.state()['messages'][-1]['run_id']]['status'], 'completed')
        self.f.capture.assert_not_called()

    def test_correction_uses_only_current_preview_and_failed_retry_preserves_it_until_ack(self):
        old = self.start_preview()
        self.f.capture.return_value = dict(outcome='retryable_failed', error_code='RT.MEMORY.GENERATION_FAILED')
        self.f.action(old, 'capture_save')
        text = '只有可访问且检索到的资料才可能帮助回答。'
        value = dict(points=[dict(text='资料需要可访问并被检索到。', evidence_quotes=[text])],
                     summary=dict(text='RAG 使用实际检索到的可访问资料辅助回答。', evidence_quotes=[text]))
        self.followup(text, value, correction=True)
        updated = self.f.offer()
        self.assertEqual(updated['status'], 'failed')
        self.assertEqual(public(updated)['preview_points'], ['资料需要可访问并被检索到。'])
        self.assertNotIn(LESSON, updated['draft']['content'])
        self.f.capture.return_value = committing_result(updated['draft']['content'])
        self.f.action(updated, 'capture_save')
        saving = self.f.offer()
        self.assertEqual(saving['status'], 'saving')
        self.assertEqual(public(saving)['preview_summary'], value['summary']['text'])
        self.assertEqual(self.f.capture.call_args.args[1], updated['draft']['content'])
        self.assertNotIn('preview', self.f.capture.call_args.args[1])
        commit = self.f.state()['tasks'][saving['save_task_id']]
        ids = [k['id'] for k in commit['memory_package']['knowledge']]
        with patch.object(self.f.harness, 'start'):
            self.f.harness.acknowledge_task(commit['task_id'], len(commit['events']), ids)
        saved = self.f.offer()
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['knowledge_ids'], ids)
        self.assertEqual(public(saved)['preview_summary'], value['summary']['text'])

    def test_missing_update_preview_falls_back_without_reusing_previous_version(self):
        old = self.start_preview()
        text = '外部资料也需要核对适用条件。'
        self.followup(text, None)
        updated = self.f.offer()
        self.assertEqual(updated['version'], old['version'] + 1)
        self.assertNotIn('preview_points', public(updated))
        self.assertEqual(updated['scope_summary'], text)
        old_event = next(e for e in self.f.state()['events'] if e['stage'] == 'capture_offer')
        self.assertIn('preview_points', old_event['payload']['capture_offer'])

    def test_unconfirmed_correction_hides_old_preview_while_retaining_history(self):
        old = self.start_preview()
        self.f.followup('需要先确认具体的纠正内容。', correction=True, update=False)
        current = self.f.offer()
        self.assertEqual(current['status'], 'invalidated')
        self.assertGreater(current['version'], old['version'])
        self.assertNotIn('preview_points', public(current))
        old_event = next(e for e in self.f.state()['events'] if e['stage'] == 'capture_offer')
        self.assertEqual(old_event['payload']['capture_offer']['preview_summary'], old['preview_summary'])
        self.f.action(current, 'capture_save')
        self.f.capture.assert_not_called()

    def test_retry_without_update_cannot_replay_an_older_run_preview_selection(self):
        old = self.start_preview()
        self.f.decision = intent('followup', scope='continue_goal', workflow='source_learning')
        accepted = self.f.send('再解释刚才的知识点。', drain=False)
        with self.f.store.transaction(self.f.sid) as data:
            data['runs'][accepted.run_id]['capture_scope_update'] = dict(
                offer_id=old['id'], version=old['version'], retained_fragment_ids=[],
                evidence_quotes=['先前尝试才存在的解释。'], scope_summary='旧尝试', preview=preview())
        base = self.f.model
        def legacy_reply(system, user, schema, **kwargs):
            if issubclass(schema, ConversationOutput):
                return ConversationOutput(message='资料检索与回答生成都需要核对。')
            return base(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=legacy_reply):
            self.f.harness.drain(self.f.sid)
        state = self.f.state()
        self.assertEqual(state['runs'][accepted.run_id]['status'], 'completed')
        self.assertNotIn('capture_scope_update', state['runs'][accepted.run_id])
        self.assertEqual(self.f.offer(), old)

    def test_invalid_first_preview_source_falls_back_without_affecting_pass_or_invitation(self):
        offer = self.start_preview(preview(quote='并未选中的来源。'))
        self.assertEqual(offer['status'], 'offered')
        self.assertNotIn('preview_summary', public(offer))
        state = self.f.state()
        task = state['tasks'][state['active_task_id']]
        self.assertTrue(task['context']['practice'][-1]['evaluation']['passed'])
        self.f.capture.assert_not_called()

    def test_old_invitation_and_restored_new_preview_keep_their_original_content(self):
        _, legacy = self.f.start_offer()
        self.assertNotIn('preview_points', public(legacy))
        self.f.harness.recover()
        self.assertEqual(self.f.offer(), legacy)
        self.f.tearDown(); self.f.setUp()
        new = self.start_preview()
        expected = public(new)
        self.f.harness.recover()
        self.assertEqual(public(self.f.offer()), expected)


if __name__ == '__main__':
    unittest.main()
