"""Actual requests retain one extensible usage fact, even without supplier IDs."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest

from tests import test_conversation_v2 as fixtures
from agent_service import run_accounting as accounting
from agent_service.checkpoint_delta import apply_changes, recovery_page
from agent_service.openai_client import parse_model
from agent_service.schemas import ConversationOutput


@pytest.fixture
def case():
    f = fixtures.ConversationTests()
    f.setUp()
    try:
        with patch.object(f.harness, 'start'), patch.object(f.harness, '_schedule_summary'):
            ack = f.send('受控请求', drain=False)
            with f.store.transaction(f.sid) as data:
                data['runs'][ack.run_id]['status'] = 'running'
            cid = accounting.reserve(f.harness, f.sid, ack.run_id, 1,
                                     node='test', model='mock', estimated_input=10)
            yield f, ack.run_id, cid
    finally:
        f.tearDown()


def admit(case):
    f, rid, cid = case
    return accounting.request(f.harness, f.sid, rid, 1, cid)


def report(case, row):
    f, rid, cid = case
    accounting.record(f.harness, f.sid, rid, cid, usage=row)


def call(case):
    f, rid, cid = case
    return next(row for row in f.state()['runs'][rid]['model_calls'] if row['id'] == cid)


def test_duplicate_anonymous_receipt_uses_admitted_request_identity(case):
    identity = admit(case)
    receipt = dict(response_id=None, input_tokens=100, output_tokens=20)
    report(case, receipt); report(case, deepcopy(receipt))
    saved = call(case)
    assert saved['request_ids'] == [identity]
    assert len(saved['usage']) == 1 and saved['usage'][0]['request_id'] == identity
    assert saved['usage_state'] == 'reported' and receipt.get('request_id') is None


def test_identified_receipt_later_enriches_missing_fields_without_erasing_known_values(case):
    identity = admit(case)
    report(case, dict(response_id='same', input_tokens=100, output_tokens=None))
    assert call(case)['usage_state'] == 'partial'
    report(case, dict(response_id='same', input_tokens=None, output_tokens=20, total_tokens=120,
                     cached_input_tokens=0))
    report(case, dict(response_id='same', input_tokens=100, output_tokens=None, total_tokens=None))
    saved = call(case)
    assert saved['usage'] == [dict(response_id='same', request_id=identity,
        input_tokens=100, output_tokens=20, total_tokens=120, cached_input_tokens=0)]
    assert saved['usage_state'] == 'reported'


@pytest.mark.parametrize('supplier_id', [None, 'supplier-reused-id'])
def test_two_real_requests_with_equal_counts_are_two_facts(case, supplier_id):
    first = admit(case)
    report(case, dict(request_id=first, response_id=supplier_id, input_tokens=100, output_tokens=20))
    assert call(case)['usage_state'] == 'reported'
    second = admit(case)
    assert first != second and call(case)['usage_state'] == 'partial'
    report(case, dict(request_id=second, response_id=supplier_id, input_tokens=100, output_tokens=20))
    report(case, dict(request_id=first, response_id=supplier_id, input_tokens=100, output_tokens=20))
    saved = call(case)
    assert len(saved['usage']) == 2 and saved['usage_state'] == 'reported'
    assert {row['request_id'] for row in saved['usage']} == {first, second}
    assert sum(row['input_tokens'] for row in saved['usage']) == 200


@pytest.mark.parametrize('row,state', [
    ({'input_tokens': None, 'output_tokens': None}, 'unavailable'),
    ({'input_tokens': 100, 'output_tokens': None}, 'partial'),
    ({'input_tokens': None, 'output_tokens': 20}, 'partial'),
    ({'input_tokens': 0, 'output_tokens': 0}, 'reported'),
])
def test_core_fields_keep_unknown_distinct_from_supplier_zero(case, row, state):
    admit(case); report(case, row)
    assert call(case)['usage_state'] == state
    assert all(call(case)['usage'][0][key] == value for key, value in row.items())


def test_optional_details_do_not_invent_values_or_hide_known_core_usage(case):
    admit(case)
    report(case, dict(input_tokens=100, output_tokens=20, total_tokens=None,
                     cached_input_tokens=None, reasoning_output_tokens=None))
    assert call(case)['usage_state'] == 'reported'
    assert call(case)['usage'][0]['total_tokens'] is None


def test_corrected_receipt_updates_one_request_instead_of_adding_a_second_charge(case):
    identity = admit(case)
    report(case, dict(request_id=identity, input_tokens=100, output_tokens=20))
    report(case, dict(request_id=identity, input_tokens=110, output_tokens=25))
    assert call(case)['usage'] == [dict(request_id=identity, input_tokens=110, output_tokens=25)]


def test_late_receipts_keep_their_own_request_when_delivery_order_changes(case):
    first, second = admit(case), admit(case)
    report(case, dict(request_id=second, input_tokens=20, output_tokens=2))
    report(case, dict(request_id=first, input_tokens=10, output_tokens=1))
    report(case, dict(request_id=first, input_tokens=None, output_tokens=None, cached_input_tokens=0))
    saved = {row['request_id']: row for row in call(case)['usage']}
    assert len(saved) == 2 and saved[first]['input_tokens'] == 10 and saved[second]['input_tokens'] == 20
    assert call(case)['usage_state'] == 'reported'


def test_anonymous_legacy_multiple_requests_are_not_guessed_or_collapsed(case):
    f, rid, cid = case
    legacy = [dict(input_tokens=10, output_tokens=2), dict(input_tokens=10, output_tokens=2)]
    with f.store.transaction(f.sid) as data:
        old = data['runs'][rid]['model_calls'][0]
        old.pop('request_ids'); old['transport_requests'] = 2; old['usage'] = deepcopy(legacy)
    report(case, dict(input_tokens=10, output_tokens=2))
    assert call(case)['usage'][:2] == legacy and len(call(case)['usage']) == 3
    assert call(case)['usage_state'] == 'partial'


def test_late_usage_after_stop_and_ack_remains_in_checkpoint_without_new_reply(case):
    f, rid, cid = case
    identity = admit(case)
    before = f.state(); projection = recovery_page(before, 0)['checkpoint']
    version = before['recovery_version']
    f.control(rid, 'stop')
    report(case, dict(request_id=identity, input_tokens=10, output_tokens=2))
    with f.store.transaction(f.sid) as data:
        data['last_acked_seq'] = f.store.last_seq(data)
        f.store.compact_acknowledged(data)
    current = f.state()
    for delta in recovery_page(current, version)['deltas']:
        projection = apply_changes(projection, delta['changes'])
    assert current['runs'][rid]['status'] == 'interrupted' and current['messages'] == before['messages']
    assert projection['runs'][rid]['model_calls'] == current['runs'][rid]['model_calls']
    assert call(case)['usage'][0]['request_id'] == identity


@pytest.mark.parametrize('response_id,enrich', [(None, False), ('supplier-id', True)])
def test_actual_stream_repeated_completions_deduplicate_and_enrich(case, response_id, enrich):
    f, rid, cid = case
    text = ConversationOutput(message='受控完整回答').model_dump_json()
    partial = {'input_tokens': 100} if enrich else {'input_tokens': 100, 'output_tokens': 20}
    counts = [partial, {'input_tokens': 100, 'output_tokens': 20}]
    events = [NS(type='response.created', response=NS(id=response_id)),
              NS(type='response.output_text.delta', delta=text)]
    for usage in counts:
        response = NS(id=response_id, status='completed', usage=NS(**usage),
                      output=[NS(content=[NS(type='output_text', text=text)])])
        events.append(NS(type='response.completed', response=response))
    client = MagicMock()
    client.responses.create.return_value.__enter__.return_value = iter(events)
    with patch('agent_service.openai_client.PROVIDER', 'deepseek'), \
         patch('agent_service.openai_client._client', return_value=client):
        parsed = parse_model('rules', 'user', ConversationOutput, on_partial=lambda _: None,
            on_request=lambda: admit(case), on_usage=lambda usage: report(case, usage))
    assert parsed.message == '受控完整回答' and client.responses.create.call_count == 1
    saved = call(case)
    assert len(saved['usage']) == 1 and saved['usage'][0]['output_tokens'] == 20
    assert saved['usage_state'] == 'reported' and saved['usage'][0]['request_id'] == saved['request_ids'][0]


def test_actual_compatible_endpoints_keep_equal_anonymous_usage_separate(case):
    client = MagicMock(); usage = dict(input_tokens=100, output_tokens=20)
    client.responses.parse.return_value = NS(id=None, usage=NS(**usage), output=[], output_parsed=None)
    client.chat.completions.parse.return_value = NS(id=None, usage=NS(**usage),
        choices=[NS(message=NS(parsed=ConversationOutput(message='兼容回答'), refusal=None))])
    with patch('agent_service.openai_client.PROVIDER', 'openai_compatible'), \
         patch('agent_service.openai_client._client', return_value=client):
        parsed = parse_model('rules', 'user', ConversationOutput,
            on_request=lambda: admit(case), on_usage=lambda usage: report(case, usage))
    assert parsed.message == '兼容回答'
    saved = call(case)
    assert saved['transport_requests'] == len(saved['request_ids']) == len(saved['usage']) == 2
    assert saved['usage_state'] == 'reported' and sum(row['input_tokens'] for row in saved['usage']) == 200
