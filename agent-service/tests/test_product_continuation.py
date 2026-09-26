"""The real harness must preserve the latest request and unfinished JD state."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from agent_service.call_errors import ModelCallError
from agent_service.conversation_materials import normalize, MaterialReadiness, MaterialFinding
from tests import test_conversation_v2 as base
from tests import test_material_routing as material


class ProductContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = material.MaterialRoutingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f

    def product(self, *intents, **kw):
        self.f.decision = base.intent(*(intents or ('material', 'continue')), material_focus='product',
            is_jd=True, jd_request='analyze', scope='continue_goal', **kw)

    def test_failed_jd_product_exchange_and_explicit_retry(self):
        self.fixture.jd(material_focus='jd')
        with patch('agent_service.conversation.fetch_public_url', return_value=('招聘页', material.SHELL)):
            self.f.send(material.URL + ' JD 在这里，我要面试，还需要了解 EMOX')
        self.fixture.outputs = [ModelCallError('TIMEOUT')]
        failed = self.f.send('补上岗位正文：' + material.JD)
        data = self.f.state(); tid = data['active_task_id']; task = data['tasks'][tid]
        self.assertEqual(task['stage'], 'jd_analyzing')
        self.assertIsNone(task['required_action'])
        self.assertFalse(task['context']['awaiting_material'])
        self.assertEqual(data['runs'][failed.run_id]['status'], 'retryable_failed')

        self.f.decision = base.intent('question', resource_boundary='capability_question',
            light_reply='我不能直接打开微信小程序，可以分析你发来的产品介绍或截图。')
        self.f.send('可以直接打开微信小程序吗')
        self.product()
        with patch('agent_service.conversation.fetch_public_url') as reader:
            shared = self.f.send('#小程序://EMOX/synthetic-share')
        reader.assert_not_called()
        data = self.f.state(); run = data['runs'][shared.run_id]
        self.assertEqual(run['status'], 'completed')
        self.assertFalse(run['intent']['is_jd'])
        self.assertNotIn('goal', run['intent']['intents'])
        self.assertEqual(len(self.fixture.jd_inputs), 1)
        self.assertFalse(run['material_readiness']['can_proceed'])
        self.assertEqual(self.fixture.readiness[-1]['kind'], 'product')
        self.assertEqual(self.fixture.readiness[-1]['original_request'], '#小程序://EMOX/synthetic-share')
        self.assertEqual(data['tasks'][tid]['stage'], 'jd_analyzing')
        self.assertTrue(data['tasks'][tid]['context']['material_readiness']['can_proceed'])
        context, _ = self.f.harness._context(data, run)
        self.assertEqual(context['incomplete_responses'][0]['content'], '半截岗位分析')
        self.assertEqual(context['incomplete_responses'][0]['state'], 'failed')
        self.assertFalse(any(m['content'] == '半截岗位分析' for m in context['recent_messages']))
        self.assertFalse(any(m['content'] == '半截岗位分析' for m in data['messages']))

        self.product()
        self.f.send(material.PRODUCT)
        self.assertEqual(len(self.fixture.jd_inputs), 1)
        self.assertEqual(self.f.state()['active_task_id'], tid)
        self.fixture.jd(material_focus='jd')
        retried = self.f.send('现在重新分析刚才的 JD，给出完整问题')
        data = self.f.state()
        self.assertEqual(data['runs'][retried.run_id]['status'], 'completed')
        self.assertEqual(len(self.fixture.jd_inputs), 2)
        self.assertEqual(data['tasks'][tid]['stage'], 'jd_analysis')
        self.assertEqual(data['pending']['kind'], 'select_question')

    def test_product_after_complete_jd_keeps_question_choice_and_version(self):
        self.fixture.jd(material_focus='jd')
        self.f.send(material.JD)
        before = self.f.state(); tid = before['active_task_id']
        self.product()
        self.f.send(material.PRODUCT)
        after = self.f.state()
        self.assertEqual(after['pending'], before['pending'])
        self.assertEqual(after['tasks'][tid]['context']['jd_analysis_version'], 1)
        self.assertEqual(after['tasks'][tid]['stage'], 'jd_analysis')
        self.assertEqual(len(self.fixture.jd_inputs), 1)

    def test_product_failure_does_not_fail_completed_jd_or_clear_choice(self):
        self.fixture.jd(material_focus='jd'); self.f.send(material.JD)
        before = self.f.state(); tid = before['active_task_id']
        self.product()
        def fail_product(system, prompt, schema, **kw):
            if schema is material.ConversationOutput:
                raise ModelCallError('TIMEOUT')
            return self.fixture.model(system, prompt, schema, **kw)
        with patch('agent_service.conversation.parse_model', side_effect=fail_product):
            ack = self.f.send(material.PRODUCT)
        after = self.f.state()
        self.assertEqual(after['runs'][ack.run_id]['status'], 'retryable_failed')
        self.assertEqual(after['tasks'][tid]['status'], before['tasks'][tid]['status'])
        self.assertEqual(after['tasks'][tid]['stage'], 'jd_analysis')
        self.assertEqual(after['pending'], before['pending'])

    def test_old_ready_material_wait_is_corrected_without_rewriting_history(self):
        self.fixture.jd(material_focus='jd'); self.fixture.outputs = [ModelCallError('TIMEOUT')]
        self.f.send(material.JD)
        with self.f.store.transaction(self.f.sid) as data:
            task = data['tasks'][data['active_task_id']]
            task.update(stage='awaiting_material', required_action={'type':'respond','prompt':'补充材料正文','options':[]})
        history = deepcopy(self.f.state()['messages'])
        self.product()
        ack = self.f.send('#小程序://EMOX/test', drain=False)
        data = self.f.state()
        context, _ = self.f.harness._context(data, data['runs'][ack.run_id])
        self.assertEqual(context['task']['stage'], 'jd_analyzing')
        self.assertIsNone(context['task']['required_action'])
        self.f.harness.drain(self.f.sid)
        after = self.f.state()
        self.assertEqual(after['messages'][:len(history)], history)
        self.assertEqual(after['tasks'][after['active_task_id']]['stage'], 'jd_analyzing')
        self.assertIsNone(after['tasks'][after['active_task_id']]['required_action'])

    def test_product_focus_cannot_override_control_or_explicit_operations(self):
        for intent in ['stop', 'pause', 'cancel', 'defer', 'reject']:
            decision = base.intent(intent, material_focus='product')
            self.assertEqual(normalize({}, decision, {}), decision)
        decision = base.intent('confirm', material_focus='product')
        self.assertEqual(normalize({}, decision, {'operation': {'kind':'select_question'}}), decision)
        teaching = base.intent('goal', material_focus='product', direct_teaching=True,
                               scope='learning', workflow='source_learning')
        self.assertEqual(normalize({}, teaching, {}), teaching)

    def test_ready_jd_does_not_force_untyped_new_material_to_analyze(self):
        self.fixture.jd(material_focus='jd'); self.f.send(material.JD)
        decision = base.intent('material')
        self.assertFalse(normalize(self.f.state(), decision, {}).is_jd)

    def test_jd_containing_product_intro_can_support_product_followup(self):
        body = material.JD + '\n' + material.PRODUCT
        assessment = MaterialReadiness(can_proceed=True, findings=[MaterialFinding(source_id='s',
            role='jd_and_product', sufficient=True, evidence=material.PRODUCT)])
        assessment.validate_request({'kind':'product','sources':[{'source_id':'s','content':body}]})
        wrong = MaterialReadiness(can_proceed=True, findings=[MaterialFinding(source_id='s',
            role='jd', sufficient=True, evidence=material.JD)])
        with self.assertRaises(ModelCallError):
            wrong.validate_request({'kind':'product','sources':[{'source_id':'s','content':body}]})
