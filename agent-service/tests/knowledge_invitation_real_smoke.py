"""Opt-in real model checks with synthetic learning and an isolated checkpoint.

Saving exercises generation/verification, then uses a simulated Mac receipt.
This does not claim that the native app wrote real knowledge in this run.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    with tempfile.TemporaryDirectory(prefix='review-today-knowledge-invitation-live-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'checkpoint.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        harness = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = str(uuid.uuid4())
        report = dict(kind='real_model_synthetic_session', native_write=False, turns=[], checks={})
        def record():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        def turn(text, operation=None):
            started = time.monotonic()
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                content=text, mode_preset='source_learning', operation=operation))
            coach_calls = []
            evaluation_and_memory_outputs = []
            original_call = harness._call
            def trace_call(call_sid, rid, revision, node, system, prompt, schema, *positional, **kwargs):
                try:
                    payload = json.loads(prompt)
                except (ValueError, TypeError):
                    payload = None
                trace = None
                if isinstance(payload, dict) and 'capture_candidates' in payload:
                    task = payload.get('context', {}).get('task') or {}
                    trace = dict(node=node, schema=schema.__name__, task_id=task.get('task_id'),
                        task_status=task.get('status'), task_stage=task.get('stage'),
                        capture_candidates=payload['capture_candidates'],
                        update_instruction_present='本轮 capture_candidates' in system)
                    coach_calls.append(trace)
                output = original_call(call_sid, rid, revision, node, system, prompt, schema, *positional, **kwargs)
                if node == 'evaluate' or node.startswith('memory_'):
                    evaluation_and_memory_outputs.append(dict(node=node, output=output.model_dump()))
                if trace is not None:
                    update = getattr(output, 'capture_update', None)
                    trace['returned_capture_update'] = update.model_dump() if update else None
                    trace['returned_learning_concepts'] = getattr(output, 'learning_concepts', [])
                return output
            with patch.object(harness, '_call', side_effect=trace_call):
                harness.drain(sid)
            data = harness.store.get(sid)
            run = data['runs'][accepted.run_id]
            row = dict(input=text, seconds=round(time.monotonic() - started, 2), status=run['status'],
                error=run.get('error_code'), intent=run.get('intent'),
                run_state={k: run.get(k) for k in ('run_id', 'revision', 'task_id', 'lifecycle_revision',
                    'dialogue_only', 'knowledge_status_reply', 'execution_complete', 'capture_scope_update',
                    'evaluated_binding', 'verified_concepts', 'capture_quotes', 'capture_feedback_quotes')},
                session_state=dict(active_task_id=data.get('active_task_id'), lifecycle_revision=data.get('lifecycle_revision', 0),
                    draft_id=(data.get('draft') or {}).get('id'), draft_version=(data.get('draft') or {}).get('version')),
                task_states=[dict(task_id=t['task_id'], mode=t['mode'], stage=t['stage'], status=t['status'],
                    understanding=t['context'].get('understanding'), requires_mastery=t['context'].get('requires_mastery'),
                    memory_invalidated=t['context'].get('memory_invalidated', False),
                    learning_plan=t['context'].get('learning_plan')) for t in data['tasks'].values()],
                coach_calls=coach_calls,
                replies=[m['content'] for m in data['messages'] if m['role'] == 'coach' and m['run_id'] == accepted.run_id],
                offers=[{k: o.get(k) for k in ('id', 'version', 'trigger', 'title', 'scope_summary', 'status',
                    'origin_task_id', 'lifecycle_revision', 'anchor_message_id', 'correction_pending',
                    'correction_run_id', 'fragments')}
                        for o in data.get('capture_offers', {}).values()],
                model_calls=len(run.get('model_calls', [])))
            row['model_usage'] = run.get('model_calls', [])
            row['evaluation_and_memory_outputs'] = evaluation_and_memory_outputs
            row['errors'] = [{k: e.get(k) for k in ('stage', 'error', 'detail', 'payload')}
                             for e in data['events'] if e.get('run_id') == accepted.run_id and e.get('error')]
            report['turns'].append(row)
            record()
            print(json.dumps(row, ensure_ascii=False), flush=True)
            assert run['status'] == 'completed', run.get('error_code')
            return data
        data = turn('直接教我一个小知识点：向量检索中，相似度高为什么不保证答案正确？只讲这个知识点，简短解释后出一道让我用自己的话复述的检查题。讲稳定原理，不需要网页搜索。')
        assert not data.get('capture_offers')
        data = turn('相似度高只说明向量表示接近，可能有助于找相关材料，但相关不等于材料真实，生成回答也可能出错，所以还需要核对来源、适用条件和答案依据。')
        offer = next(o for o in data.get('capture_offers', {}).values() if o.get('trigger') == 'verified_check')
        identity, version = offer['id'], offer['version']
        report['checks']['pass_invites_without_generation'] = not any(t['mode'] == 'memory_organization' for t in data['tasks'].values())
        assert report['checks']['pass_invites_without_generation']
        data = turn('继续补充刚才这个知识点：为什么相关的材料也可能过时？请把这个边界解释清楚，不开始新知识点。')
        updated = data['capture_offers'][identity]
        report['checks']['same_invitation_scope_updated'] = updated['version'] > version
        record()
        assert report['checks']['same_invitation_scope_updated']
        version = updated['version']
        data = turn('把刚才这个边界再纠正准确：向量编码可能捕捉文本中的时间信息，不能笼统说向量完全没有时间信息；但相似度仍不保证资料时效。请保留这个准确边界，不开始新知识点。')
        corrected = data['capture_offers'][identity]
        report['checks']['correction_updates_same_invitation'] = corrected['version'] > version and not corrected.get('correction_pending')
        record()
        assert report['checks']['correction_updates_same_invitation']
        version = corrected['version']
        data = turn('现在只解释另一个知识点：文档切块的重叠部分有什么作用？不要把这个新知识点合并到刚才向量相似度的内容里，也暂不出题。')
        report['checks']['new_concept_not_merged'] = data['capture_offers'][identity]['version'] == version
        record()
        assert report['checks']['new_concept_not_merged']
        offer = data['capture_offers'][identity]
        data = turn('新增知识', dict(kind='capture_save', target_id=identity, version=offer['version']))
        offer = data['capture_offers'][identity]
        assert offer['status'] == 'saving', offer
        task = data['tasks'][offer['save_task_id']]
        report['generated_knowledge'] = task['memory_package']
        report['selected_source'] = task['memory_source_text']
        ids = [k['id'] for k in task['memory_package']['knowledge']]
        report['checks']['before_receipt_not_saved'] = offer['status'] != 'saved'
        with patch.object(harness, 'start'):
            harness.acknowledge_task(task['task_id'], len(task['events']), ids)
        data = harness.store.get(sid)
        offer = data['capture_offers'][identity]
        report['checks']['simulated_receipt_saved_no_auto_continue'] = offer['status'] == 'saved' and 'continuation_run_id' not in offer
        assert report['checks']['simulated_receipt_saved_no_auto_continue']
        data = turn('刚才关于向量相似度不保证正确的知识卡保存了吗？')
        status = next(e for e in reversed(data['events']) if e['stage'] == 'knowledge_status')
        report['checks']['queried_saved_topic_after_different_topic'] = status['payload']['stage'] == 'saved'
        record()
        assert report['checks']['queried_saved_topic_after_different_topic']
        print('PASS: real model invitation/update/scope/save; simulated Mac receipt only', flush=True)


if __name__ == '__main__':
    main()
