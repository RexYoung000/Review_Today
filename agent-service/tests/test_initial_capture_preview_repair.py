"""New grounded passes repair missing invitation prose once, without saving."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_service.call_errors import ModelCallError
from agent_service.capture_preview import CapturePreview
from agent_service.judgment_grading import JudgmentFeedback, ScoredMasteryEvaluation
from agent_service.schemas import MasteryEvaluation
from agent_service.topic_capture import public
from tests import test_knowledge_invitation as invitation_fixture
from tests.test_teaching_alignment import LESSON

REAL = Path(__file__).resolve().parents[2] / 'docs/evidence/2026-10-21-continuous-learning-real'


def recorded_evaluation():
    rows = [json.loads(line) for line in (REAL / 'live-events.jsonl').read_text().splitlines()]
    result = [r for r in rows if r['type'] == 'semantic_output' and r['schema'] == 'MasteryEvaluation'][-1]
    payload = next(r['input'] for r in rows if r['type'] == 'semantic_start' and r['call_id'] == result['call_id'])
    return copy.deepcopy(result['output']), copy.deepcopy(payload)


def grounded_preview(quote=LESSON):
    return dict(points=[dict(text='检索到的资料可以帮助回答，但不能保证答案正确。', evidence_quotes=[quote])],
        summary=dict(text='资料辅助回答后仍需核对结果。', evidence_quotes=[quote]))


class InitialPreviewValidationTests(unittest.TestCase):
    def test_retained_real_null_reports_specific_repair_without_changing_grade(self):
        output, payload = recorded_evaluation()
        for schema in (MasteryEvaluation, ScoredMasteryEvaluation):
            with self.subTest(schema=schema.__name__):
                result = schema.model_validate(output)
                before = result.model_dump()
                with self.assertRaises(ModelCallError) as caught:
                    result.validate_request(payload)
                self.assertTrue(caught.exception.repair_missing_capture_preview)
                self.assertEqual(json.loads(caught.exception.diagnostic), [
                    dict(field=['capture_preview'], type='initial_capture_preview_missing')])
                self.assertEqual(result.model_dump(), before)

    def test_missing_null_and_malformed_new_preview_use_the_same_repair(self):
        output, payload = recorded_evaluation()
        for raw in (None, {}, {'points': [], 'summary': {}}, '旧范围说明', {'points': [{'text': '要点'}]}):
            with self.subTest(raw=raw):
                result = MasteryEvaluation.model_validate({**output, 'capture_preview': raw})
                self.assertIsNone(result.capture_preview)
                with self.assertRaises(ModelCallError) as caught:
                    result.validate_request(payload)
                self.assertTrue(caught.exception.repair_missing_capture_preview)
        output.pop('capture_preview')
        with self.assertRaises(ModelCallError):
            MasteryEvaluation.model_validate(output).validate_request(payload)

    def test_non_invitation_and_unreliable_paths_keep_optional_compatibility(self):
        output, original = recorded_evaluation()
        cases = [({'passed': False}, {}), ({'question_validity': 'ambiguous'}, {}),
            ({}, {'hint_used': True}), ({}, {'check_binding': None}),
            ({}, {'capture_concepts': []}), ({'capture_quotes': []}, {})]
        for changes, payload_changes in cases:
            with self.subTest(changes=changes, payload=payload_changes):
                result = MasteryEvaluation.model_validate({**output, **changes})
                result.validate_request({**original, **payload_changes})
                self.assertIsNone(result.capture_preview)
        legacy = MasteryEvaluation(passed=True, correctness='正确', completeness='足够', expression='清楚',
            transfer='未验', feedback='答对了。')
        legacy.validate_request({})
        self.assertTrue(legacy.passed)

    def test_existing_answer_coverage_guard_runs_before_preview_requirement(self):
        output, payload = recorded_evaluation()
        output['answer_coverage'][0]['demonstrated'] = False
        output['answer_coverage'][0]['answer_quotes'] = []
        result = MasteryEvaluation.model_validate(output)
        result.validate_request(payload)
        self.assertFalse(result.passed)
        self.assertIsNone(result.capture_preview)

    def test_original_quote_failure_is_not_reclassified_as_missing_preview(self):
        output, payload = recorded_evaluation()
        output['capture_quotes'] = ['不在当前讲义中的引文。']
        with self.assertRaises(ModelCallError) as caught:
            MasteryEvaluation.model_validate(output).validate_request(payload)
        self.assertFalse(getattr(caught.exception, 'repair_missing_capture_preview', False))
        self.assertEqual(json.loads(caught.exception.diagnostic)[0]['field'], ['capture_quotes'])

    def test_jev_uses_program_effective_pass_instead_of_feedback_guess(self):
        output, payload = recorded_evaluation()
        values = {k: v for k, v in output.items() if k in JudgmentFeedback.model_fields}
        result = JudgmentFeedback.model_validate(values)
        with self.assertRaises(ModelCallError):
            result.validate_request({**payload, 'effective_passed': True})
        for effective in (False, None):
            result.validate_request({**payload, 'effective_passed': effective})

    def test_repaired_preview_must_use_selected_fragments_not_whole_reference(self):
        output, payload = recorded_evaluation()
        selected = output['capture_quotes'][0]
        value = grounded_preview(selected)
        payload['_repair_missing_capture_preview'] = True
        result = MasteryEvaluation.model_validate({**output, 'capture_preview': value})
        result.validate_request(payload)
        unselected = payload['reference'][:12]
        self.assertFalse(any(unselected in text for text in output['capture_quotes'] + output['capture_feedback_quotes']))
        for target in ('point', 'summary'):
            bad = copy.deepcopy(value)
            item = bad['points'][0] if target == 'point' else bad['summary']
            item['evidence_quotes'] = [unselected]
            with self.subTest(target=target), self.assertRaises(ModelCallError) as caught:
                MasteryEvaluation.model_validate({**output, 'capture_preview': bad}).validate_request(payload)
            self.assertEqual(json.loads(caught.exception.diagnostic)[0]['type'], 'initial_capture_preview_grounding')

    def test_duplicate_points_in_missing_preview_repair_are_rejected(self):
        output, payload = recorded_evaluation()
        value = grounded_preview(output['capture_quotes'][0])
        value['points'].append(copy.deepcopy(value['points'][0]))
        with self.assertRaises(ModelCallError) as caught:
            MasteryEvaluation.model_validate({**output, 'capture_preview': value}).validate_request(
                {**payload, '_repair_missing_capture_preview': True})
        self.assertEqual(json.loads(caught.exception.diagnostic)[0]['type'], 'initial_capture_preview_duplicate')

    def test_existing_valid_shaped_initial_source_failure_keeps_compatibility(self):
        output, payload = recorded_evaluation()
        value = grounded_preview('并未选中的旧内容。')
        result = MasteryEvaluation.model_validate({**output, 'capture_preview': value})
        result.validate_request(payload)
        self.assertTrue(result.passed)


class InitialPreviewRepairFlowTests(unittest.TestCase):
    def setUp(self):
        self.f = invitation_fixture.KnowledgeInvitationTests()
        self.f.setUp()
        self.f.start_lesson()

    def tearDown(self): self.f.tearDown()

    def answer_with(self, replacement, *, first_format_error=False, repair_without_quotes=False):
        calls = []
        base = self.f.model
        def score(system, user, schema, **kwargs):
            if schema is MasteryEvaluation:
                calls.append(system)
                if first_format_error and len(calls) == 1:
                    raise ModelCallError('SCHEMA', 'controlled initial JSON failure')
                result = base(system, user, schema, **kwargs)
                result.capture_quotes = [LESSON]
                result.capture_preview = None if len(calls) == 1 else replacement
                if len(calls) == 2 and repair_without_quotes:
                    result.capture_quotes = []
                return result
            return base(system, user, schema, **kwargs)
        with patch('agent_service.conversation.parse_model', side_effect=score):
            self.f.answer()
        return calls, self.f.state()

    def test_missing_preview_repaired_once_published_once_and_never_saved(self):
        calls, state = self.answer_with(CapturePreview.model_validate(grounded_preview()))
        self.assertEqual(len(calls), 2)
        self.assertIn('initial_capture_preview_missing', calls[1])
        offer = self.f.offer()
        self.assertEqual(offer['version'], 1)
        self.assertEqual(public(offer)['preview_points'], [grounded_preview()['points'][0]['text']])
        self.assertEqual(public(offer)['preview_summary'], grounded_preview()['summary']['text'])
        self.assertEqual(len([e for e in state['events'] if e['stage'] == 'capture_offer']), 1)
        self.assertEqual(list(state['runs'].values())[-1]['status'], 'completed')
        self.assertIsNone(state['draft'])
        self.f.capture.assert_not_called()

    def test_second_missing_preview_stops_without_third_attempt_or_invitation(self):
        calls, state = self.answer_with(None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(state['runs'].values())[-1]['status'], 'retryable_failed')
        self.assertEqual(state.get('capture_offers', {}), {})
        self.f.capture.assert_not_called()

    def test_repaired_bad_source_stops_instead_of_publishing_fallback(self):
        calls, state = self.answer_with(CapturePreview.model_validate(grounded_preview('未选中的资料。')))
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(state['runs'].values())[-1]['error_code'], 'RT.MODEL.SCHEMA')
        self.assertEqual(state.get('capture_offers', {}), {})
        self.f.capture.assert_not_called()

    def test_prior_format_repair_and_missing_preview_share_one_retry(self):
        calls, state = self.answer_with(None, first_format_error=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(state['runs'].values())[-1]['status'], 'retryable_failed')
        self.assertEqual(state.get('capture_offers', {}), {})

    def test_repair_cannot_drop_sources_to_bypass_required_preview(self):
        for preview in (None, CapturePreview.model_validate(grounded_preview())):
            with self.subTest(preview=preview):
                calls, state = self.answer_with(preview, repair_without_quotes=True)
                self.assertEqual(len(calls), 2)
                self.assertEqual(list(state['runs'].values())[-1]['error_code'], 'RT.MODEL.SCHEMA')
                self.assertEqual(state.get('capture_offers', {}), {})
                self.f.capture.assert_not_called()


if __name__ == '__main__': unittest.main()
