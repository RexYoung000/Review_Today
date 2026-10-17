"""Replay actual HTTP outputs; compare old/new state and stop before RAG/save.

No SDK, network, actual model judgment, knowledge generation or native write.
Only independent scratch stores are imported/opened; actual QA files stay closed.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from unittest.mock import patch
import uuid

from baseline_tests import baseline_respond

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'docs/evidence/2026-10-17-separate-topic-real'


def read(path):
    return json.loads(Path(path).read_text())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BoundaryReached(BaseException):
    pass


def main():
    setup = read(OUT / 'setup.json')
    before = read(ROOT / setup['source_checkpoint'])
    actual_after = read(ROOT / setup['actual_after_checkpoint'])
    original_run = list(actual_after['runs'].values())[-1]
    frozen_intent = next(v for v in original_run['steps'].values() if 'intents' in v)
    frozen_prep = next(v for v in original_run['steps'].values() if 'public_query' in v)
    frozen_reply = next(v for v in original_run['steps'].values() if 'message' in v)
    sid, tid = before['session_id'], before['active_task_id']
    offer = next(iter(before['capture_offers'].values()))
    assert offer['version'] == 3 and offer['trigger'] == 'verified_check'
    directory = Path(tempfile.mkdtemp(prefix='review-today-source-repair-replay-', dir='/tmp')).resolve()
    for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'TYPESAFE_API_KEY', 'EXA_API_KEY', 'TAVILY_API_KEY', 'BRAVE_API_KEY'):
        os.environ[name] = ''
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / 'default.sqlite3'), REVIEW_TODAY_JEV_TEST='0',
        REVIEW_TODAY_LLM_PROVIDER='openai_compatible', REVIEW_TODAY_SEARCH_PROVIDER='none',
        REVIEW_TODAY_CONTEXT_PROVIDER='none', REVIEW_TODAY_BROWSER_FALLBACK='0')
    sys.path.insert(0, str(ROOT / 'agent-service'))
    counts = dict(network=0, sdk_client=0, request_identity=0, outside_sqlite=0, unexpected_model=0)
    sqlite_open = sqlite3.connect

    def forbidden(name):
        def stop(*args, **kwargs):
            counts[name] += 1
            raise AssertionError('Replay forbids ' + name)
        return stop

    def isolated_sqlite(database, *args, **kwargs):
        if not Path(database).resolve().is_relative_to(directory):
            counts['outside_sqlite'] += 1
            raise AssertionError('Database outside isolated replay directory')
        return sqlite_open(database, *args, **kwargs)

    results = []
    with ExitStack() as guards:
        guards.enter_context(patch('sqlite3.connect', side_effect=isolated_sqlite))
        guards.enter_context(patch('socket.socket.connect', side_effect=forbidden('network')))
        guards.enter_context(patch('socket.socket.connect_ex', side_effect=forbidden('network')))
        guards.enter_context(patch('socket.create_connection', side_effect=forbidden('network')))
        from agent_service import conversation
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.openai_client import ModelCallError
        from agent_service.schemas import ConversationOutput, IntentDecision, SessionMessageRequest, TeachingPreparation
        guards.enter_context(patch('agent_service.openai_client._client', side_effect=forbidden('sdk_client')))
        guards.enter_context(patch('agent_service.openai_client._request_identity', side_effect=forbidden('request_identity')))

        def clone(checkpoint, label):
            store = ConversationStore(HarnessStore(str(directory / (label + '.sqlite3'))))
            with store.transaction(sid) as data:
                data.update(deepcopy(checkpoint))
            for key, task in checkpoint['tasks'].items():
                assert {k: v for k, v in store.get(sid)['tasks'][key].items() if k != 'updated_at'} == {
                    k: v for k, v in task.items() if k != 'updated_at'}
            return store, ConversationHarness(store)

        corrected = ConversationHarness._respond
        legacy = baseline_respond(conversation.__dict__)
        for case, respond in (('legacy', legacy), ('fixed', corrected), ('fixed_format_repair', corrected)):
            store, harness = clone(before, case)
            restored = store.get(sid)
            phase = 'independent'
            observations = dict(case=case, fixture_schemas=[], answer_attempts=0)

            def parser(system, user, schema, **kwargs):
                observations['fixture_schemas'].append(dict(phase=phase, schema=schema.__name__))
                if phase == 'independent':
                    if schema is IntentDecision:
                        return schema.model_validate(deepcopy(frozen_intent))
                    if schema is TeachingPreparation:
                        return schema.model_validate(deepcopy(frozen_prep))
                    if schema is ConversationOutput:
                        observations['answer_attempts'] += 1
                        if case == 'fixed_format_repair' and observations['answer_attempts'] == 1:
                            raise ModelCallError('SCHEMA', 'json_invalid/non_json')
                        return schema.model_validate(deepcopy(frozen_reply))
                elif phase == 'return':
                    if schema is IntentDecision:
                        return IntentDecision(intents=['followup'], relation='continuation', scope='continue_goal',
                            target_task_id=tid, answer_only=True, rationale='受控夹具：明确回到原 RAG，解释而不推进')
                    if schema is TeachingPreparation:
                        return TeachingPreparation(concepts=[], public_query='')
                    if schema is ConversationOutput:
                        observations['return_input'] = json.loads(user)
                        raise BoundaryReached()
                counts['unexpected_model'] += 1
                raise AssertionError('Unexpected semantic node')

            def call_summaries(run):
                calls = [{k: c[k] for k in ('node', 'status', 'transport_requests', 'request_ids', 'usage')}
                         for c in run.get('model_calls', [])]
                assert all(c['transport_requests'] == 0 and c['request_ids'] == [] and c['usage'] == [] for c in calls)
                return calls

            with patch.object(ConversationHarness, '_respond', respond), \
                    patch('agent_service.conversation.parse_model', side_effect=parser), \
                    patch('agent_service.conversation.run_capture', side_effect=AssertionError('No capture during answers')):
                accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                    content=(PRIOR / 'input.txt').read_text().strip(), mode_preset=before['mode']))
                harness.drain(sid)
                after_http = store.get(sid)
                run = after_http['runs'][accepted.run_id]
                assert run['status'] == 'completed'
                assert after_http['messages'][-1]['content'] == frozen_reply['message']
                assert after_http['messages'][:len(before['messages'])] == before['messages']
                assert all(after_http['runs'][k] == v for k, v in before['runs'].items())
                assert after_http['capture_offers'] == before['capture_offers']
                assert after_http['draft'] == before['draft'] and after_http['pending'] == before['pending']
                assert after_http['active_task_id'] == tid and len(after_http['tasks']) == 1
                assert after_http['tasks'][tid]['context']['learning_plan'] == before['tasks'][tid]['context']['learning_plan']
                observations.update(independent_calls=call_summaries(run),
                    original_task_unchanged=after_http['tasks'] == restored['tasks'],
                    task_source_count=len(after_http['tasks'][tid]['context']['sources']),
                    original_invitation_unchanged=True, old_messages_and_runs_unchanged=True,
                    independent_answer_source_count=len(run['answer_sources']), reply=after_http['messages'][-1]['content'])
                assert observations['independent_answer_source_count'] == 0
                if case != 'legacy':
                    assert observations['original_task_unchanged'] and observations['task_source_count'] == 1
                else:
                    assert not observations['original_task_unchanged'] and observations['task_source_count'] == 0
                phase = 'return'
                returned = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                    content='回到刚才的 RAG：高相似度是否能证明资料可信？请结合原讲义中的过时接口例子解释；只解释，不推进。',
                    mode_preset=before['mode']))
                try:
                    harness.drain(sid)
                except BoundaryReached:
                    pass
                assert 'return_input' in observations
                payload = observations['return_input']
                lesson = payload['context']['task']['context']['last_lesson']
                observations.update(return_source_count=len(payload['sources']),
                    last_lesson_preserved=lesson == before['tasks'][tid]['context']['last_lesson'],
                    return_calls=call_summaries(store.get(sid)['runs'][returned.run_id]))
                assert observations['return_source_count'] == (0 if case == 'legacy' else 1)
                assert observations['last_lesson_preserved']
                if case != 'legacy':
                    assert payload['sources'] == before['tasks'][tid]['context']['sources']

            # Saving uses a separate copy before the unfinished return probe.
            save_store, save_harness = clone(after_http, case + '-save')
            phase = 'save'

            def capture_boundary(commit_id, content, language, **kwargs):
                current = save_store.get(sid)
                selected = current['capture_offers'][offer['id']]
                observations['save_input'] = dict(offer_id=selected['id'], version=selected['version'], content=content,
                    draft=deepcopy(current['draft']), sources=deepcopy(current['tasks'][commit_id]['context']['sources']))
                assert current['draft'] == offer['draft'] and content == offer['draft']['content']
                assert observations['save_input']['sources'] == offer['sources']
                assert not any(t.get('memory_package') for t in current['tasks'].values())
                raise BoundaryReached()

            with patch('agent_service.conversation.parse_model', side_effect=parser), \
                    patch('agent_service.conversation.run_capture', side_effect=capture_boundary):
                saved = save_harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                    content='capture_save', mode_preset=before['mode'],
                    operation=dict(kind='capture_save', target_id=offer['id'], version=offer['version'])))
                try:
                    save_harness.drain(sid)
                except BoundaryReached:
                    pass
            assert 'save_input' in observations
            observations['save_calls'] = call_summaries(save_store.get(sid)['runs'][saved.run_id])
            assert observations['save_calls'] == []
            write(case + '.json', observations)
            results.append({k: v for k, v in observations.items() if k not in {'return_input', 'save_input', 'reply'}})

    assert all(value == 0 for value in counts.values())
    assert all((ROOT / key).is_file() and digest(ROOT / key) == value for key, value in setup['protected_sha256'].items()
               if key not in setup['allowed_production_changes'])
    assert all(not Path(p).exists() for p in setup['daily_missing'])
    runtime = Path(setup['actual_runtime'])
    assert read(runtime / 'request-count.json')['actual_requests'] == 30
    write('replay-result.json', dict(outcome='PASS', directory=str(directory), cases=results,
        real_model_requests=0, original_actual_requests=30, original_stop_unchanged=True, guards=counts,
        original_after30_checkpoint_unchanged=True, protected_files_unchanged=len(setup['protected_sha256']) - 2,
        production_changes=setup['allowed_production_changes'],
        caveat='Historical HTTP route/preparation/final output frozen; return route is controlled; stop before new RAG answer or capture. No real quality or native save claim.'))
    print(json.dumps(dict(outcome='PASS', variants=len(results), flows=9, original_task_unchanged=[x['original_task_unchanged'] for x in results],
        return_sources=[x['return_source_count'] for x in results], actual_requests=0, guards=counts), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
