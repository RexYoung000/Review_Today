"""Explicit live smoke with synthetic dialogue, isolated storage and no knowledge writes."""
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
    parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    with tempfile.TemporaryDirectory(prefix='review-today-topic-live-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'checkpoint.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        harness = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = str(uuid.uuid4())
        def turn(text, operation=None):
            started = time.monotonic()
            request = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text, operation=operation)
            accepted = harness.accept(sid, request)
            with patch('agent_service.conversation.run_capture', side_effect=AssertionError('This smoke must not save knowledge')):
                harness.drain(sid)
            state = harness.store.get(sid); run = state['runs'][accepted.run_id]
            replies = [m['content'] for m in state['messages'] if m['role'] == 'coach' and m['run_id'] == accepted.run_id]
            print(json.dumps(dict(input=text, seconds=round(time.monotonic()-started, 2), status=run['status'], intent=run.get('intent'), replies=replies,
                offers=[dict(id=o['id'], title=o['title'], status=o['status'], continuation_consumed=o['continuation_consumed']) for o in state.get('capture_offers', {}).values()]), ensure_ascii=False), flush=True)
            assert run['status'] == 'completed', run.get('error_code')
            return state, replies
        state, _ = turn('请简短说明 RAG 与微调的区别，只讲稳定的基础概念。')
        assert not state.get('capture_offers')
        state, _ = turn('明白了，接下来讲 Agent 的基本组成。')
        offers = list(state.get('capture_offers', {}).values())
        assert len(offers) == 1 and offers[0]['status'] == 'offered'
        offer = offers[0]
        state, _ = turn('稍后录入', dict(kind='capture_later', target_id=offer['id'], version=offer['version']))
        assert state['capture_offers'][offer['id']]['status'] == 'deferred'
        continued = state['runs'][state['capture_offers'][offer['id']]['continuation_run_id']]
        continued_replies = [m['content'] for m in state['messages'] if m['role'] == 'coach' and m['run_id'] == continued['run_id']]
        print(json.dumps(dict(continuation_status=continued['status'], continuation_replies=continued_replies), ensure_ascii=False), flush=True)
        assert continued['status'] == 'completed' and continued_replies
        assert (state.get('pending') or {}).get('kind') != 'new_session'
        state, replies = turn('算了，晚点再学吧')
        assert len(replies) == 1 and len(replies[0]) <= 100
        print('PASS: real answer → user closure → defer capture/continue once → short pause; no formal knowledge writes', flush=True)

if __name__ == '__main__': main()
