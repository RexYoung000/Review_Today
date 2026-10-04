"""Opt-in fixed legacy-history replay using one entry call per new status turn.

From agent-service:
  .venv/bin/python -m tests.knowledge_status_history_real_smoke --live --output /tmp/new.jsonl

All history is authored synthetic fixture data. Web and knowledge writes are
blocked; no private snapshot, daily database, or native persistence is used.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import uuid

from tests.knowledge_status_history_fixture import CLAIM_ID, QUERY, seed


def checks_for(record, *, first):
    from agent_service.knowledge_capture_status import validate_context
    before, after, run = record['before'], record['after'], record['run']
    intent = run.get('intent') or {}
    proposal = intent.get('status_context') or {}
    calls = record['model_calls']
    context = next((call.get('input', {}) for call in calls if call['schema'] == 'IntentDecision'), {})
    sources = {item['message_id']: item for item in context.get('knowledge_capture_status', {}).get('discussion_sources', [])}
    focus = proposal.get('focus', [])
    labels = [item['label'] for item in focus]
    prior = proposal.get('prior_claim') or {}
    reply = '\n'.join(record['replies'])
    return dict(
        one_entry_call=len(calls) == 1 and calls[0]['schema'] == 'IntentDecision',
        read_only_status=bool(intent.get('knowledge_card_status') and run.get('knowledge_status_reply')),
        references_exact=bool(focus) and all(item['message_id'] in sources
            and item['quote'] in sources[item['message_id']]['content'] for item in focus),
        selection_scope_preserved=bool(focus) and validate_context(
            context.get('knowledge_capture_status', {}), proposal)['focus_labels'] == list(dict.fromkeys(labels)),
        current_topics_named=all(any(topic in label for label in labels) and topic in reply
                                for topic in ('关键词', '向量')),
        no_earlier_unanswered_topic=not any('切块' in label for label in labels),
        prior_claim_selected=prior.get('message_id') == CLAIM_ID if first else not prior,
        correction_applied=(run.get('knowledge_status_correction_message_id') == CLAIM_ID
                            if first else run.get('knowledge_status_correction_message_id') is None),
        no_tasks_or_progress_changed=before['tasks'] == after['tasks'],
        no_capture_authorized=(not intent.get('proposed_actions')
            and before['capture_offers'] == after['capture_offers']
            and before['draft'] == after['draft'] and before['pending'] == after['pending']),
        old_history_unchanged=after['messages'][:len(before['messages'])] == before['messages'],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--turns', choices=(1, 2), type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('use a new evidence file; never overwrite an earlier result')
    with tempfile.TemporaryDirectory(prefix='review-today-status-history-') as folder:
        os.environ['REVIEW_TODAY_HARNESS_DB'] = str(Path(folder) / 'synthetic.sqlite3')
        os.environ['REVIEW_TODAY_JEV_TEST'] = '0'
        from agent_service.config import PROVIDER
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_prompts import INTENT_SYSTEM
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import IntentDecision, SessionMessageRequest
        from tests.case_library.recording import RunReport

        if PROVIDER != 'deepseek':
            raise RuntimeError('current expected DeepSeek provider is not active; configuration left unchanged')
        harness = ConversationHarness(ConversationStore(HarnessStore(os.environ['REVIEW_TODAY_HARNESS_DB'])))
        sid = seed(harness)
        planned = ['legacy_claim_status', 'repeat_status'][:args.turns]
        with RunReport(args.output, layer='live_fixed_context', planned=planned,
                fixture=dict(synthetic=True, jev=False, source='knowledge_status_history_fixture.py',
                    purpose='Historical false card claim, current retrieval concepts and mismatched old plan',
                    repeat_same_input=True,
                    daily_data_used=False, native_persistence_verified=False)) as report:
            report.write(dict(type='prompt', system=INTENT_SYSTEM, schema=IntentDecision.model_json_schema()))
            for index, identity in enumerate(planned):
                record = report.turn(harness, sid, SessionMessageRequest(
                    client_message_id=str(uuid.uuid4()), content=QUERY, mode_preset='source_learning'))
                checks = checks_for(record, first=index == 0)
                report.add(identity, record, checks)
                result = report.records[-1]
                print(json.dumps(dict(id=identity, checks=result['checks'],
                    automatic_result=result['automatic_result'], replies=record['replies'],
                    status_context=(record['run'].get('intent') or {}).get('status_context'),
                    elapsed_ms=record['run'].get('elapsed_ms'),
                    model_accounting=record['run'].get('model_calls')), ensure_ascii=False), flush=True)
                if result['automatic_result'] != 'PASS':
                    break  # Preserve the failure; do not pay for dependent turns.
        raise SystemExit(0 if report.passed else 1)


if __name__ == '__main__':
    main()
