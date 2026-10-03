"""Capture the actual explanation and bound corrections after an answer."""
import copy
from types import SimpleNamespace
import unittest

from agent_service.topic_capture import collect_source


class CaptureSourceTests(unittest.TestCase):
    def setUp(self):
        self.h = SimpleNamespace(store=SimpleNamespace(memory_valid=lambda refs: True),
                                 _memory_run_valid=lambda run: not run.get('memory_invalidated'))
        self.task = dict(task_id='task', session_id='session', status='awaiting_user', context=dict(
            learning_plan=dict(version=2, current_step_id='index', steps=[dict(id='index', title='索引', message_ids=['lesson'])]),
            practice=[dict(run_id='evaluate', message_id='answer', revision=1,
                           binding=dict(step_id='index', plan_version=2),
                           evaluation=dict(passed=False, feedback='向量索引可匹配近义表达，但仍可能漏检。'))]))
        self.data = dict(session_id='session', lifecycle_revision=0, events=[], capture_offers={},
            messages=[dict(message_id='lesson', role='coach', run_id='teach', content='关键词检索会分词，是否命中取决于匹配规则。'),
                      dict(message_id='answer', role='user', run_id='evaluate', content='用户错答：向量一定找得到。'),
                      dict(message_id='feedback', role='coach', run_id='evaluate', content='不能说一定命中。')],
            runs=dict(teach=dict(run_id='teach', task_id='task', status='completed', revision=1,
                                activity_kind='lesson_step', teaching_step_id='index', teaching_plan_version=2),
                      evaluate=dict(run_id='evaluate', task_id='task', status='completed', revision=1, input_ids=['answer'],
                                    intent=dict(intents=['answer']), evaluated_step_id='index', evaluation_message_id='answer',
                                    evaluated_binding=dict(step_id='index', plan_version=2))))

    def source(self, **kwargs):
        return collect_source(self.h, self.data, self.task, **kwargs)

    def test_latest_evaluation_closure_includes_lesson_and_valid_correction(self):
        result = self.source(message_ids=['feedback'])
        self.assertEqual(result['message_ids'], ['lesson', 'feedback'])
        self.assertIn('是否命中取决于匹配规则', result['content'])
        self.assertIn('仍可能漏检', result['content'])
        self.assertNotIn('用户错答', result['content'])
        self.assertNotIn('向量一定找得到', result['content'])

    def test_question_clarification_and_status_reply_do_not_break_segment(self):
        self.data['messages'].insert(1, dict(message_id='clarification', role='coach', run_id='clarify', content='这题只需要说出不同措辞如何匹配。'))
        self.data['runs']['clarify'] = dict(status='completed', task_id=None, dialogue_only=True, reply_feedback_handled=True)
        self.data['messages'].append(dict(message_id='status', role='coach', run_id='status', content='尚未生成知识卡。'))
        self.data['runs']['status'] = dict(status='completed', knowledge_status_reply=True, task_id=None)
        result = self.source(message_ids=['feedback'])
        self.assertEqual(result['message_ids'], ['lesson', 'feedback'])
        self.assertNotIn('尚未生成', result['content'])

    def test_foreign_task_interrupts_segment_and_cannot_be_selected(self):
        self.data['messages'].insert(1, dict(message_id='foreign', role='coach', run_id='foreign', content='另一目标的材料'))
        self.data['runs']['foreign'] = dict(status='completed', task_id='another', activity_kind='lesson_step')
        self.assertIsNone(self.source())
        self.assertIsNone(self.source(message_ids=['foreign', 'feedback']))

    def test_wrong_version_foreign_step_invalidated_and_unfinished_sources_fail(self):
        for change in [dict(teaching_plan_version=1), dict(teaching_step_id='chunking'),
                       dict(memory_invalidated=True), dict(status='interrupted')]:
            with self.subTest(change=change):
                data = copy.deepcopy(self.data); data['runs']['teach'].update(change)
                self.assertIsNone(collect_source(self.h, data, self.task))

    def test_archive_restore_does_not_invalidate_completed_delivered_teaching(self):
        self.data['lifecycle_revision'] = 4
        self.data['runs']['teach']['lifecycle_revision'] = 0
        self.data['runs']['evaluate']['lifecycle_revision'] = 0
        self.assertIsNotNone(self.source())

    def test_followup_explanation_after_lesson_is_part_of_direct_save_source(self):
        self.data['messages'].insert(1, dict(message_id='followup', role='coach', run_id='followup', content='补充：关键词检索会按规则计算相关性。'))
        self.data['runs']['followup'] = dict(run_id='followup', status='completed', task_id='task', revision=1,
                                            activity_kind='knowledge_answer', intent=dict(relation='continuation', intents=['question']))
        result = self.source()
        self.assertEqual(result['message_ids'], ['lesson', 'followup', 'feedback'])
        self.assertIn('按规则计算相关性', result['content'])

    def test_no_teaching_cannot_use_feedback_as_knowledge(self):
        self.data['messages'] = self.data['messages'][1:]
        self.assertIsNone(self.source())

    def test_unbound_legacy_feedback_is_only_a_closure_anchor(self):
        self.data['runs']['evaluate']['evaluated_binding'] = None
        result = self.source(message_ids=['feedback'])
        self.assertEqual(result['message_ids'], ['lesson'])
        self.assertEqual(result['excluded_unbound_feedback_ids'], ['feedback'])
        self.assertNotIn('近义表达', result['content'])
        self.assertNotIn('用户错答', result['content'])

    def test_practice_record_from_another_run_does_not_supply_feedback(self):
        self.task['context']['practice'][0]['run_id'] = 'another-evaluation'
        result = self.source()
        self.assertNotIn('近义表达', result['content'])

    def test_same_run_retry_uses_new_correction_and_excludes_old_wrong_feedback(self):
        self.data['runs']['evaluate']['revision'] = 2
        self.data['events'].append(dict(revision=2, message=dict(message_id='feedback')))
        old = self.task['context']['practice'][0]
        old['evaluation']['feedback'] = '旧错反馈：关键词必须完整句完全匹配。'
        current = copy.deepcopy(old)
        current.update(revision=2, evaluation=dict(passed=True, feedback='新纠正：关键词会分词匹配。'))
        self.task['context']['practice'].append(current)
        result = self.source()
        self.assertIn('新纠正：关键词会分词匹配', result['content'])
        self.assertNotIn('旧错反馈', result['content'])

    def test_missing_revision_or_mismatched_binding_is_only_an_excluded_anchor(self):
        for mutate in [lambda value: value.pop('revision'),
                       lambda value: value.update(binding=dict(step_id='chunking', plan_version=2))]:
            with self.subTest(mutate=mutate):
                task = copy.deepcopy(self.task)
                mutate(task['context']['practice'][0])
                result = collect_source(self.h, self.data, task)
                self.assertNotIn('近义表达', result['content'])
                self.assertEqual(result['excluded_unbound_feedback_ids'], ['feedback'])

    def test_model_cannot_include_user_answer_or_invent_message_id(self):
        for identity in ['answer', 'invented']:
            self.assertIsNone(self.source(message_ids=[identity, 'feedback']))

    def test_receipt_boundary_never_reoffers_the_same_source(self):
        self.data['capture_offers']['old'] = dict(message_ids=['lesson', 'feedback'])
        self.assertIsNone(self.source())

    def test_direct_save_reuses_explicitly_frozen_source_and_its_version(self):
        self.data['capture_offers']['old'] = dict(id='old', status='dismissed', origin_task_id='task',
            message_ids=['lesson', 'feedback'], lifecycle_revision=0,
            draft=dict(id='draft', version=3, content='已冻结的讲解和纠正', memory_references=[]), sources=[])
        result = self.source(include_captured=True)
        self.assertEqual(result['content'], '已冻结的讲解和纠正')
        self.assertEqual((result['draft_id'], result['draft_version']), ('draft', 3))
        self.data['capture_offers']['old']['status'] = 'invalidated'
        self.assertIsNone(self.source(include_captured=True))

    def test_stale_message_revision_cannot_reappear_in_capture(self):
        self.data['events'].append(dict(revision=1, message=dict(message_id='lesson')))
        self.data['runs']['teach']['revision'] = 2
        self.assertIsNone(self.source())


if __name__ == '__main__':
    unittest.main()
