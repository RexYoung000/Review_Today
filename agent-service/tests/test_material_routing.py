"""Replay supplied material through the real Harness with isolated fixtures."""
import json
import threading
import unittest
import uuid
from dataclasses import asdict
from unittest.mock import patch

from agent_service.capture.fetch import extract_urls
from agent_service.conversation_materials import MaterialReadiness, MaterialFinding
from agent_service.schemas import JDAnalysis, ConversationOutput
from agent_service.source_content import readable_page
from agent_service.call_errors import WebToolError, ModelCallError
from agent_service.harness_store import HarnessTaskRecord
from tests import test_conversation_v2 as base

JD = '岗位职责：负责知识检索产品的需求分析与质量评估。任职要求：有用户访谈经验，理解召回率和准确率。'
PRODUCT = 'EMOX 产品说明：一个用于记录每日阅读笔记的小程序，支持按主题检索自己的笔记。'
SHELL = 'window.matchMedia("screen"); var a=document.cookie; function(){window.location.href="login";};'
URL = 'https://example.com/job'
PRODUCT_URL = 'https://example.com/product'


class MaterialRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = base.ConversationTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.outputs = []
        self.readiness = []
        self.jd_inputs = []
        self.model_patch = patch('agent_service.conversation.parse_model', side_effect=self.model)
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def model(self, system, user, schema, **kw):
        payload = json.loads(user)
        if schema is MaterialReadiness:
            self.readiness.append(payload)
            findings = []
            for source in payload['sources']:
                body = source['content']
                role = 'jd' if JD in body else 'product' if PRODUCT in body else 'other'
                findings.append(MaterialFinding(source_id=source['source_id'], role=role,
                    sufficient=role != 'other', evidence=JD if role == 'jd' else PRODUCT if role == 'product' else ''))
            proceed = any(f.sufficient and (payload['kind'] != 'jd' or f.role == 'jd') for f in findings)
            return MaterialReadiness(can_proceed=proceed, findings=findings,
                missing=[] if any(f.role == 'product' for f in findings) else ['EMOX 的实际产品内容尚未提供。'],
                reply='' if proceed else '你这次要准备面试，但链接还没有提供可用的岗位正文。请贴出岗位职责和任职要求，我们接着分析这个岗位。')
        if schema is JDAnalysis:
            self.jd_inputs.append(payload)
            if self.outputs:
                value = self.outputs.pop(0)
                if isinstance(value, Exception):
                    kw['on_partial']({'role_goal': '半截岗位分析'})
                    raise value
            return JDAnalysis(role_goal='岗位侧重知识检索产品的需求与评估', competency_map=['需求分析与质量评估'],
                              risk_points=['项目经历尚未提供，暂不能判断个人差距'], prioritized_questions=['如何评估检索质量？'])
        return self.f.model(system, user, schema, **kw)

    def jd(self, **overrides):
        self.f.decision = base.intent('material', 'goal', workflow='source_learning', is_jd=True,
            jd_request='analyze', target_description='根据 JD 和产品资料准备面试', **overrides)

    def test_actual_three_turn_route_halts_on_script_and_resumes_same_goal(self):
        self.f.decision = base.intent('greeting', light_reply='你好，我是学习教练。')
        self.f.send('你好')
        self.f.decision = base.intent('social', conversation_kind='background', light_reply='方便提供这次面试的岗位信息吗？')
        self.f.send('我最近有一个面试')
        self.assertEqual(self.f.state()['tasks'], {})
        self.jd()
        with patch('agent_service.conversation.fetch_public_url', return_value=('招聘页面', SHELL)) as reader:
            failed = self.f.send(URL + ' JD在这里，他还让我去看微信小程序 EMOX')
        data = self.f.state()
        task_id = data['active_task_id']
        task = data['tasks'][task_id]
        self.assertEqual(task['stage'], 'awaiting_material')
        self.assertNotIn('learning_plan', task['context'])
        self.assertEqual(self.jd_inputs, [])
        self.assertEqual(data['runs'][failed.run_id]['status'], 'completed')
        self.assertFalse(any(e['stage'] == 'source_read' and e['user_summary'] == '网页内容已读取' for e in data['events']))
        self.assertEqual(data['runs'][failed.run_id]['material_reads'][0]['state'], 'unavailable')
        reader.assert_called_once()
        # The router need not re-infer the interview goal when the missing text arrives.
        self.f.decision = base.intent('material', scope='continue_goal', workflow='source_learning')
        with patch('agent_service.conversation.fetch_public_url') as no_read:
            self.f.send('补上 JD 正文：' + JD)
        data = self.f.state()
        self.assertEqual(data['active_task_id'], task_id)
        self.assertEqual(len(data['tasks']), 1)
        self.assertEqual(data['tasks'][task_id]['stage'], 'jd_analysis')
        self.assertIn(JD, json.dumps(self.jd_inputs[-1], ensure_ascii=False))
        self.assertEqual(data['pending']['kind'], 'select_question')
        no_read.assert_not_called()
        self.assertNotIn(ConversationOutput, [schema for schema, _ in self.f.calls])

    def test_multiple_urls_deduplicated_and_original_body_reaches_jd(self):
        self.jd()
        def read(url, **kwargs):
            return ('职位', JD) if url == URL else ('产品', PRODUCT)
        with patch('agent_service.conversation.fetch_public_url', side_effect=read) as reader:
            self.f.send(f'JD：{URL}\n产品：{PRODUCT_URL}\n同一个JD：{URL}')
        self.assertEqual(reader.call_count, 2)
        payload = self.jd_inputs[0]
        self.assertNotEqual(payload['goal'], JD)
        self.assertTrue(any(s['content'] == JD for s in payload['sources']))
        self.assertTrue(any(s['content'] == PRODUCT for s in payload['sources']))
        self.assertEqual(payload['materials']['missing'], [])
        self.assertEqual(self.f.state()['pending']['version'], 1)

    def test_readable_but_irrelevant_job_page_does_not_start_analysis(self):
        self.jd()
        with patch('agent_service.conversation.fetch_public_url', return_value=('招聘首页', '欢迎来这里寻找下一份工作。这里有很多职位供你选择。')):
            self.f.send(URL + ' 帮我准备这个岗位的面试')
        task = self.f.state()['tasks'][self.f.state()['active_task_id']]
        self.assertEqual(task['stage'], 'awaiting_material')
        self.assertEqual(self.jd_inputs, [])

    def test_partial_material_product_failure_does_not_block_actual_jd(self):
        self.jd()
        def read(url, **kwargs):
            if url == PRODUCT_URL:
                raise WebToolError('READ_FAILED')
            return ('职位', JD)
        with patch('agent_service.conversation.fetch_public_url', side_effect=read):
            self.f.send(f'JD {URL} 产品 {PRODUCT_URL}')
        data = self.f.state()
        self.assertEqual(data['tasks'][data['active_task_id']]['stage'], 'jd_analysis')
        reply = [m['content'] for m in data['messages'] if m['role'] == 'coach'][-1]
        self.assertIn('尚未提供', reply)
        self.assertNotIn(PRODUCT, reply)
        self.assertNotIn(PRODUCT_URL, self.f.state()['runs'][next(reversed(data['runs']))]['allowed_source_urls'])

    def test_continue_without_missing_body_still_waits_and_retains_failure_reason(self):
        self.jd()
        with patch('agent_service.conversation.fetch_public_url', return_value=('职位', SHELL)):
            self.f.send(URL)
        self.f.decision = base.intent('continue', scope='continue_goal', workflow='source_learning')
        with patch('agent_service.conversation.fetch_public_url') as reader:
            self.f.send('继续')
        reader.assert_not_called()
        data = self.f.state()
        self.assertEqual(data['tasks'][data['active_task_id']]['stage'], 'awaiting_material')
        self.assertTrue(self.readiness[-1]['reads'])
        self.assertEqual(self.jd_inputs, [])

    def test_four_url_limit_records_unread_source_without_claiming_success(self):
        self.jd()
        urls = [URL + str(i) for i in range(5)]
        with patch('agent_service.conversation.fetch_public_url', return_value=('职位', JD)) as reader:
            self.f.send('\n'.join(urls))
        self.assertEqual(reader.call_count, 4)
        self.assertEqual(self.readiness[-1]['reads'][-1], dict(url=urls[-1], state='not_read', reason='per_turn_limit'))

    def test_read_and_answer_only_does_not_create_an_organization_draft(self):
        self.f.decision = base.intent('material', 'question', answer_only=True)
        with patch('agent_service.conversation.fetch_public_url', return_value=('产品', PRODUCT)):
            self.f.send('读这个链接，简单说两个特点：' + PRODUCT_URL)
        data = self.f.state()
        self.assertFalse(data['tasks'])
        self.assertFalse(data.get('draft'))
        self.assertIsNone(data['pending'])
        self.assertIn(PRODUCT_URL, data['messages'][-1]['content'])

    def test_unusable_cached_body_is_reread_before_analysis(self):
        self.jd()
        ack = self.f.send(URL, drain=False)
        with self.f.store.transaction(self.f.sid) as data:
            data['runs'][ack.run_id]['source_cache'] = {URL: dict(url=URL, title='职位', content=SHELL)}
        with patch('agent_service.conversation.fetch_public_url', return_value=('职位', JD)) as reader:
            self.f.harness.drain(self.f.sid)
        reader.assert_called_once()
        self.assertTrue(any(s['content'] == JD for s in self.jd_inputs[0]['sources']))

    def test_retry_old_misrouted_task_reclassifies_and_keeps_task_identity(self):
        self.jd()
        ack = self.f.send('JD在这里：' + URL, drain=False)
        task_id = str(uuid.uuid4())
        with self.f.store.transaction(self.f.sid) as data:
            task = asdict(HarnessTaskRecord(task_id=task_id, session_id=self.f.sid,
                client_message_id=ack.message_id, content='根据岗位材料准备面试', content_type='text',
                primary_language='zh', mode_preset='auto', mode='source_learning',
                context={'conversation_managed': True, 'origin_run_id': ack.run_id}))
            task.update(status='retryable_failed', stage='accepted')
            data['tasks'][task_id] = task
            data['active_task_id'] = task_id
            run = data['runs'][ack.run_id]
            old = self.f.decision.model_dump(); old.pop('jd_request')
            run.update(task_id=task_id, status='retryable_failed', dialogue_policy='dialogue-context-3',
                       intent=old, decision_mode='auto', decision_input_ids=list(run['input_ids']),
                       source_cache={URL: dict(url=URL, title='职位', content=SHELL)})
            data['foreground'] = None
            data['paused'] = True
        self.f.control(ack.run_id, 'retry')
        with patch('agent_service.conversation.fetch_public_url', return_value=('职位', JD)):
            self.f.harness.drain(self.f.sid)
        data = self.f.state()
        self.assertEqual(data['active_task_id'], task_id)
        self.assertEqual(data['tasks'][task_id]['mode'], 'problem_solving')
        self.assertEqual(data['tasks'][task_id]['stage'], 'jd_analysis')
        self.assertNotIn('learning_plan', data['tasks'][task_id]['context'])

    def test_schema_repair_does_not_reread_or_change_question_version(self):
        self.jd()
        self.outputs = [ModelCallError('SCHEMA')]
        with patch('agent_service.conversation.fetch_public_url', return_value=('职位', JD)) as reader:
            self.f.send(URL)
        reader.assert_called_once()
        self.assertEqual(len(self.jd_inputs), 2)
        self.assertEqual(self.jd_inputs[0], self.jd_inputs[1])
        data = self.f.state()
        self.assertEqual(data['pending']['version'], 1)
        replies = [m for m in data['messages'] if m['role'] == 'coach']
        self.assertEqual(len(replies), 1)
        self.assertNotIn('半截', replies[0]['content'])
        stream = [e['payload']['response'] for e in data['events'] if 'response' in e.get('payload', {})]
        self.assertEqual(len({r['response_id'] for r in stream}), 1)
        self.assertIn('recovering', [r['status'] for r in stream])

    def test_method_request_and_quoted_url_never_enter_jd_analysis(self):
        self.f.decision = base.intent('goal', workflow='source_learning', is_jd=True,
            jd_request='method', direct_teaching=True, target_description='学习如何拆解 JD')
        self.f.send('教我如何拆解 JD 的方法')
        self.assertEqual(self.jd_inputs, [])
        self.assertEqual(self.readiness, [])
        self.f.decision = base.intent('question', answer_only=True)
        with patch('agent_service.conversation.fetch_public_url') as reader:
            self.f.send('URL 中 https://example.com/job 这串字符是什么结构？')
        reader.assert_not_called()

    def test_cancel_during_read_cannot_publish_or_analyze(self):
        self.jd()
        entered, closed = threading.Event(), threading.Event()
        def read(url, on_cancel_handle):
            on_cancel_handle(closed.set)
            entered.set()
            closed.wait(2)
            return '职位', JD
        with patch('agent_service.conversation.fetch_public_url', side_effect=read):
            accepted = self.f.send(URL, drain=False)
            thread = threading.Thread(target=self.f.harness.drain, args=(self.f.sid,))
            thread.start()
            self.assertTrue(entered.wait(2))
            self.f.control(accepted.run_id, 'stop')
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.jd_inputs, [])
        self.assertFalse([m for m in self.f.state()['messages'] if m['role'] == 'coach'])


