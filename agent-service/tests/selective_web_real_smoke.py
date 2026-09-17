"""Opt-in A011 live replay: isolated DB, real intent/model/search/read, safe logs."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-selective-web-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))

        def send(sid, text, searched):
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            h.drain(sid)
            data = h.store.get(sid)
            run = data['runs'][accepted.run_id]
            events = [e for e in data['events'] if e['run_id'] == accepted.run_id]
            reply = [m['content'] for m in data['messages'] if m['role']=='coach' and m['run_id']==accepted.run_id]
            record = dict(input=text, status=run['status'], intent=run.get('intent'), first_text_ms=run.get('first_text_ms'),
                elapsed_ms=run.get('elapsed_ms'), search_state=run.get('search_state'), replies=reply,
                events=[{k:e.get(k) for k in ('stage','user_summary','duration_ms')} for e in events if not e['stage'].startswith('response.')],
                providers=[e['payload'] for e in events if e['stage']=='web_provider'],
                sources=[dict(url=s.get('url'), chars=len(s.get('content',''))) for s in run.get('teaching_sources',[])])
            print(json.dumps(record, ensure_ascii=False), flush=True)
            assert run['status']=='completed' and reply, 'answer failed'
            assert not data['tasks'], 'ordinary question created a learning task'
            if searched:
                assert run['search_state']=='verified' and record['sources'], 'real web verification failed'
            else:
                assert run['search_state']=='not_called' and not record['providers'], 'unexpected web call'
                assert '[!NOTE]' not in reply[-1], 'unnecessary verification warning'
            return record

        sid = str(uuid.uuid4())
        send(sid, 'harness是什么意思，有什么作用', False)
        send(sid, '给刚才的 Agent harness 举个生活类比就好', False)
        sid = str(uuid.uuid4())
        record = send(sid, '请搜索 Python 官方文档，核验 for 循环如何遍历列表，给出可点击的原始出处。', True)
        assert sum(e['status']=='started' and e['operation']=='read' for e in record['providers']) <= 3
        send(sid, '用刚才的官方资料，再举一个更简单的例子，不用重新搜索', False)
        print('PASS: real stable knowledge and follow-up skip web; explicit official verification and evidence reuse.', flush=True)


if __name__ == '__main__':
    main()
