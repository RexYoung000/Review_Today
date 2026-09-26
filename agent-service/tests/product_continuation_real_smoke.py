"""Opt-in real dialogue models with synthetic material and an isolated database.

The first JD answer is deliberately interrupted after a real public preview.
Web reads are fixtures and public search is explicitly unavailable in this probe.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch


JD = '''岗位：AI 陪伴体验产品经理。职责：设计虚拟角色的人设与互动，围绕对话和情绪记录设计成长机制；设计首次体验到持续使用的路径，用原型与低成本测试验证，与工程和运营协作。要求：3 年 C 端产品或游戏策划经验，洞察用户需要，能在资源限制内取舍；AI 陪伴或互动内容经验优先。不把游戏化简单等同于签到积分。
公司产品介绍：Mello 提供 AI 日记、AI 课程和 AI 助教；以上仅为招聘介绍，未展示实际小程序页面。'''
PRODUCT = '补充 MELLO 首页截图里的文字：记录今天、情绪趋势、我的陪伴角色。底部有首页和我的。这里没有展示课程入口，不能确认是否存在。'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', required=True, action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite earlier evidence')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-product-continuation-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'harness.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest, JDAnalysis
        from agent_service.openai_client import parse_model
        from agent_service.call_errors import ModelCallError, WebToolError
        from agent_service.response_projection import public_preview
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = str(uuid.uuid4())
        report = dict(data='synthetic; no user data', models='real configured models',
            fault='one TIMEOUT injected after real JD preview; not an actual 90-second outage',
            web='fixture read failure; search disabled only inside probe', calls=[], turns=[])
        fault = {'armed': False}

        def write():
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

        def model(system, prompt, schema, **kw):
            call = dict(schema=schema.__name__, model=kw.get('model'), elapsed_ms=None)
            report['calls'].append(call)
            started = time.monotonic()
            if schema is JDAnalysis and fault['armed']:
                publish = kw['on_partial']
                def partial(value):
                    publish(value)
                    if len(public_preview('jd_analysis', value)) >= 150:
                        fault['armed'] = False
                        call['injected_timeout'] = True
                        raise ModelCallError('TIMEOUT', 'synthetic interrupted JD for continuation replay')
                kw['on_partial'] = partial
            try:
                output = parse_model(system, prompt, schema, **kw)
                call['status'] = 'returned'
                return output
            except Exception as error:
                call['error'] = getattr(error, 'code', type(error).__name__)
                raise
            finally:
                call['elapsed_ms'] = round((time.monotonic() - started) * 1000)

        def send(text, expected='completed'):
            ack = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            h.drain(sid)
            data = h.store.get(sid); run = data['runs'][ack.run_id]
            task = data['tasks'].get(data.get('active_task_id')) or {}
            turn = dict(input=text, status=run['status'], error_code=run.get('error_code'),
                intent=run.get('intent'), elapsed_ms=run.get('elapsed_ms'),
                task_id=data.get('active_task_id'), task_stage=task.get('stage'),
                task_required_action=task.get('required_action'),
                jd_version=task.get('context', {}).get('jd_analysis_version'),
                readiness=run.get('material_readiness'), model_calls=run.get('model_calls'),
                replies=[m['content'] for m in data['messages'] if m['role']=='coach' and m.get('run_id')==ack.run_id],
                preview=run.get('active_response'))
            report['turns'].append(turn); write()
            print(json.dumps(dict(turn=len(report['turns']), status=turn['status'],
                focus=(turn['intent'] or {}).get('material_focus'), elapsed_ms=turn['elapsed_ms']), ensure_ascii=False), flush=True)
            assert turn['status'] == expected, turn['error_code']
            return turn

        try:
            with patch('agent_service.conversation.parse_model', side_effect=model), \
                 patch('agent_service.conversation.fetch_public_url', side_effect=WebToolError('READ_FAILED')), \
                 patch('agent_service.conversation.web_search_capability', return_value={'status':'unavailable','provider':'synthetic-disabled'}):
                missing = send('我要准备面试，JD 在这里：https://example.com/job ，还让我了解微信小程序 MELLO')
                assert missing['task_stage'] == 'awaiting_material'
                fault['armed'] = True
                interrupted = send('补上 JD 截图中的文字：' + JD, expected='retryable_failed')
                assert interrupted['preview']['text'] and interrupted['task_stage'] == 'jd_analyzing'
                assert interrupted['task_required_action'] is None
                send('你能直接在微信里打开这个小程序吗？如果不行需要什么材料？')
                shared = send('#小程序://MELLO/synthetic-share-reference')
                assert shared['intent']['material_focus'] == 'product' and not shared['intent']['is_jd']
                assert not any(c['node']=='jd_analysis' for c in shared['model_calls'])
                assert shared['task_id'] == interrupted['task_id']
                supplied = send(PRODUCT)
                assert not any(c['node']=='jd_analysis' for c in supplied['model_calls'])
                retried = send('现在请重新分析刚才的 JD，给出完整的优先问题，简洁一点。')
                assert retried['task_stage'] == 'jd_analysis' and retried['jd_version'] == 1
                followup = send('刚才的首页资料能帮助我准备哪一点？只补充这一点，不要重写 JD。')
                assert not any(c['node']=='jd_analysis' for c in followup['model_calls'])
                assert followup['jd_version'] == 1
                public = send('请查一下这个产品的公开介绍，不要操作微信。')
                assert public['intent']['resource_boundary'] == 'none' and public['intent']['needs_verification']
            report['checks_passed'] = True
        finally:
            write()


if __name__ == '__main__':
    main()