class ReadableContentTests(unittest.TestCase):
    def test_shell_login_and_title_are_not_body(self):
        for body in [SHELL, '<html><script>window.x=1</script></html>', '请登录后查看完整岗位内容', '标题']:
            with self.subTest(body=body), self.assertRaises(WebToolError):
                readable_page(('标题', body))

    def test_real_article_with_code_keeps_prose(self):
        body = '下面介绍浏览器接口怎样工作，以及它们在实际页面中的使用方式。\n```js\n' + SHELL + '\n```'
        self.assertEqual(readable_page(('文档', body))[1], body)
        self.assertEqual(readable_page(('职位', JD)), ('职位', JD))

    def test_url_candidates_preserve_order_and_chinese_boundaries(self):
        self.assertEqual(extract_urls(f'JD（{URL}），产品 {PRODUCT_URL}。重复 [{URL}]({URL})'), [URL, PRODUCT_URL])

    def test_claims_without_existing_literal_source_evidence_are_invalid(self):
        payload = dict(kind='jd', sources=[dict(source_id='one', content=JD)])
        for finding in [MaterialFinding(source_id='missing', role='jd', sufficient=True, evidence=JD),
                        MaterialFinding(source_id='one', role='jd', sufficient=True, evidence='编造的岗位要求')]:
            with self.assertRaises(ModelCallError):
                MaterialReadiness(can_proceed=True, findings=[finding]).validate_request(payload)
