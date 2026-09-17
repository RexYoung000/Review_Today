"""A008 opt-in live coach check with synthetic inputs and an isolated database."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import uuid
from contextlib import nullcontext
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--fixed-routing', action='store_true', help='Isolate verification/coach from the intent router; preparation and answers still use real models.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-verification-live-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest, IntentDecision
        from agent_service.openai_client import web_search_capability, parse_model
        assert web_search_capability()['status'] == 'unavailable', 'This scenario checks the known unavailable service only.'
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = str(uuid.uuid4())
        print(json.dumps({'fixed_routing': args.fixed_routing}), flush=True)
        for index, text in enumerate(['什么是 RAG？用两三句话解释。', '针对刚才的检索再生成，举个生活类比就好。']):
            def routed(system, user, schema, **kwargs):
                if schema is IntentDecision:
                    return IntentDecision(intents=['question' if index == 0 else 'example'], scope='conversation',
                                          relation='continuation', answer_only=True, public_search_query='RAG', rationale='synthetic verification test route')
                return parse_model(system, user, schema, **kwargs)
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            with patch('agent_service.conversation.parse_model', side_effect=routed) if args.fixed_routing else nullcontext():
                h.drain(sid)
            data = h.store.get(sid); run = data['runs'][accepted.run_id]
            replies = [m['content'] for m in data['messages'] if m['role']=='coach' and m['run_id']==accepted.run_id]
            nodes = [e['node'] for e in data['events'] if e['run_id']==accepted.run_id]
            print(json.dumps(dict(input=text, status=run['status'], search_state=run.get('search_state'),
                                  evidence=run.get('teaching_evidence'), replies=replies, nodes=nodes), ensure_ascii=False), flush=True)
            assert run['status']=='completed' and replies
            assert 'search_attempt' not in nodes and 'public_search' not in nodes
            if index == 0:
                assert run['search_state']=='unavailable'
                assert '网页检索服务不可用' in replies[-1]
            else:
                assert run['search_state']=='not_called'
                assert run['teaching_evidence']['state']=='insufficient'
                assert '[!NOTE]' not in replies[-1]
                assert '网页核验' not in replies[-1] and '另行查证' not in replies[-1], 'The coach must not paraphrase the old generic notice.'
        print('PASS: unavailable search is honest; a same-topic example does not repeat the service notice.', flush=True)


if __name__=='__main__': main()
