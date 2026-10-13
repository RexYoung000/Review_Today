"""Isolated composed retry paths; actual harness/client logic, mocked SDK I/O."""
from contextlib import contextmanager
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from tests.test_conversation_v2 import ConversationTests, intent
from agent_service import run_accounting as accounting
from agent_service.openai_client import parse_model
from agent_service.schemas import IntentDecision


@contextmanager
def fixture():
    f = ConversationTests()
    f.setUp()
    try:
        with patch.object(f.harness, 'start'), patch.object(f.harness, '_schedule_summary'), \
             patch('agent_service.conversation.require_model'):
            ack = f.send('原问题', drain=False)
            with f.store.transaction(f.sid) as data:
                run = data['runs'][ack.run_id]
                run['status'] = 'running'
                accounting.begin(run)
            yield f, ack.run_id
    finally:
        f.tearDown()


def call(f, rid):
    with patch('agent_service.conversation.parse_model', side_effect=parse_model):
        return f.harness._call(f.sid, rid, 1, 'intent', '按结构返回',
                              json.dumps({'current_inputs': ['当前答案'],
                                          'task': {'context': {'check_question': '受控检查题'}}}), IntentDecision)


def error_of(fn):
    try:
        fn()
    except RuntimeError as exc:
        return getattr(exc, 'code', str(exc))
    raise AssertionError('expected a bounded failure')


def compatible_client(parsed):
    client = Mock()
    client.responses.parse.return_value = NS(output_parsed=None, output=[], usage=None)
    client.chat.completions.parse.return_value = NS(
        choices=[NS(message=NS(parsed=parsed, refusal=None))], usage=None)
    return client


def deepseek_response(raw):
    return NS(output=[NS(content=[NS(type='output_text', text=raw)])], usage=None)


def main():
    rows = []
    with fixture() as (f, rid):
        client = compatible_client(intent('answer', answer_evidence='旧答案'))
        with patch('agent_service.openai_client.PROVIDER', 'openai_compatible'), \
             patch('agent_service.openai_client._client', return_value=client):
            error = error_of(lambda: call(f, rid))
        run = f.state()['runs'][rid]
        assert error == 'RT.MODEL.SCHEMA'
        assert client.responses.parse.call_count == client.chat.completions.parse.call_count == 1
        assert run['execution_budget']['attempts'] == 2
        assert len(run['model_calls']) == 1 and run['model_calls'][0]['transport_requests'] == 2
        rows.append(dict(case='endpoint_fallback_then_schema_failure', passed=True,
                         requests=2, logical_steps=1, error=error, third_request=False))

    for run_limit, expected in [(12, None), (1, 'RT.RUN.BUDGET_CALLS')]:
        with fixture() as (f, rid):
            client = Mock()
            valid = intent('greeting').model_dump_json()
            client.responses.create.side_effect = [deepseek_response('{}'), deepseek_response(valid)]
            with patch('agent_service.openai_client.PROVIDER', 'deepseek'), \
                 patch('agent_service.openai_client._client', return_value=client), \
                 patch('agent_service.run_accounting.MODEL_ATTEMPTS', run_limit):
                if expected:
                    error = error_of(lambda: call(f, rid))
                    assert error == expected
                else:
                    assert call(f, rid).intents == ['greeting']
                    error = None
            run = f.state()['runs'][rid]
            assert client.responses.create.call_count == (1 if expected else 2)
            assert run['execution_budget']['attempts'] == (1 if expected else 2)
            rows.append(dict(case='deepseek_schema_repair' if not expected else 'whole_run_blocks_repair',
                             passed=True, requests=client.responses.create.call_count, error=error,
                             budget_limit=run_limit))

    with fixture() as (f, rid):
        old_call = accounting.reserve(f.harness, f.sid, rid, 1,
                                      node='probe_previous_step', model='mock', estimated_input=10)
        accounting.request(f.harness, f.sid, rid, 1, old_call)
        with f.store.transaction(f.sid) as data:
            data['runs'][rid]['execution_budget']['attempts'] = accounting.MODEL_ATTEMPTS
        before = f.state()['runs'][rid]['execution_budget']
        accepted = f.send('运行中补充', drain=False)
        assert accepted.run_id == rid
        after = f.state()['runs'][rid]['execution_budget']
        assert after == before
        sent = Mock()
        with patch('agent_service.conversation.parse_model', side_effect=sent):
            f.harness.drain(f.sid)
        sent.assert_not_called()
        exhausted = f.state()['runs'][rid]
        assert exhausted['error_code'] == 'RT.RUN.BUDGET_CALLS'
        assert exhausted['status'] == 'retryable_failed' and f.state()['paused']
        ledger = exhausted['model_calls']
        f.control(rid, 'retry')
        assert 'execution_budget' not in f.state()['runs'][rid]
        assert f.state()['runs'][rid]['model_calls'] == ledger
        f.harness.drain(f.sid)
        retried = f.state()['runs'][rid]
        assert retried['status'] == 'completed'
        assert retried['execution_budget']['id'] != before['id']
        assert retried['model_calls'][0]['id'] == old_call
        rows.append(dict(case='steer_preserves_budget_explicit_retry_starts_new_segment', passed=True,
                         same_run=True, preserved_attempts=after['attempts'], preserved_deadline=True,
                         preloaded_exhausted_budget=True,
                         automatic_requests_after_limit=sent.call_count, old_ledger_retained=True))

    print(json.dumps(dict(cases=rows, real_model_calls=0, daily_data_writes=0,
                          note='Mocked SDK responses and isolated temporary SQLite; no production edits.'),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
