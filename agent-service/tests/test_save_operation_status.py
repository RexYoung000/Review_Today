"""Operation receipts and discussion coverage answer different questions."""
import copy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError
from agent_service.knowledge_capture_status import facts, reply
from agent_service.openai_client import ModelCallError
from agent_service.schemas import IntentDecision
from tests import test_conversation_v2 as fixtures

REAL = Path(__file__).resolve().parents[2] / 'docs/evidence/2026-10-21-learning-save-real'


def recorded():
    data = json.loads((REAL/'after-save-committed.json').read_text())
    final = json.loads((REAL/'after-status-query.json').read_text())
    query = final['messages'][-2]['content']
    decision = copy.deepcopy(list(final['runs'].values())[-1]['intent'])
    offer = next(iter(data['capture_offers'].values()))
    reference = dict(task_id=offer['save_task_id'], version=offer['version'], evidence='这次一共保存了几张，分别叫什么')
    return data, query, decision, reference


class SaveOperationStatusTests(unittest.TestCase):
    def setUp(self):
        self.data, self.query, self.decision, self.reference = recorded()
        self.offer = next(iter(self.data['capture_offers'].values()))
        self.task = self.data['tasks'][self.offer['save_task_id']]
        self.run = self.data['runs'][self.task['context']['origin_run_id']]

    def selected(self, **kwargs):
        before = copy.deepcopy(self.data)
        state = facts(self.data, save_operation=self.reference, current_request=self.query, **kwargs)
        self.assertEqual(self.data, before)
        return state

    def add_later_save(self):
        offer,task,run=copy.deepcopy(self.offer),copy.deepcopy(self.task),copy.deepcopy(self.run)
        message=copy.deepcopy(next(m for m in self.data['messages'] if m['message_id']==self.offer['action_input_id']))
        message.update(message_id='later-input',run_id='later-run',content='保存另一张预览')
        message['operation']['target_id']='later-offer'
        offer.update(id='later-offer',save_task_id='later-task',action_input_id='later-input',knowledge_ids=['later-card'])
        offer['draft']['id']='later-offer'
        task.update(task_id='later-task',memory_package=dict(knowledge=[dict(id='later-card',title='后一次保存的卡')]))
        task['context'].update(draft_id='later-offer',origin_run_id='later-run',latest_run_id='later-run',capture_offer_id='later-offer')
        run.update(run_id='later-run',task_id='later-task',capture_offer_id='later-offer',input_ids=['later-input'])
        self.data['messages'].append(message)
        self.data['capture_offers'][offer['id']]=offer
        self.data['tasks'][task['task_id']]=task
        self.data['runs'][run['run_id']]=run
        return offer,task

    def test_same_real_focus_still_cannot_certify_whole_discussion(self):
        state = facts(self.data, status_context=self.decision['status_context'])
        self.assertEqual(state['stage'], 'scope_unconfirmed')
        self.assertNotIn('已成功写入 5 张', reply(state, self.decision['status_context']))

    def test_selected_save_answers_matching_five_cards_without_broadening_discussion(self):
        state = self.selected(status_context=self.decision['status_context'])
        text = reply(state, self.decision['status_context'])
        self.assertEqual(state['stage'], 'saved')
        self.assertEqual(set(state['current_knowledge_ids']), set(self.offer['knowledge_ids']))
        self.assertIn('已成功写入 5 张知识卡', text)
        for card in self.task['memory_package']['knowledge']:
            self.assertIn(card['title'], text)
        self.assertNotIn('保存范围不完全一致', text)
        self.assertFalse(text.startswith('刚才讨论的是'))
        self.assertEqual(state['selected_save_operation']['input_message_id'], self.offer['action_input_id'])

    def test_initial_projection_exposes_only_program_owned_binding(self):
        operations = facts(self.data)['save_operations']
        self.assertEqual(len(operations), 1)
        operation = operations[0]
        self.assertEqual(operation['task_id'], self.task['task_id'])
        self.assertEqual(operation['run_id'], self.run['run_id'])
        self.assertEqual(operation['version'], 4)
        self.assertEqual(operation['request'], '保存为知识卡')
        self.assertNotIn('knowledge', operation)

    def test_no_ack_and_mismatched_ids_do_not_borrow_success(self):
        for change in ('no_ack', 'different_offer_ids', 'different_package_ids'):
            with self.subTest(change=change):
                self.setUp()
                if change=='no_ack': self.task['events'] = []
                elif change=='different_offer_ids': self.offer['knowledge_ids'] = ['unrelated-card']
                else: self.task['memory_package']['knowledge'][0]['id'] = 'unrelated-card'
                state = self.selected()
                self.assertEqual(state['stage'], 'saving')
                self.assertEqual(state['current_knowledge_ids'], [])
                self.assertNotIn('已成功写入', reply(state))

    def test_failed_operation_stays_failed(self):
        self.offer.update(status='failed', knowledge_ids=[])
        self.task.update(status='needs_attention', memory_package=None, events=[])
        state = self.selected()
        self.assertEqual(state['stage'], 'failed')
        self.assertEqual(state['current_cards'], [])

    def test_selected_operation_is_not_replaced_by_a_later_success(self):
        self.add_later_save()
        self.assertEqual(len(facts(self.data)['save_operations']),2)
        state=self.selected()
        self.assertEqual(set(state['current_knowledge_ids']),set(self.offer['knowledge_ids']))
        self.assertNotIn('后一次保存的卡',reply(state))

    def test_new_unconfirmed_operation_cannot_borrow_previous_receipt(self):
        offer,task=self.add_later_save();task['events']=[]
        self.reference.update(task_id=task['task_id'],version=offer['version'])
        state=self.selected()
        self.assertEqual(state['stage'],'saving')
        self.assertEqual(state['current_knowledge_ids'],[])

    def test_guessed_reference_or_noncurrent_evidence_is_rejected(self):
        for change in ('task', 'version', 'evidence'):
            with self.subTest(change=change):
                self.setUp()
                self.reference[{'task':'task_id','version':'version','evidence':'evidence'}[change]] = (
                    3 if change=='version' else 'not-in-current-request')
                with self.assertRaises(ModelCallError): self.selected()

    def test_task_run_source_lifecycle_and_version_fences_are_rechecked(self):
        for change in ('foreign_task', 'wrong_offer', 'version', 'stale_run', 'stopped',
                       'run_memory', 'task_memory', 'source_memory', 'lifecycle', 'archived'):
            with self.subTest(change=change):
                self.setUp()
                if change=='foreign_task': self.task['session_id']='other'
                elif change=='wrong_offer': self.task['context']['capture_offer_id']='other'
                elif change=='version': self.task['context']['draft_version']+=1
                elif change=='stale_run': self.run['revision']+=1
                elif change=='stopped': self.run['status']='interrupted'
                elif change=='run_memory': self.run['memory_invalidated']=True
                elif change=='task_memory': self.task['context']['memory_invalidated']=True
                elif change=='source_memory': self.data['tasks'][self.offer['origin_task_id']]['context']['memory_invalidated']=True
                elif change=='lifecycle': self.data['lifecycle_revision']+=1
                else: self.data['status']='archived'
                self.assertEqual(facts(self.data)['save_operations'], [])
                with self.assertRaises(ModelCallError): self.selected()

    def test_post_save_new_knowledge_or_correction_cannot_use_old_operation(self):
        for relation in ('new_topic', 'continuation'):
            with self.subTest(relation=relation):
                self.setUp()
                self.data['messages'].append(dict(message_id='new-content',run_id='new',role='coach',content='新的讲解内容'))
                self.data['runs']['new']=dict(status='completed',activity_kind='knowledge_answer',
                    intent=dict(relation=relation,intents=['question' if relation=='new_topic' else 'correction']))
                self.assertEqual(facts(self.data)['save_operations'], [])
                with self.assertRaises(ModelCallError): self.selected()

    def test_new_topic_input_blocks_old_result_even_before_its_answer(self):
        self.data['messages'].append(dict(message_id='new-question',run_id='new',role='user',content='换一个问题'))
        self.data['runs']['new']=dict(status='running',intent=dict(relation='new_topic'))
        self.assertEqual(facts(self.data)['save_operations'], [])

    def test_compacted_session_events_do_not_remove_persisted_binding(self):
        self.data['events']=[]
        self.assertEqual(self.selected()['stage'], 'saved')

    def test_memory_validity_callback_cannot_be_bypassed(self):
        self.assertEqual(facts(self.data,valid_run=lambda r:False)['save_operations'], [])
        with self.assertRaises(ModelCallError): self.selected(valid_run=lambda r:False)

    def test_reference_validated_before_call_is_rechecked_against_current_state(self):
        value=IntentDecision.model_validate({**self.decision,'knowledge_save_operation':self.reference,'status_context':None})
        payload=dict(knowledge_capture_status=facts(self.data),current_inputs=[self.query])
        value.validate_request(payload)
        self.offer['version']+=1
        with self.assertRaises(ModelCallError): self.selected()


class SaveOperationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.data,self.query,self.decision,self.reference=recorded()
        self.f=fixtures.ConversationTests();self.f.setUp();self.f.sid=self.data['session_id']
        with self.f.store.transaction(self.f.sid) as data: data.update(copy.deepcopy(self.data))

    def tearDown(self): self.f.tearDown()

    def test_repeat_native_text_input_projects_five_cards_without_writes_or_capture(self):
        self.f.decision=IntentDecision.model_validate({**self.decision,'knowledge_save_operation':self.reference,'status_context':None})
        before=copy.deepcopy(self.f.state())
        for _ in range(2):
            accepted=self.f.send(self.query,mode=self.data['mode'])
            after=self.f.state();run=after['runs'][accepted.run_id]
            self.assertEqual(run['status'],'completed')
            self.assertIn('已成功写入 5 张知识卡',after['messages'][-1]['content'])
            self.assertEqual(run['knowledge_status_save_operation']['task_id'],self.reference['task_id'])
            self.assertEqual(run['knowledge_status_context']['focus_labels'],[])
            self.assertEqual(after['tasks'],before['tasks'])
            self.assertEqual(after['capture_offers'],before['capture_offers'])
            self.assertEqual(after['draft'],before['draft'])
            self.assertEqual(after['messages'][:len(before['messages'])],before['messages'])
        self.assertEqual([schema for schema,_ in self.f.calls],[IntentDecision,IntentDecision])
        projected=self.f.calls[0][1]['knowledge_capture_status']['save_operations']
        self.assertEqual(projected[0]['task_id'],self.reference['task_id'])
        self.f.capture.assert_not_called()

    def test_legacy_real_decision_keeps_its_actual_failure_as_a_negative_control(self):
        self.f.decision=IntentDecision.model_validate(self.decision)
        accepted=self.f.send(self.query,mode=self.data['mode'])
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['status'],'completed')
        self.assertIn('保存范围不完全一致',self.f.state()['messages'][-1]['content'])
        self.f.capture.assert_not_called()

    def test_invalid_selection_uses_only_existing_one_repair(self):
        original_model=self.f.model
        valid=IntentDecision.model_validate({**self.decision,'knowledge_save_operation':self.reference,'status_context':None})
        invalid=valid.model_copy(update={'knowledge_save_operation':valid.knowledge_save_operation.model_copy(update={'task_id':'guessed'})})
        def model(*args,**kwargs):
            self.f.decision=invalid if not self.f.calls else valid
            return original_model(*args,**kwargs)
        from unittest.mock import patch
        with patch('agent_service.conversation.parse_model',side_effect=model):
            accepted=self.f.send(self.query,mode=self.data['mode'])
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['status'],'completed')
        self.assertEqual([schema for schema,_ in self.f.calls],[IntentDecision,IntentDecision])
        self.assertIn('已成功写入 5 张知识卡',self.f.state()['messages'][-1]['content'])
        self.f.capture.assert_not_called()

    def test_repeated_invalid_selection_stops_without_borrowing_receipt(self):
        bad={**self.reference,'task_id':'guessed'}
        self.f.decision=IntentDecision.model_validate({**self.decision,'knowledge_save_operation':bad,'status_context':None})
        accepted=self.f.send(self.query,mode=self.data['mode'])
        run=self.f.state()['runs'][accepted.run_id]
        self.assertEqual(run['status'],'retryable_failed')
        self.assertEqual(run['error_code'],'RT.MODEL.SCHEMA')
        self.assertEqual([schema for schema,_ in self.f.calls],[IntentDecision,IntentDecision])
        self.f.capture.assert_not_called()

    def test_schema_and_jev_paths_share_readonly_reference_validation(self):
        from agent_service.judgment_nodes import IntentRemainder
        value=IntentDecision.model_validate({**self.decision,'knowledge_save_operation':self.reference,'status_context':None})
        payload=dict(knowledge_capture_status=facts(self.data),current_inputs=[self.query])
        partial=IntentRemainder(scope='conversation',rationale='受控操作选择',knowledge_card_status=True,
            knowledge_save_operation=self.reference)
        for item,arg in ((value,payload),(partial,dict(context=payload)),
                         (IntentRemainder(scope='conversation',rationale='受控完整替换',replacement=value),dict(context=payload))):
            item.validate_request(arg)
            wrong=copy.deepcopy(arg)
            (wrong.get('context',wrong))['current_inputs']=['其他请求']
            with self.assertRaises(ModelCallError): item.validate_request(wrong)
        self.assertEqual(IntentRemainder.model_fields['knowledge_save_operation'].annotation,
                         IntentDecision.model_fields['knowledge_save_operation'].annotation)
        with self.assertRaises(ValidationError):
            IntentDecision.model_validate({**self.decision,'knowledge_card_status':False,'knowledge_save_operation':self.reference})


if __name__=='__main__': unittest.main()
