"""Inspect actual model-client/ledger paths with isolated SQLite and fake SSE."""
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from tests.test_conversation_v2 import ConversationTests
from agent_service import run_accounting as accounting
from agent_service.checkpoint_delta import apply_changes, recovery_page
from agent_service.openai_client import _report_usage, parse_model
from agent_service.schemas import ConversationOutput


@contextmanager
def fixture():
    f = ConversationTests()
    f.setUp()
    try:
        with patch.object(f.harness, 'start'), patch.object(f.harness, '_schedule_summary'), \
             patch('agent_service.conversation.require_model'):
            ack = f.send('合成用量检查', drain=False)
            with f.store.transaction(f.sid) as data:
                run = data['runs'][ack.run_id]
                run['status'] = 'running'
                accounting.begin(run)
            yield f, ack.run_id
    finally:
        f.tearDown()


def normalized(response_id, **fields):
    rows = []
    _report_usage(NS(id=response_id, usage=NS(**fields)), rows.append)
    return rows[0]


def ledger_case(callbacks, *, requests=1, after_stop=False):
    with fixture() as (f, rid):
        cid = accounting.reserve(f.harness, f.sid, rid, 1,
                                 node='inspection', model='mock', estimated_input=9999)
        for _ in range(requests):
            accounting.request(f.harness, f.sid, rid, 1, cid)
        before = f.state()
        projection = recovery_page(before, 0)['checkpoint']
        version = before['recovery_version']
        if after_stop:
            f.control(rid, 'stop')
        for row in callbacks:
            accounting.record(f.harness, f.sid, rid, cid, usage=row)
        with f.store.transaction(f.sid) as data:
            data['last_acked_seq'] = f.store.last_seq(data)
            f.store.compact_acknowledged(data)
        current = f.state()
        recovery = recovery_page(current, version)
        assert 'deltas' in recovery
        for delta in recovery['deltas']:
            projection = apply_changes(projection, delta['changes'])
        call = current['runs'][rid]['model_calls'][0]
        assert projection['runs'][rid]['model_calls'][0] == call
        assert recovery_page(current, 0)['checkpoint']['runs'][rid]['model_calls'][0] == call
        return dict(call=call, run_status=current['runs'][rid]['status'],
                    delta_and_ack_preserve_record=True,
                    visible_messages_changed=current['messages'] != before['messages'])


def stream_case(response_id, counts):
    with fixture() as (f, rid):
        text = ConversationOutput(message='合成完整回答').model_dump_json()
        client = MagicMock()
        events = [NS(type='response.created', response=NS(id=response_id)),
                  NS(type='response.output_text.delta', delta=text)]
        for usage in counts:
            response = NS(id=response_id, status='completed', usage=NS(**usage),
                          output=[NS(content=[NS(type='output_text', text=text)])])
            events.append(NS(type='response.completed', response=response))
        client.responses.create.return_value.__enter__.return_value = iter(events)
        with patch('agent_service.openai_client.PROVIDER', 'deepseek'), \
             patch('agent_service.openai_client._client', return_value=client), \
             patch('agent_service.conversation.parse_model', side_effect=parse_model):
            answer = f.harness._call(f.sid, rid, 1, 'answer', '合成规则', '{}', ConversationOutput)
        assert answer.message == '合成完整回答'
        call = f.state()['runs'][rid]['model_calls'][0]
        assert client.responses.create.call_count == 1 and call['transport_requests'] == 1
        return dict(call=call, sdk_requests=1, validated_answer=True)


def compatible_double_case():
    with fixture() as (f, rid):
        client = MagicMock()
        usage = dict(input_tokens=100, output_tokens=20, total_tokens=120)
        client.responses.parse.return_value = NS(id=None, usage=NS(**usage), output=[], output_parsed=None)
        client.chat.completions.parse.return_value = NS(id=None, usage=NS(**usage),
            choices=[NS(message=NS(parsed=ConversationOutput(message='合成兼容回答'), refusal=None))])
        with patch('agent_service.openai_client.PROVIDER', 'openai_compatible'), \
             patch('agent_service.openai_client._client', return_value=client), \
             patch('agent_service.conversation.parse_model', side_effect=parse_model):
            answer = f.harness._call(f.sid, rid, 1, 'inspection', '合成规则', '{}', ConversationOutput)
        assert answer.message == '合成兼容回答'
        call = f.state()['runs'][rid]['model_calls'][0]
        assert client.responses.parse.call_count == client.chat.completions.parse.call_count == 1
        assert call['transport_requests'] == len(call['usage']) == 2
        return dict(call=call, sdk_requests=2, validated_answer=True)


