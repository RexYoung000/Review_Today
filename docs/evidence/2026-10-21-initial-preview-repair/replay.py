"""Retained real grading failure + controlled repair, through production HTTP."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REAL = ROOT / 'docs/evidence/2026-10-21-continuous-learning-real'


def main():
    directory = Path(tempfile.mkdtemp(prefix='review-today-initial-preview-replay-', dir='/tmp')).resolve()
    tempfile.tempdir = str(directory)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/'checkpoint.sqlite3'), REVIEW_TODAY_JEV_TEST='0',
        REVIEW_TODAY_LLM_PROVIDER='openai_compatible', OPENAI_API_KEY='', DEEPSEEK_API_KEY='', DEEPSEEK_WEB_API_KEY='',
        TYPESAFE_API_KEY='', EXA_API_KEY='', TAVILY_API_KEY='', BRAVE_API_KEY='',
        REVIEW_TODAY_SEARCH_PROVIDER='none', REVIEW_TODAY_READ_PROVIDER='local',
        REVIEW_TODAY_SEARCH_FALLBACKS='', REVIEW_TODAY_READ_FALLBACKS='', REVIEW_TODAY_CONTEXT_PROVIDER='none',
        REVIEW_TODAY_TAVILY_KEYLESS='0', REVIEW_TODAY_BROWSER_FALLBACK='0')
    def audit(event, args):
        if event == 'socket.connect': raise AssertionError('No network during controlled replay')
        if event == 'sqlite3.connect' and args[0] != ':memory:':
            assert Path(str(args[0]).removeprefix('file:').split('?', 1)[0]).resolve().is_relative_to(directory)
    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT/'agent-service'))
    from tests import test_conversation_v2 as fixtures
    from tests.test_initial_capture_preview_repair import recorded_evaluation
    from agent_service import main as api
    from agent_service.schemas import IntentDecision, MasteryEvaluation
    from fastapi.testclient import TestClient

    original = json.loads((REAL/'partial-complete.json').read_text())
    failure = json.loads((REAL/'complete-answer-final.json').read_text())
    evaluation, payload = recorded_evaluation()
    decision = list(failure['runs'].values())[-1]['intent']
    query = failure['messages'][-2]['content']
    quotes = evaluation['capture_quotes']
    preview = dict(points=[
        dict(text='生成可能混入无依据内容，或遗漏资料中的限制。', evidence_quotes=[quotes[0]]),
        dict(text='核对来源的发布者、时间，以及版本、地区和适用前提。', evidence_quotes=[quotes[1]])],
        summary=dict(text='相关和带引用仍不保证正确，答案还需核对来源与适用条件。',
                     evidence_quotes=evaluation['capture_feedback_quotes']))
    results = []
    for label in ('controlled_grounded_repair', 'second_missing_stops', 'second_bad_source_stops',
                  'second_drops_sources_stops'):
        f = fixtures.ConversationTests(); f.setUp(); f.sid = original['session_id']
        try:
            with f.store.transaction(f.sid) as data: data.update(copy.deepcopy(original))
            f.decision = IntentDecision.model_validate(decision)
            before = copy.deepcopy(f.state()); cursor = f.store.last_seq(before)
            base = f.model; calls = []; observed = []
            def model(system, user, schema, **kwargs):
                if schema is not MasteryEvaluation: return base(system, user, schema, **kwargs)
                calls.append(dict(system=system, input=json.loads(user)))
                output = copy.deepcopy(evaluation)
                if len(calls) == 2 and label != 'second_missing_stops':
                    output['capture_preview'] = copy.deepcopy(preview)
                    if label == 'second_bad_source_stops':
                        output['capture_preview']['points'][0]['evidence_quotes'] = [payload['reference'][:12]]
                    if label == 'second_drops_sources_stops':
                        output['capture_quotes'] = []
                return MasteryEvaluation.model_validate(output)
            original_validate = MasteryEvaluation.validate_request
            def validate(output, incoming):
                try: return original_validate(output, incoming)
                except Exception as error:
                    observed.append(dict(code=getattr(error, 'code', ''), diagnostic=getattr(error, 'diagnostic', '')))
                    raise
            with patch('agent_service.conversation.parse_model', side_effect=model), \
                    patch.object(MasteryEvaluation, 'validate_request', validate), \
                    patch.object(api, 'conversation_harness', f.harness), \
                    patch.object(f.harness, 'start', side_effect=f.harness.drain):
                client = TestClient(api.app)  # No lifespan/startup/probes.
                accepted = client.post(f'/v2/sessions/{f.sid}/messages', json=dict(
                    client_message_id=str(uuid.uuid4()), content=query, mode_preset=original['mode']))
                assert accepted.status_code == 200, accepted.text
                page = client.get(f'/v2/sessions/{f.sid}/events', params=dict(after_seq=cursor))
                assert page.status_code == 200, page.text
                events = page.json()
            after = f.state(); run = after['runs'][accepted.json()['run_id']]
            assert len(calls) == 2
            assert len(f.calls) == 1 and f.calls[0][0] is IntentDecision
            assert 'initial_capture_preview_missing' in calls[1]['system']
            assert calls[0]['input'] == calls[1]['input']
            for key in ('reference', 'check_binding', 'capture_concepts', 'answer'):
                assert calls[0]['input'][key] == payload[key], key
            assert after['messages'][:len(before['messages'])] == before['messages']
            assert after['draft'] is None and after['pending'] is None
            f.capture.assert_not_called()
            if label == 'controlled_grounded_repair':
                assert run['status'] == 'completed'
                assert len(after['capture_offers']) == 1
                offer = next(iter(after['capture_offers'].values()))
                published = [e['payload']['capture_offer'] for e in events['events']
                             if e.get('payload', {}).get('capture_offer')]
                assert len(published) == 1
                assert offer['version'] == 1 and offer['status'] == 'offered'
                assert published[0]['preview_points'] == [p['text'] for p in preview['points']]
                assert published[0]['preview_summary'] == preview['summary']['text']
                assert published[0]['version'] == 1 and published[0]['id'] == offer['id']
                assert offer['anchor_message_id'] == after['messages'][-1]['message_id']
                assert after['messages'][-1]['content'] == failure['messages'][-1]['content']
                assert len(observed) == 1
                details = dict(title=published[0]['title'], points=published[0]['preview_points'],
                               summary=published[0]['preview_summary'], version=1, anchored_to_feedback=True)
            else:
                assert run['status'] == 'retryable_failed' and run['error_code'] == 'RT.MODEL.SCHEMA'
                assert not after.get('capture_offers')
                assert not any(e.get('payload', {}).get('capture_offer') for e in events['events'])
                assert len(observed) == 2
                details = dict(no_invitation=True, error_code=run['error_code'])
            (OUT/(label+'-events.json')).write_text(json.dumps(events, ensure_ascii=False, indent=2)+'\n')
            results.append(dict(case=label, outcome='PASS', http_post=200, http_events=200,
                run_status=run['status'], controlled_intent_calls=1, controlled_evaluation_calls=2,
                repair_diagnostics=observed, real_model_requests=0, real_web_operations=0,
                old_history_unchanged=True, saved_cards=0, **details))
        finally: f.tearDown()
    (OUT/'replay-result.json').write_text(json.dumps(dict(outcome='PASS', results=results,
        actual_model_requests=0, actual_provider_web_operations=0,
        limitation='Repair and intent outputs are controlled; no new real model, native input, save, UI or App restart.'),
        ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
