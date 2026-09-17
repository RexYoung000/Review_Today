"""Opt-in A013 live dialogue transitions, current plans and explicit old-goal recovery."""
import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    failures = []
    with tempfile.TemporaryDirectory(prefix='review-topic-transition-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore, HarnessTaskRecord
        from agent_service.goal_continuation import owns, ownership
        from agent_service.learning_progress import set_plan
        from agent_service.schemas import SessionMessageRequest
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))

        from tests.case_library.recording import RunReport
        output = args.output or Path(tempfile.gettempdir()) / f'review-case-flow-{uuid.uuid4()}.jsonl'
        with RunReport(output, layer='live_generated_flow', planned=[f'turn-{i:02}' for i in range(1, 10)],
                       fixture={'script': Path(__file__).name, 'history': 'preceding replies generated during this run'}) as report:
            def seed():
                sid, tid = str(uuid.uuid4()), str(uuid.uuid4())
                task = asdict(HarnessTaskRecord(task_id=tid, session_id=sid, client_message_id=str(uuid.uuid4()),
                    content='理解 RAG 的基本流程', content_type='text', primary_language='zh',
                    mode_preset='auto', mode='source_learning', status='awaiting_user', stage='teaching',
                    context={'conversation_managed':True, 'understanding':'unknown'}))
                set_plan(task, ['资料切分与建立索引', '检索与重排', '基于证据生成答案'])
                task['context']['learning_plan']['steps'][0]['state'] = 'explained'
                with h.store.transaction(sid) as data:
                    data['tasks'][tid] = task
                    data['active_task_id'] = tid
                h.memory_policy(sid, allowed=True, policy_version=0, content_version=0)
                return sid, tid

            def send(sid, text, *, expected='local', task_id=None, protected=None):
                before = copy.deepcopy(h.store.get(sid) or {})
                old = copy.deepcopy(h.store.get(protected[0])) if protected else None
                outcome = report.turn(h, sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
                data = h.store.get(sid)
                run = outcome['run']
                events = [e for e in data['events'] if e['run_id']==run['run_id']]
                replies = [m['content'] for m in data['messages'] if m['run_id']==run['run_id'] and m['role']=='coach']
                stages = [e['stage'] for e in events if not e['stage'].startswith('response.')]
                checks = dict(completed=run['status']=='completed' and bool(replies),
                    no_web=not any(s in {'web_provider','source_read','source_search'} for s in stages),
                    no_new_capture=len(data.get('capture_offers',{}))==len(before.get('capture_offers',{})))
                if expected in {'local','clarify','lesson','defer'}:
                    checks['no_recovery'] = not any(s.startswith('continuation_') for s in stages) and not run.get('goal_transfer')
                    checks['no_progress_error'] = not any('没有找到可接续' in r or '核对已有进度' in r or '打开原会话' in r for r in replies)
                if expected in {'local','clarify','missing'}:
                    checks['no_task'] = not data['tasks']
                if expected == 'clarify':
                    decision = run.get('intent') or {}
                    checks['content_clarification'] = decision.get('clarification_kind')=='content' and bool(decision.get('clarification'))
                    checks['short_reply'] = sum(len(r) for r in replies)<160
                    checks['not_understood'] = decision.get('understanding')=='unknown'
                    checks['no_extra_model_call'] = 'continuation_intent' not in stages and 'answer' not in stages
                if task_id:
                    current = data['tasks'][task_id]
                    previous = before['tasks'][task_id]
                    checks['same_goal'] = data['active_task_id']==task_id and ownership(current)==ownership(previous)
                    checks['not_mastered'] = current['context']['understanding']=='unknown'
                    checks['same_plan'] = [s['id'] for s in current['context']['learning_plan']['steps']]==[s['id'] for s in previous['context']['learning_plan']['steps']]
                if expected == 'lesson':
                    checks['teaching'] = 'lesson' in stages
                if expected == 'defer':
                    checks['no_lesson'] = 'lesson' not in stages and sum(len(r) for r in replies)<160
                if expected == 'resume':
                    checks['transferred'] = bool(run.get('goal_transfer')) and len(data['tasks'])==1
                if protected:
                    after = h.store.get(protected[0])
                    checks['old_goal_untouched'] = old==after and owns(after['tasks'][protected[1]])
                record = dict(input=text, expected=expected, status=run['status'], intent=run.get('intent'),
                    replies=replies, task_count=len(data['tasks']), checks=checks, stages=stages,
                    first_text_ms=run.get('first_text_ms'), elapsed_ms=run.get('elapsed_ms'))
                report.add(f'turn-{len(report.records) + 1:02}', outcome, checks)
                print(json.dumps(record, ensure_ascii=False), flush=True)
                if not all(checks.values()):
                    failures.append(dict(input=text, failed=[k for k,v in checks.items() if not v]))

            sid = str(uuid.uuid4())
            send(sid, '大模型是怎么生成回复的？简单讲一下原理。')
            send(sid, '好的，先这样吧，我们学下一个内容', expected='clarify')
            send(sid, '那 RAG 又是什么，有什么作用？')

            previous = seed()
            sid = str(uuid.uuid4())
            send(sid, '大模型是怎么生成回复的？简单讲一下原理。', protected=previous)
            send(sid, '好的，先这样吧，我们学下一个内容', expected='clarify', protected=previous)
            send(previous[0], '好的，先这样吧，我们学下一个内容', expected='lesson', task_id=previous[1])
            send(previous[0], '算了，晚点再学吧', expected='defer', task_id=previous[1])
            send(str(uuid.uuid4()), '继续上次没学完的 RAG', expected='resume')
            send(str(uuid.uuid4()), '继续上次没学完的光合作用', expected='missing')

    print(json.dumps(dict(result='PASS' if report.passed else 'FAIL', failures=failures, report=str(output)),ensure_ascii=False),flush=True)
    raise SystemExit(not report.passed)


if __name__ == '__main__':
    main()
