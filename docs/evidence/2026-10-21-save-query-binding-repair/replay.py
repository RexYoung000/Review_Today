"""Real retained state + controlled new selection, through production HTTP/API."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent


def main():
    directory=Path(tempfile.mkdtemp(prefix='review-today-save-query-replay-',dir='/tmp')).resolve()
    tempfile.tempdir=str(directory)
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/'checkpoint.sqlite3'),REVIEW_TODAY_JEV_TEST='0',
        REVIEW_TODAY_LLM_PROVIDER='openai_compatible',OPENAI_API_KEY='',DEEPSEEK_API_KEY='',DEEPSEEK_WEB_API_KEY='',
        EXA_API_KEY='',TAVILY_API_KEY='',BRAVE_API_KEY='',REVIEW_TODAY_SEARCH_PROVIDER='none',REVIEW_TODAY_READ_PROVIDER='local')
    def audit(event,args):
        if event=='socket.connect':raise AssertionError('No network during controlled replay')
        if event=='sqlite3.connect' and args[0]!=':memory:':assert Path(args[0]).resolve().is_relative_to(directory)
    sys.addaudithook(audit)
    sys.path.insert(0,str(ROOT/'agent-service'))
    from tests.test_save_operation_status import recorded
    from tests import test_conversation_v2 as fixtures
    from agent_service import main as api
    from agent_service.schemas import IntentDecision
    from fastapi.testclient import TestClient
    original,query,old_decision,reference=recorded()
    results=[]
    for label in ('original_router_negative','controlled_save_operation'):
        fixture=fixtures.ConversationTests();fixture.setUp();fixture.sid=original['session_id']
        try:
            with fixture.store.transaction(fixture.sid) as data:data.update(copy.deepcopy(original))
            decision=copy.deepcopy(old_decision)
            if label=='controlled_save_operation':decision.update(knowledge_save_operation=reference,status_context=None)
            fixture.decision=IntentDecision.model_validate(decision)
            before=copy.deepcopy(fixture.state());cursor=fixture.store.last_seq(before)
            with patch.object(api,'conversation_harness',fixture.harness),patch.object(fixture.harness,'start',side_effect=fixture.harness.drain):
                client=TestClient(api.app)  # No startup/lifespan, no probes.
                accepted=client.post(f'/v2/sessions/{fixture.sid}/messages',json=dict(
                    client_message_id=str(uuid.uuid4()),content=query,mode_preset=original['mode']))
                assert accepted.status_code==200,accepted.text
                page=client.get(f'/v2/sessions/{fixture.sid}/events',params=dict(after_seq=cursor))
                assert page.status_code==200,page.text
                public=page.json()
            after=fixture.state();run=after['runs'][accepted.json()['run_id']]
            text=after['messages'][-1]['content']
            if label=='controlled_save_operation':
                assert '已成功写入 5 张知识卡' in text and '保存范围不完全一致' not in text
                for card in original['tasks'][reference['task_id']]['memory_package']['knowledge']:assert card['title'] in text
                assert run['knowledge_status_save_operation']['task_id']==reference['task_id']
                assert run['knowledge_status_save_operation']['version']==4
            else:assert '保存范围不完全一致' in text
            assert run['status']=='completed'
            for key in ('tasks','capture_offers','draft','pending','active_task_id','focus_goal'):assert after[key]==before[key],key
            assert after['messages'][:len(before['messages'])]==before['messages']
            assert [schema for schema,_ in fixture.calls]==[IntentDecision]
            fixture.capture.assert_not_called()
            assert any((event.get('message') or {}).get('content')==text for event in public['events'])
            (OUT/(label+'-public-events.json')).write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
            result=dict(case=label,outcome='EXPECTED_NEGATIVE' if label=='original_router_negative' else 'PASS',
                http_post_status=accepted.status_code,http_event_page_status=page.status_code,run_status=run['status'],
                reply=text,controlled_intent_calls=1,actual_model_requests=0,web_operations=0,
                tasks_offers_draft_progress_and_old_history_unchanged=True,
                selection_is_new_real_model_output=False)
            results.append(result)
        finally:fixture.tearDown()
    (OUT/'replay-result.json').write_text(json.dumps(dict(outcome='PASS',results=results,
        actual_model_requests=0,actual_provider_web_operations=0,
        limitation='New operation selection is controlled, not a new real model judgment. Native input/outbox/UI not rerun.'),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
