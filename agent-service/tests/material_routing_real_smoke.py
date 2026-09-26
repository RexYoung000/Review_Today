"""Opt-in real models, synthetic material, isolated DB; one actual public URL read."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', required=True, action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--public-only', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite prior evidence')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-material-replay-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'harness.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest, JDAnalysis
        from agent_service.openai_client import parse_model
        from agent_service.call_errors import ModelCallError
        from agent_service.web_tools import read_public_url
        from tests.test_material_routing import JD, PRODUCT, SHELL, URL, PRODUCT_URL
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        result = dict(version='material-routing-v1', data='synthetic', models='real configured providers',
                      reads='synthetic fixtures except final public Python URL', calls=[], turns=[], page_reads=[])
        fault = {'inject': False}
        def record_call(system, prompt, schema, **kwargs):
            start = time.monotonic()
            entry = dict(schema=schema.__name__, model=kwargs.get('model'), system=system, input=prompt)
            result['calls'].append(entry)
            try:
                value = parse_model(system, prompt, schema, **kwargs)
                entry['output'] = value.model_dump()
                if schema is JDAnalysis and fault['inject']:
                    fault['inject'] = False
                    entry['injected_fault'] = 'SCHEMA after real streaming output; controlled fault only'
                    raise ModelCallError('SCHEMA')
                return value
            except Exception as exc:
                entry['error'] = getattr(exc, 'code', type(exc).__name__)
                raise
            finally:
                entry['elapsed_ms'] = round((time.monotonic()-start)*1000)
        def read(url, **kwargs):
            result['page_reads'].append(url)
            if url == 'https://example.com/job-unreadable': return '招聘页', SHELL
            if url == URL: return '合成测试岗位', JD
            if url == PRODUCT_URL: return 'EMOX 合成产品材料', PRODUCT
            return read_public_url(url, **kwargs)
        def send(sid, text):
            ack = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            h.drain(sid)
            data = h.store.get(sid); run = data['runs'][ack.run_id]
            task = data['tasks'].get(data.get('active_task_id'))
            entry = dict(input=text, status=run['status'], intent=run.get('intent'), elapsed_ms=run['elapsed_ms'],
                first_text_ms=run.get('first_text_ms'), material_reads=run.get('material_reads'),
                readiness=run.get('material_readiness'), task_id=data.get('active_task_id'), task_stage=(task or {}).get('stage'),
                model_calls=run.get('model_calls', []),
                replies=[m['content'] for m in data['messages'] if m['role']=='coach' and m['run_id']==ack.run_id],
                events=[{k:e.get(k) for k in ('stage','user_summary','duration_ms','error_code')}
                        for e in data['events'] if e['run_id']==ack.run_id and e['stage']!='response.delta'])
            result['turns'].append(entry)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({k:entry[k] for k in ('status','task_stage','elapsed_ms')}, ensure_ascii=False), flush=True)
            assert run['status']=='completed' and entry['replies'], 'turn did not complete'
            return entry, task
        try:
            with patch('agent_service.conversation.parse_model', side_effect=record_call), patch('agent_service.conversation.fetch_public_url', side_effect=read):
                if not args.public_only:
                    sid = str(uuid.uuid4())
                    _, task = send(sid, '你好'); assert task is None
                    _, task = send(sid, '我最近有一个面试'); assert task is None
                    missing, task = send(sid, 'JD在这里：https://example.com/job-unreadable ，他还让我去看微信小程序 EMOX')
                    assert missing['task_stage']=='awaiting_material' and not task['context'].get('learning_plan')
                    supplement, task = send(sid, '补上岗位正文：' + JD)
                    assert supplement['task_id']==missing['task_id'] and supplement['task_stage']=='jd_analysis'
                    assert not task['context'].get('learning_plan')
                    assert supplement['readiness']['missing'], 'unknown product must remain explicit'
                    fault['inject'] = True
                    combined, _ = send(str(uuid.uuid4()), '我要准备这个岗位的面试，请分析 JD 和产品材料，列出最值得先练的问题。\nJD：'+URL+'\n产品：'+PRODUCT_URL)
                    assert combined['task_stage']=='jd_analysis' and len(combined['material_reads'])==2
                    assert any(e['stage']=='response.recovering' for e in combined['events'])
                    assert sum(c['node']=='jd_analysis' for c in combined['model_calls'])==2
                final, _ = send(str(uuid.uuid4()), '请阅读 https://docs.python.org/3/tutorial/datastructures.html ，简短概括列表的两个常用操作，不需要出题。')
                assert any(r['state']=='body_read' for r in final['material_reads']), 'public page was not read'
                assert final['readiness']['can_proceed']
                assert final['task_id'] is None
                assert final['intent']['answer_only']
            result['result'] = 'passed'
        except Exception as exc:
            result.update(result='failed', failure=str(exc))
            raise
        finally:
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
