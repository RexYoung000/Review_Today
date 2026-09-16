"""A006 opt-in synthetic live reproduction, isolated from the user's history."""
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
    with tempfile.TemporaryDirectory(prefix='review-dialogue-live-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        from agent_service.dialogue_routing import LEGACY_QUESTION
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = str(uuid.uuid4())
        for index, text in enumerate(['什么叫 harness', '我不是才和你聊天吗']):
            if index:
                with h.store.transaction(sid) as d:
                    d['messages'][-1]['content'] = LEGACY_QUESTION
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            h.drain(sid)
            data = h.store.get(sid); run = data['runs'][accepted.run_id]
            replies = [m['content'] for m in data['messages'] if m['role']=='coach' and m['run_id']==accepted.run_id]
            print(json.dumps(dict(input=text, status=run['status'], intent=run.get('intent'), replies=replies, tasks=len(data['tasks'])), ensure_ascii=False), flush=True)
            assert run['status']=='completed' and replies
            assert all(LEGACY_QUESTION not in reply for reply in replies)
            assert not data['tasks']
            if index: assert run.get('dialogue_only') and run.get('resolved_input')=='什么叫 harness'
        print('PASS: independent first question and legacy conversation repair.', flush=True)

if __name__=='__main__': main()
