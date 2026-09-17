"""A010 opt-in real routing/answer replay; all state stays in a temporary DB."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import uuid
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-ordinary-question-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest, IntentDecision
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))

        def send(sid, content):
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=content))
            h.drain(sid)
            state = h.store.get(sid)
            run = state['runs'][accepted.run_id]
            replies = [m['content'] for m in state['messages'] if m['role']=='coach' and m['run_id']==accepted.run_id]
            events = [e for e in state['events'] if e['run_id']==accepted.run_id]
            print(json.dumps(dict(input=content, status=run['status'], intent=run.get('intent'),
                resolved_input=run.get('resolved_input'), replies=replies,
                task_states=[{k:t.get(k) for k in ('status','stage','required_action')} for t in state['tasks'].values()],
                nodes=[e['node'] for e in events], search_state=run.get('search_state'),
                provider_events=[e.get('payload') for e in events if e['node']=='web_provider'],
                preparation=[v for v in run.get('steps',{}).values() if 'public_query' in v],
                sources=[dict(url=s.get('url'), chars=len(s.get('content',''))) for s in run.get('teaching_sources',[])]),ensure_ascii=False),flush=True)
            assert run['status']=='completed' and replies
            return state, run, replies

        sid = str(uuid.uuid4())
        for content in ['你好','我不知道','harness是什么，它有什么作用','给刚才的 Agent harness 举个生活类比就好']:
            state, run, replies = send(sid, content)
            assert not state['tasks'], 'ordinary conversation created a learning task'
            assert not state.get('pending'), 'ordinary conversation was blocked by a pending operation'
            assert '你最希望学完' not in replies[-1]
            if content.startswith('harness'):
                assert 'agent' in replies[-1].lower() or '智能体' in replies[-1], 'ambiguous harness narrowed to testing only'
            if content.startswith('给刚才'):
                assert run['search_state']=='not_called', 'same-topic example repeated search'

        # Seed only the legacy routing mistake; the correction turn is fully live.
        sid = str(uuid.uuid4())
        legacy = IntentDecision(intents=['goal'], relation='new_topic', scope='learning',
                                workflow='topic_exploration', rationale='synthetic legacy task seed')
        with patch('agent_service.conversation.parse_model', return_value=legacy):
            state, origin, _ = send(sid, 'harness是什么，它有什么作用')
        tid = state['active_task_id']
        with h.store.transaction(sid) as current:
            current['runs'][origin['run_id']]['intent']['intents'] = ['question']
        state, run, replies = send(sid, '我只是问它是什么，不是要你安排学习，先回答我的问题')
        assert run.get('resolved_input')=='harness是什么，它有什么作用'
        assert state['tasks'][tid]['status']=='cancelled' and state['active_task_id'] is None
        assert '你最希望学完' not in replies[-1]
        print('PASS: real ordinary-question routing and example, plus live repair of a seeded legacy task.',flush=True)


if __name__ == '__main__':
    main()
