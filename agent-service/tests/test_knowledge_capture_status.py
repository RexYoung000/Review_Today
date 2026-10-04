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


def check_offer(data, status='offered'):
    value = offer(data, status)
    value.update(trigger='verified_check', scope_summary='整理向量检索的语义匹配及其限定。',
                 anchor_message_id='lesson', fragments=[dict(message_id='lesson', text='向量索引讲解')])
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

    def test_check_invitation_projects_actual_entry_and_visible_scope_without_mutation(self):
        data = state(); current = check_offer(data); before = copy.deepcopy(data)
        result = facts(data)
        self.assertEqual(result['capture_offer']['trigger'], 'verified_check')
        self.assertEqual(result['capture_offer']['scope_summary'], current['scope_summary'])
        text = reply(result)
        self.assertIn('「新增知识」', text)
        self.assertIn('「稍后」', text)
        self.assertIn('还没有生成知识卡', text)
        self.assertIn(current['scope_summary'], text)
        self.assertNotIn('收尾面板', text)
        self.assertNotIn('录入并继续', text)
        self.assertIn('新增知识', result['steps'][1])
        self.assertEqual(data, before)

    def test_check_invitation_statuses_use_the_actual_controls(self):
        for status, expected in [('deferred', '「稍后」'), ('failed', '「重试录入」'),
                                 ('dismissed', '提示已收起'), ('invalidated', '旧版不能继续'),
                                 ('skipped', '没有因此生成知识卡')]:
            with self.subTest(status=status):
                data = state(); check_offer(data, status)
                text = reply(facts(data))
                self.assertIn(expected, text)
                self.assertNotIn('收尾面板', text)
                self.assertNotIn('录入并继续', text)
                if status == 'deferred':
                    self.assertIn('「新增知识」', text)

    def test_current_check_invitation_is_not_hidden_by_an_older_last_inserted_offer(self):
        data = state(); new = check_offer(data)
        data['messages'].insert(0, dict(message_id='old-lesson', role='coach', run_id='old', content='旧知识讲解'))
        data['runs']['old'] = dict(status='completed', activity_kind='lesson_step')
        data['capture_offers']['old'] = dict(id='old', version=1, status='deferred', message_ids=['old-lesson'],
            lifecycle_revision=0, title='旧知识')
        self.assertEqual(facts(data)['capture_offer']['id'], new['id'])
        self.assertEqual(facts(data)['stage'], 'awaiting_confirmation')

    def test_status_selection_matches_its_specific_offer_instead_of_latest_offer(self):
        data = state(); older = check_offer(data, 'deferred')
        data['messages'].append(dict(message_id='later', role='coach', run_id='next', content='关键词按字词匹配。'))
        data['runs']['next'] = dict(status='completed', activity_kind='knowledge_answer')
        data['capture_offers']['new'] = dict(id='new', version=1, status='offered', title='关键词匹配',
            trigger='verified_check', scope_summary='整理关键词匹配。', message_ids=['later'],
            anchor_message_id='later', fragments=[dict(message_id='later', text='关键词按字词匹配。')],
            lifecycle_revision=0)
        context = dict(focus=[dict(message_id='lesson', label='向量语义匹配', quote='向量索引讲解')])
        result = facts(data, status_context=context)
        self.assertEqual(result['capture_offer']['id'], older['id'])
        self.assertEqual(result['stage'], 'deferred')
        self.assertIn('已选择「稍后」', reply(result, context))
        context['focus'][0].update(message_id='later', label='关键词匹配', quote='关键词按字词匹配。')
        self.assertEqual(facts(data, status_context=context)['capture_offer']['id'], 'new')

    def test_same_lesson_other_excerpt_cannot_borrow_a_check_invitation(self):
        data = state(); current = check_offer(data)
        data['messages'][0]['content'] = '向量索引讲解。关键词按字词匹配。'
        current['anchor_message_id'] = 'answer-feedback'
        context = dict(focus=[dict(message_id='lesson', label='关键词匹配', quote='关键词按字词匹配。')])
        result = facts(data, status_context=context)
        self.assertIsNone(result['capture_offer'])
        self.assertEqual(result['stage'], 'unorganized')
        self.assertNotIn(current['scope_summary'], reply(result, context))

    def test_saved_vector_invitation_is_selected_after_later_chunking_discussion(self):
        data = state(); current = check_offer(data, 'saved')
        current['knowledge_ids'] = ['new-card']
        task = commit(data, acknowledged=True)
        task['memory_package']['knowledge'][0]['title'] = '向量匹配及其限定'
        current.update(anchor_message_id='feedback', message_ids=['lesson', 'feedback', 'followup'])
        additions = [
            ('feedback', '回答正确；不同措辞也可能按语义相近程度召回，但不保证正确。'),
            ('followup', '向量匹配仍需要检查实际内容是否回答了问题。'),
            ('chunking', '资料切块把文档分成适合检索的小段。'),
        ]
        for identity, content in additions:
            data['messages'].append(dict(message_id=identity, role='coach', run_id=identity, content=content))
            data['runs'][identity] = dict(status='completed', activity_kind='knowledge_answer')
        current['fragments'].append(dict(message_id='followup', text=additions[1][1]))
        context = dict(focus=[dict(message_id='feedback', label='向量匹配的召回与正确性', quote=additions[0][1]),
                              dict(message_id='followup', label='向量匹配的内容核对', quote=additions[1][1])])
        self.assertEqual(facts(data)['stage'], 'unorganized', 'the later chunking segment itself is unsaved')
        before = copy.deepcopy(data)
        result = facts(data, status_context=context)
        self.assertEqual(result['capture_offer']['id'], current['id'])
        self.assertEqual(result['stage'], 'saved')
        self.assertEqual(result['current_knowledge_ids'], ['new-card'])
        text = reply(result, context)
        self.assertIn('已成功写入 1 张知识卡', text)
        self.assertIn('向量匹配及其限定', text)
        self.assertNotIn('这段内容还没有整理成知识卡', text)
        self.assertNotIn('切块', text)
        self.assertEqual(data, before)
        task['events'] = []
        self.assertEqual(facts(data, status_context=context)['stage'], 'saving', 'source selection cannot replace a Mac ACK')

    def test_combined_scope_with_saved_part_and_uncovered_topic_is_not_called_wholly_unsaved(self):
        data = state(); current = check_offer(data, 'saved'); current['knowledge_ids'] = ['new-card']
        task = commit(data, acknowledged=True)
        data['messages'].append(dict(message_id='keyword', role='coach', run_id='keyword', content='关键词按字词匹配。'))
        data['runs']['keyword'] = dict(status='completed', activity_kind='knowledge_answer')
        context = dict(focus=[dict(message_id='lesson', label='向量匹配', quote='向量索引讲解'),
                              dict(message_id='keyword', label='关键词匹配', quote='关键词按字词匹配。')])
        result = facts(data, status_context=context)
        self.assertEqual(result['stage'], 'scope_unconfirmed')
        self.assertEqual(result['current_knowledge_ids'], [], 'one receipt does not certify the whole combined query')
        self.assertEqual(result['scope_saved_knowledge_ids'], ['new-card'])
        self.assertTrue(result['scope_has_uncovered_focus'])
        text = reply(result, context)
        self.assertIn('保存范围不完全一致', text)
        self.assertIn('已保存的部分可以到知识库查看', text)
        self.assertIn('其余内容需要先明确保存范围', text)
        self.assertNotIn('这段内容还没有整理成知识卡', text)
        self.assertNotIn('已成功写入', text)
        task['events'] = []
        result = facts(data, status_context=context)
        self.assertEqual(result['scope_saved_knowledge_ids'], [])
        self.assertNotIn('已保存的部分', reply(result, context))

    def test_combined_scope_fully_covered_by_separate_saved_offers_keeps_their_receipt_truth(self):
        data = state(); current = check_offer(data, 'saved'); current['knowledge_ids'] = ['new-card']
        commit(data, acknowledged=True)
        data['messages'].append(dict(message_id='keyword', role='coach', run_id='keyword', content='关键词按字词匹配。'))
        data['runs']['keyword'] = dict(status='completed', activity_kind='knowledge_answer')
        data['capture_offers']['keyword'] = dict(id='keyword', version=1, trigger='verified_check', status='saved',
            title='关键词匹配', scope_summary='整理关键词匹配。', message_ids=['keyword'], anchor_message_id='keyword',
            fragments=[dict(message_id='keyword', text='关键词按字词匹配。')], knowledge_ids=['keyword-card'],
            save_task_id='keyword-commit', lifecycle_revision=0)
        data['tasks']['keyword-commit'] = dict(task_id='keyword-commit', session_id='current', status='completed',
            mode='memory_organization', context=dict(capture_offer_id='keyword'),
            memory_package=dict(knowledge=[dict(id='keyword-card')]), events=[dict(node='mac_ack')])
        context = dict(focus=[dict(message_id='lesson', label='向量匹配', quote='向量索引讲解'),
                              dict(message_id='keyword', label='关键词匹配', quote='关键词按字词匹配。')])
        for item, expected in zip(context['focus'], ['new-card', 'keyword-card']):
            single = facts(data, status_context=dict(focus=[item]))
            self.assertEqual(single['stage'], 'saved')
            self.assertEqual(single['current_knowledge_ids'], [expected])
        before = copy.deepcopy(data)
        result = facts(data, status_context=context)
        self.assertEqual(result['stage'], 'scope_unconfirmed')
        self.assertCountEqual(result['scope_saved_knowledge_ids'], ['new-card', 'keyword-card'])
        self.assertFalse(result['scope_has_uncovered_focus'])
        text = reply(result, context)
        self.assertIn('已保存的部分可以到知识库查看', text)
        self.assertIn('分别核对对应记录的保存范围', text)
        self.assertNotIn('其余内容需要先明确保存范围', text)
        self.assertNotIn('还没有整理成知识卡', text)
        self.assertNotIn('还没有写入知识库', text)
        self.assertNotIn('已成功写入 0', text)
        self.assertEqual(data, before)


if __name__ == '__main__':
    unittest.main()
