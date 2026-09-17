"""Opt-in A012 real semantic routing and multi-turn replies in an isolated DB."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.parse_args()
    failures = []
    with tempfile.TemporaryDirectory(prefix='review-social-dialogue-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))

        def send(sid, text, *, kind=None, preserve=False, no_task=True):
            before = copy.deepcopy(h.store.get(sid) or {})
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            h.drain(sid)
            data = h.store.get(sid)
            run = data['runs'][accepted.run_id]
            events = [e for e in data['events'] if e['run_id'] == accepted.run_id]
            replies = [m['content'] for m in data['messages'] if m['role']=='coach' and m['run_id']==accepted.run_id]
            checks = dict(completed=run['status']=='completed' and bool(replies),
                          no_web=not any(e['stage'] in {'web_provider', 'source_read', 'source_search'} for e in events),
                          no_new_capture=len(data.get('capture_offers', {}))==len(before.get('capture_offers', {})))
            if no_task:
                checks['no_task'] = not data['tasks']
            if kind:
                checks['kind'] = (run.get('intent') or {}).get('conversation_kind') == kind
                if kind != 'ordinary':
                    checks['bounded_route'] = run.get('social_reply_kind') == kind
                    checks['not_knowledge_activity'] = not run.get('activity_kind')
            if preserve:
                checks['preserved'] = all(before.get(k)==data.get(k) for k in ('tasks','active_task_id','pending','draft','focus_goal','teaching_context'))
            record = dict(input=text, status=run['status'], kind=(run.get('intent') or {}).get('conversation_kind'),
                intents=(run.get('intent') or {}).get('intents'), bounded_route=run.get('social_reply_kind'),
                first_text_ms=run.get('first_text_ms'), elapsed_ms=run.get('elapsed_ms'), replies=replies,
                checks=checks, stages=[e['stage'] for e in events if not e['stage'].startswith('response.')])
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if not all(checks.values()):
                failures.append(dict(input=text, failed=[k for k,v in checks.items() if not v]))
            return record

        sid = str(uuid.uuid4())
        send(sid, '你好', kind='social')
        send(sid, '谢谢', kind='social')
        send(sid, '今天有点累', kind='social')
        send(sid, '你可以陪我说说话吗', kind='companionship')
        send(sid, '就随便聊聊嘛', kind='companionship')
        send(sid, '今天不想学，只想随便聊', kind='companionship')
        send(sid, '最近复习总记不住，有点挫败，怎么办', kind='learning_support')
        send(sid, '今天很烦，顺便解释一下 RAG', kind='ordinary')
        send(sid, 'harness 是什么，有什么作用', kind='ordinary')
        send(sid, '算了，晚点再学吧')

        sid = str(uuid.uuid4())
        send(sid, '你好', kind='social')
        for text in ('我上一次说了什么', '真的吗', '你再看看'):
            send(sid, text)
        send(sid, '你可以陪我说说话吗', kind='companionship')

        sid = str(uuid.uuid4())
        send(sid, '我想系统学习 Python for 循环，请安排两个步骤，先讲第一步，只讲基础知识，不用搜索。', kind='ordinary', no_task=False)
        send(sid, '我学不进去，有点挫败，不要改学习计划，只给点调整状态的建议', kind='learning_support', preserve=True, no_task=False)
        send(sid, '陪我随便聊聊吧', kind='companionship', preserve=True, no_task=False)
        send(sid, '谢谢，继续讲解刚才的 for 循环', kind='ordinary', no_task=False)

    print(json.dumps(dict(result='FAIL' if failures else 'PASS', failures=failures), ensure_ascii=False), flush=True)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
