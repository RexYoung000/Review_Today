"""Zero-request reproduction from the unchanged real router output and data."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def main():
    setup = json.loads((OUT/'setup.json').read_text())
    directory = Path(setup['directory'])
    before = hashlib.sha256((directory/'quota.json').read_bytes()).hexdigest()
    sandbox = Path(tempfile.mkdtemp(prefix='review-today-status-diagnosis-',dir='/tmp')).resolve()
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(sandbox/'checkpoint.sqlite3'),REVIEW_TODAY_JEV_TEST='0')
    def audit(event, values):
        if event=='socket.connect': raise AssertionError('No network during diagnosis')
        if event=='sqlite3.connect': assert Path(values[0]).resolve().is_relative_to(sandbox)
    sys.addaudithook(audit)
    sys.path.insert(0,str(ROOT/'agent-service'))
    from agent_service import knowledge_capture_status as status
    data = json.loads((OUT/'after-status-query.json').read_text())
    rows = [json.loads(line) for line in (directory/'live-events.jsonl').read_text().splitlines()]
    decision = [r['output'] for r in rows if r['type']=='semantic_output' and r['schema']=='IntentDecision'][-1]
    context = decision['status_context']
    state = status.facts(data,status_context=context)
    reply = status.reply(state,context)
    assert reply==data['messages'][-1]['content'] and state['stage']=='scope_unconfirmed'
    offer = next(iter(data['capture_offers'].values()))
    receipt = status._task_receipt(data,data['tasks'][offer['save_task_id']])
    assert len(receipt)==5 and set(receipt)==set(offer['knowledge_ids'])
    focus = [dict(**item,covered_by_saved_offer=status._offer_covers_focus(offer,item)) for item in context['focus']]
    # Diagnostic contrast only: omit semantic focus on an in-memory copy.
    # This is not a proposed blanket fallback or a replacement production result.
    no_focus = status.facts(data)
    assert no_focus['stage']=='saved' and len(no_focus['current_knowledge_ids'])==5
    assert before==hashlib.sha256((directory/'quota.json').read_bytes()).hexdigest()
    result=dict(outcome='REAL_QUERY_FAILURE_REPRODUCED_OFFLINE',actual_router_status_query=True,
        real_focus=focus,actual_stage=state['stage'],actual_reply=reply,
        receipt_count=5,offer_status=offer['status'],offer_version=offer['version'],
        offer_receipt_ids_match=True,matched_task_mode=data['tasks'][offer['save_task_id']]['mode'],
        no_semantic_focus_diagnostic_stage=no_focus['stage'],no_semantic_focus_diagnostic_count=5,
        diagnosis='Semantic focus selects a recap heading outside frozen excerpts; coverage guard replaces matched save result with mixed-scope uncertainty.',
        no_additional_requests=True,quota_unchanged=True,production_modified=False,
        recommendation='Bind explicit this-save queries to an eligible program-owned save operation and durable receipt; retain excerpt coverage for questions about all discussed knowledge. Do not relax quote checks globally.')
    (OUT/'status-diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
