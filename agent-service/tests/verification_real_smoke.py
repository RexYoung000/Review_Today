"""A008 opt-in live search/read/assessment/coach check in an isolated database."""
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
    parser.add_argument('--fixed-routing', action='store_true', help='Isolate search/coach from the intent router; preparation, search, reads and answers still run live.')
    parser.add_argument('--expect-read-blocked', action='store_true', help='Verify honest degradation on a network whose public DNS answers are rejected; never counts as verified evidence.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-verification-live-') as directory:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(directory) / 'state.sqlite3')
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest, IntentDecision
        from agent_service.openai_client import web_search_capability, parse_model
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = str(uuid.uuid4())
        print(json.dumps({'fixed_routing': args.fixed_routing, 'expect_read_blocked': args.expect_read_blocked, 'search_adapter': web_search_capability()}), flush=True)
        questions = ['请查阅 Python 官方文档，用两三句话解释列表 append 和 extend 的区别，并附上来源。',
                     '针对刚才 append 和 extend 的区别，举个生活类比就好。']
        for index, text in enumerate(questions):
            def routed(system, user, schema, **kwargs):
                if schema is IntentDecision:
                    return IntentDecision(intents=['question' if index == 0 else 'example'], scope='conversation',
                                          relation='continuation', answer_only=True, needs_verification=index == 0,
                                          public_search_query='Python official documentation list append extend', rationale='synthetic verification test route')
                return parse_model(system, user, schema, **kwargs)
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text))
            with patch('agent_service.conversation.parse_model', side_effect=routed) if args.fixed_routing else nullcontext():
                h.drain(sid)
            data = h.store.get(sid); run = data['runs'][accepted.run_id]
            replies = [m['content'] for m in data['messages'] if m['role']=='coach' and m['run_id']==accepted.run_id]
            nodes = [e['node'] for e in data['events'] if e['run_id']==accepted.run_id]
            sources = run.get('teaching_sources', [])
            print(json.dumps(dict(input=text, status=run['status'], search_state=run.get('search_state'),
                                  evidence=run.get('teaching_evidence'), replies=replies, nodes=nodes,
                                  search_results=list(run.get('search_results', {}).values()),
                                  selected_sources=[v for v in run.get('steps', {}).values() if 'candidates' in v],
                                  read_sources=[dict(url=s.get('url'), title=s.get('title'), fetched_at=s.get('fetched_at'),
                                                     content_chars=len(s.get('content', ''))) for s in sources]), ensure_ascii=False), flush=True)
            assert run['status']=='completed' and replies
            if index == 0:
                assert 'search_attempt' in nodes and 'public_search' in nodes
                if args.expect_read_blocked:
                    assert run['search_state']=='insufficient'
                    assert '网页未能读取' in run.get('verification_notice', '')
                    assert not sources and not run['teaching_evidence']['sources']
                    assert any(e.get('detail_summary')=='public_address_required' for e in data['events'])
                    assert 'https://' not in replies[-1] and 'http://' not in replies[-1]
                    continue
                assert run['search_state']=='verified'
                assert sources and all(s.get('content') and s.get('fetched_at') for s in sources)
                urls = run['teaching_evidence']['sources']
                assert urls and all(u in {s['url'] for s in sources} for u in urls)
                assert any(u in replies[-1] for u in urls), 'The answer must display an actually read source.'
            else:
                assert 'search_attempt' not in nodes and 'public_search' not in nodes
                assert run['search_state']=='not_called'
                assert run['teaching_evidence']['state'] in ({'insufficient'} if args.expect_read_blocked else {'supported', 'scoped'})
                assert '[!NOTE]' not in replies[-1]
        print('PASS: real search, blocked reads reported honestly, follow-up without repeated notice; successful page verification remains untested.' if args.expect_read_blocked else 'PASS: real search, public page reads, evidence assessment and displayed sources; follow-up reuses evidence.', flush=True)


if __name__=='__main__': main()