def main(expect_fixed=False):
    rows = []
    full = normalized('same-response', input_tokens=100, output_tokens=20, total_tokens=120)
    partial = normalized('same-response', input_tokens=100)
    zero = normalized('zero', input_tokens=0, output_tokens=0, total_tokens=0)
    absent = ledger_case([])
    assert absent['call']['usage_state'] == 'unavailable' and not absent['call']['usage']
    rows.append(dict(case='missing_usage_is_not_estimated_or_zero', expected_boundary=True, **absent))

    complete = ledger_case([full, deepcopy(full)])
    assert len(complete['call']['usage']) == 1
    rows.append(dict(case='same_response_identical_receipt_is_deduplicated', expected_boundary=True, **complete))

    zeros = ledger_case([zero])
    assert zeros['call']['usage'][0]['input_tokens'] == 0 and zeros['call']['usage_state'] == 'reported'
    rows.append(dict(case='supplier_reported_zero_is_known', expected_boundary=True, **zeros))

    missing_field = ledger_case([partial])
    assert missing_field['call']['usage_state'] == ('partial' if expect_fixed else 'reported')
    assert missing_field['call']['usage'][0]['output_tokens'] is None
    rows.append(dict(case='partial_core_fields_marked_reported',
                     defect_reproduced=not expect_fixed, repair_verified=expect_fixed, **missing_field))

    enriched = ledger_case([partial, full])
    assert len(enriched['call']['usage']) == 1
    assert enriched['call']['usage'][0]['output_tokens'] == (20 if expect_fixed else None)
    rows.append(dict(case='same_response_later_fields_discarded',
                     defect_reproduced=not expect_fixed, repair_verified=expect_fixed, **enriched))

    fallback = ledger_case([full], requests=2)
    assert fallback['call']['usage_state'] == 'partial'
    rows.append(dict(case='two_requests_one_report_is_partial', expected_boundary=True, **fallback))

    stopped = ledger_case([full], after_stop=True)
    assert stopped['run_status'] == 'interrupted' and not stopped['visible_messages_changed']
    rows.append(dict(case='late_usage_after_stop_does_not_revive_reply', expected_boundary=True, **stopped))

    duplicated = stream_case(None, [dict(input_tokens=100, output_tokens=20, total_tokens=120)] * 2)
    assert len(duplicated['call']['usage']) == (1 if expect_fixed else 2)
    assert sum(row['input_tokens'] for row in duplicated['call']['usage']) == (100 if expect_fixed else 200)
    rows.append(dict(case='missing_response_id_duplicate_completed_receipt',
                     defect_reproduced=not expect_fixed, repair_verified=expect_fixed, **duplicated))

    supplemented = stream_case('stream-response', [dict(input_tokens=100),
                                                  dict(input_tokens=100, output_tokens=20, total_tokens=120)])
    assert len(supplemented['call']['usage']) == 1
    assert supplemented['call']['usage'][0]['output_tokens'] == (20 if expect_fixed else None)
    rows.append(dict(case='actual_stream_later_usage_fields_discarded',
                     defect_reproduced=not expect_fixed, repair_verified=expect_fixed, **supplemented))

    distinct = compatible_double_case()
    rows.append(dict(case='two_distinct_anonymous_requests_with_equal_counts', expected_boundary=True, **distinct))

    print(json.dumps(dict(cases=rows, real_supplier_calls=0, daily_data_writes=0,
                          mode='fixed' if expect_fixed else 'baseline',
                          note='Controlled SDK receipts, not supplier incident or billed-total claims.'),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import sys
    main(expect_fixed='--expect-fixed' in sys.argv)
