"""Knowledge-card status must describe persisted state, not nearby library cards."""
import copy
import unittest

from agent_service.knowledge_capture_status import facts, reply


def state():
    return dict(session_id='current', lifecycle_revision=0, tasks={}, capture_offers={}, events=[],
                messages=[dict(message_id='lesson', role='coach', run_id='teaching', content='向量索引讲解')],
                runs={'teaching': dict(status='completed', activity_kind='lesson_step')}, draft=None, pending=None)


def offer(data, status='offered'):
    value = dict(id='offer', version=1, status=status, title='检索索引', message_ids=['lesson'],
                 save_task_id='commit', knowledge_ids=[], lifecycle_revision=0)
    data['capture_offers']['offer'] = value
    return value


def commit(data, *, acknowledged=False):
    value = dict(task_id='commit', session_id='current', status='completed' if acknowledged else 'committing',
                 mode='memory_organization', context=dict(conversation_managed=True, capture_offer_id='offer'),
                 memory_package=dict(knowledge=[dict(id='new-card')]), events=[dict(node='mac_ack')] if acknowledged else [])
    data['tasks']['commit'] = value
    return value


class KnowledgeCaptureStatusTests(unittest.TestCase):
    def test_old_related_cards_never_claim_current_segment_was_saved(self):
        data = state(); before = copy.deepcopy(data)
        result = facts(data, related_knowledge=[dict(id='old-20260814-a'), dict(id='old-20260814-b')])
        self.assertEqual(result['stage'], 'unorganized')
        self.assertEqual(result['current_knowledge_ids'], [])
        self.assertIn('还没有整理成知识卡', reply(result))
        self.assertIn('旧卡只是参考', reply(result))
        self.assertIn('把刚才内容整理成知识卡', reply(result))
        self.assertEqual(data, before, 'status reads must not authorize or mutate a capture')

    def test_offered_deferred_dismissed_failed_and_invalidated_are_distinct(self):
        expected = dict(offered='awaiting_confirmation', deferred='deferred', dismissed='dismissed',
                        failed='failed', invalidated='invalidated', skipped='skipped')
        for value, stage in expected.items():
            with self.subTest(value=value):
                data = state(); offer(data, value)
                result = facts(data)
                self.assertEqual(result['stage'], stage)
                self.assertEqual(result['current_knowledge_ids'], [])
        data = state(); offer(data, 'dismissed')
        self.assertIn('提示已收起', reply(facts(data)))

    def test_generated_package_does_not_certify_a_local_write(self):
        data = state(); current = offer(data, 'saving'); current['knowledge_ids'] = ['new-card']
        task = commit(data)
        self.assertEqual(facts(data)['stage'], 'saving')
        task['status'] = 'completed'; current['status'] = 'saved'
        self.assertEqual(facts(data)['stage'], 'saving', 'a declared completed status is insufficient without ACK')
        task['events'] = [dict(node='mac_ack')]
        self.assertEqual(facts(data)['stage'], 'saved')
        self.assertEqual(facts(data)['current_knowledge_ids'], ['new-card'])

    def test_foreign_task_or_mismatching_receipt_cannot_certify_offer(self):
        data = state(); current = offer(data, 'saved'); current['knowledge_ids'] = ['new-card']
        task = commit(data, acknowledged=True)
        task['session_id'] = 'foreign'
        self.assertEqual(facts(data)['stage'], 'saving')
        task['session_id'] = 'current'; current['knowledge_ids'] = ['another-card']
        self.assertEqual(facts(data)['stage'], 'saving')

    def test_new_explanation_does_not_inherit_old_save_success(self):
        data = state(); current = offer(data, 'saved'); current['knowledge_ids'] = ['new-card']; commit(data, acknowledged=True)
        data['messages'].append(dict(message_id='later', role='coach', run_id='next', content='后续纠正'))
        data['runs']['next'] = dict(status='completed', activity_kind='knowledge_answer')
        result = facts(data)
        self.assertEqual(result['stage'], 'unorganized')
        self.assertEqual(result['session_saved_knowledge_ids'], ['new-card'])
        self.assertIn('不能据此说刚才这段也已保存', reply(result))

    def test_status_reply_is_not_a_new_learning_segment(self):
        data = state(); offer(data)
        data['messages'].append(dict(message_id='status', role='coach', run_id='status-run', content='尚未保存'))
        data['runs']['status-run'] = dict(status='completed', knowledge_status_reply=True, activity_kind='knowledge_answer')
        self.assertEqual(facts(data)['stage'], 'awaiting_confirmation')
        self.assertEqual(facts(data)['latest_learning_message_id'], 'lesson')

    def test_pending_draft_has_honest_instruction_without_an_offer_panel(self):
        data = state()
        data['draft'] = dict(id='draft', version=1, source_message_ids=['lesson'])
        data['pending'] = dict(kind='save', target_id='draft', version=1)
        result = facts(data)
        self.assertEqual(result['stage'], 'awaiting_confirmation')
        self.assertIn('确认保存', reply(result))
        self.assertNotIn('收尾面板', reply(result))

    def test_legacy_draft_event_binds_the_actual_generation(self):
        data = state(); data['draft'] = dict(id='draft', version=1)
        data['pending'] = dict(kind='save', target_id='draft', version=1)
        data['events'] = [dict(stage='draft', run_id='teaching', payload=dict(draft=copy.deepcopy(data['draft'])))]
        self.assertEqual(facts(data)['stage'], 'awaiting_confirmation')
        data['messages'].append(dict(message_id='later', role='coach', run_id='next', content='新知识'))
        data['runs']['next'] = dict(status='completed', activity_kind='knowledge_answer')
        self.assertEqual(facts(data)['stage'], 'unorganized')

    def test_legacy_memory_task_needs_mac_ack(self):
        data = state(); task = commit(data)
        task['context'] = dict(conversation_managed=True, origin_run_id='save')
        data['messages'].append(dict(message_id='save-input', role='user', content='保存'))
        data['runs']['save'] = dict(input_ids=['save-input'])
        self.assertEqual(facts(data)['stage'], 'saving')
        task['status'] = 'completed'; task['events'] = [dict(node='mac_ack')]
        self.assertEqual(facts(data)['stage'], 'saved')

    def test_saved_reply_names_only_the_cards_in_the_current_real_receipt(self):
        data = state(); current = offer(data, 'saved'); current['knowledge_ids'] = ['new-card', 'second']
        task = commit(data, acknowledged=True)
        task['memory_package']['knowledge'] = [dict(id='new-card', title='关键词索引', explanation='正文不进入状态投影'),
                                                dict(id='second', learning_goal='解释向量索引如何匹配近义表达')]
        result = facts(data, related_knowledge=[dict(id='old-card', title='旧卡不可混入')])
        self.assertEqual(result['current_cards'], [dict(id='new-card', title='关键词索引'), dict(id='second', title='解释向量索引如何匹配近义表达')])
        text = reply(result)
        self.assertIn('关键词索引', text)
        self.assertIn('向量索引如何匹配近义表达', text)
        self.assertNotIn('旧卡不可混入', text)
        self.assertNotIn('正文不进入状态投影', str(result))

    def test_partial_legacy_coverage_is_explicit_in_status_answer(self):
        data = state(); current = offer(data)
        current['coverage_note'] = '部分旧题反馈未能与讲解核对，暂仅整理已确认的讲解；可先补讲再完整整理。'
        self.assertIn('暂仅整理已确认的讲解', reply(facts(data)))


if __name__ == '__main__':
    unittest.main()
