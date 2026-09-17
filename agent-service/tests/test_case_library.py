"""Test the evaluator's failures too: a green result must have real coverage."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from tests.case_library.schema import (
    ROOT, Catalog, Check, Scenario, digest, load, select, validate,
)
from tests.case_library.replay import evaluate, identity, run_one, seed
from tests.case_library.recording import RunReport
from tests.case_library.results import read_report
from tests import test_conversation_v2 as fixtures


@pytest.fixture
def suite():
    return load()


@pytest.fixture
def controlled():
    f = fixtures.ConversationTests()
    f.setUp()
    try:
        yield f
    finally:
        f.tearDown()


def test_catalog_test_references_and_doc_inventory_agree(suite):
    catalog, scenarios = suite
    validate(catalog, scenarios)
    assert {s.id for s in scenarios.scenarios} == {s for c in catalog.cases for s in c.fixed_scenarios}


@pytest.mark.parametrize('mutation', ['missing_history', 'unknown_state', 'unsupported_pending', 'bad_assertion', 'negative_only'])
def test_incomplete_or_ignored_scenario_data_is_rejected(suite, mutation):
    value = suite[1].scenarios[0].model_dump()
    if mutation == 'missing_history':
        del value['initial']['history']
    elif mutation == 'unknown_state':
        value['initial']['hidden_prior_goal'] = True
    elif mutation == 'unsupported_pending':
        value['initial']['pending'] = {'kind': 'save'}
    elif mutation == 'bad_assertion':
        value['checks'][0]['field'] = 'reply.length_typo'
    else:
        value['checks'] = [{'field': 'task_count', 'op': 'eq', 'value': 0}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(value)


def test_partial_original_cannot_be_claimed_as_observed_replay(suite):
    catalog, scenarios = suite
    scenarios.scenarios[0].provenance = 'observed_sanitized'
    with pytest.raises(ValueError, match='partial original'):
        validate(catalog, scenarios)


def test_context_gap_cannot_be_hidden_and_acceptance_requires_record(suite):
    value = suite[0].model_dump()
    value['cases'][0]['source']['missing_context'] = []
    with pytest.raises(ValidationError):
        Catalog.model_validate(value)
    value = suite[0].model_dump()
    value['cases'][0]['acceptance'] = 'accepted'
    with pytest.raises(ValidationError):
        Catalog.model_validate(value)


@pytest.mark.parametrize('mutation', ['duplicate', 'orphan', 'wrong_case', 'doc_drift', 'renamed_test'])
def test_inventory_drift_and_broken_references_fail(suite, mutation):
    catalog, scenarios = suite
    if mutation == 'duplicate':
        scenarios.scenarios.append(scenarios.scenarios[0])
    elif mutation == 'orphan':
        catalog.cases[0].fixed_scenarios = []
    elif mutation == 'wrong_case':
        scenarios.scenarios[0].case_id = 'A005'
    elif mutation == 'doc_drift':
        catalog.cases[0].id = 'A999'
    else:
        catalog.cases[0].controlled[0] += '_renamed'
    with pytest.raises(ValueError):
        validate(catalog, scenarios)


@pytest.mark.parametrize('names', [[], ['A013', 'A099'], ['does-not-exist'], ['A013', 'A013'], ['A009']])
def test_unknown_empty_or_nonreplayable_selection_never_passes(suite, names):
    with pytest.raises(ValueError):
        select(suite[1].scenarios, names)


def test_offline_gate_does_not_import_runtime_or_create_database(tmp_path):
    database = tmp_path / 'must-not-exist.sqlite3'
    result = subprocess.run([sys.executable, '-c',
        'import sys; from tests.case_library.schema import load; load(); '
        'assert not any(k.startswith("agent_service") for k in sys.modules)'],
        cwd=ROOT / 'agent-service', env={**os.environ, 'REVIEW_TODAY_HARNESS_DB': str(database)},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not database.exists()


def test_cli_unknown_case_exits_before_service_import(tmp_path):
    output = tmp_path / 'not-a-result.jsonl'
    result = subprocess.run([sys.executable, 'tests/run_case_library.py', '--live',
                             '--cases', 'A099', '--output', str(output)],
        cwd=ROOT / 'agent-service', capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()


def test_fixture_history_and_current_plan_reach_actual_router_projection(suite, controlled):
    scenario = next(s for s in suite[1].scenarios if s.id == 'A013-current-plan-next')
    h = controlled.harness
    sid, others = seed(h, scenario)
    from agent_service.schemas import SessionMessageRequest
    accepted = h.accept(sid, SessionMessageRequest(client_message_id=identity('projection'), content=scenario.input))
    data = h.store.get(sid)
    context, last = h._context(data, data['runs'][accepted.run_id])
    assert [m['content'] for m in context['recent_messages']] == [
        scenario.initial.history[0].user, scenario.initial.history[0].coach]
    assert context['task']['content'] == scenario.initial.current_task.title
    assert [s['title'] for s in context['task']['context']['learning_plan']['steps']] == [s.title for s in scenario.initial.current_task.steps]
    assert last['content'] == scenario.input
    assert not others


def test_fixed_scenario_digest_and_ids_are_order_independent(suite, controlled):
    scenario = next(s for s in suite[1].scenarios if s.id == 'A013-foreign-goal-transition')
    sid, others = seed(controlled.harness, scenario)
    assert sid == identity(scenario.id)
    assert len(others) == 1
    assert controlled.store.get(others[0])['active_task_id']
    assert digest(scenario.model_dump()) == digest(dict(reversed(list(scenario.model_dump().items()))))
    assert controlled.store.get(sid)['tasks'] == {}


def test_wrong_behavior_is_a_failed_assertion_not_a_missing_result():
    checks = [Check(field='reply', op='contains', value='知识'),
              Check(field='task_count', op='eq', value=0),
              Check(field='reply_length', op='lte', value=160)]
    result = evaluate(checks, {'reply': '请提供完整项目，我来代写。', 'task_count': 1, 'reply_length': 300})
    assert [r['passed'] for r in result] == [False, False, False]
    assert result[0]['actual'] == '请提供完整项目，我来代写。'


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_recorder_preserves_input_actual_calls_and_failed_checks(suite, controlled, tmp_path):
    scenario = next(s for s in suite[1].scenarios if s.id == 'A012-greeting')
    controlled.decision = fixtures.intent('greeting', conversation_kind='social')
    # Intentionally wrong expectation tests our gate, not the product.
    scenario.checks.append(Check(field='task_count', op='eq', value=1))
    output = tmp_path / 'failure.jsonl'
    with RunReport(output, layer='live_fixed_context', planned=[scenario.id], fixture={}) as report:
        run_one(controlled.harness, report, scenario)
    data = records(output)
    assert not report.passed
    assert data[0]['models']['provider']
    assert data[1]['model_calls'][0]['input']
    assert data[1]['before']['messages'] == []
    assert data[1]['run']['intent']['conversation_kind'] == 'social'
    assert data[-1]['failed'] == [scenario.id]
    assert data[1]['language_review'] == 'pending'


def test_skipped_case_and_exception_are_persisted_as_failure(tmp_path, controlled):
    output = tmp_path / 'interrupted.jsonl'
    with pytest.raises(RuntimeError):
        with RunReport(output, layer='live_generated_flow', planned=['first', 'second'], fixture={}) as report:
            raise RuntimeError('synthetic interruption')
    footer = records(output)[-1]
    assert footer['automatic_result'] == 'FAIL'
    assert footer['missing'] == ['first', 'second']
    assert footer['error_type'] == 'RuntimeError'
    assert not report.passed


def test_results_cannot_overwrite_previous_evidence(tmp_path, controlled):
    output = tmp_path / 'existing.jsonl'
    output.write_text('old evidence')
    with pytest.raises(FileExistsError):
        with RunReport(output, layer='live_fixed_context', planned=['one'], fixture={}):
            pass
    assert output.read_text() == 'old evidence'


def test_blocked_tool_attempt_fails_even_if_caller_catches_error(tmp_path, controlled, suite):
    scenario = next(s for s in suite[1].scenarios if s.id == 'A012-greeting')
    original = controlled.model
    def bad_model(*args, **kwargs):
        from agent_service.conversation import web_search_text
        try:
            web_search_text('public synthetic query')
        except RuntimeError:
            pass
        return original(*args, **kwargs)
    controlled.decision = fixtures.intent('greeting', conversation_kind='social')
    output = tmp_path / 'blocked.jsonl'
    with patch('agent_service.conversation.parse_model', side_effect=bad_model):
        with RunReport(output, layer='live_fixed_context', planned=[scenario.id], fixture={}) as report:
            run_one(controlled.harness, report, scenario)
    assert not report.passed
    assert records(output)[1]['tool_attempts'] == ['web_search']


def test_case_input_context_change_changes_fingerprint(suite):
    scenario = suite[1].scenarios[0]
    previous = digest(scenario.model_dump())
    scenario.initial.current_task = None
    scenario.initial.task_history_index = None
    assert digest(scenario.model_dump()) != previous


def test_task_progress_without_related_history_is_rejected(suite):
    value = suite[1].scenarios[0].model_dump()
    value['initial']['task_history_index'] = None
    with pytest.raises(ValidationError, match='requires a history entry'):
        Scenario.model_validate(value)


@pytest.mark.parametrize('fault', ['truncated', 'duplicate', 'false_pass', 'missing_case', 'no_checks', 'no_model_calls', 'no_metadata'])
def test_report_reader_rejects_false_success(tmp_path, controlled, suite, fault):
    scenario = next(s for s in suite[1].scenarios if s.id == 'A012-greeting')
    controlled.decision = fixtures.intent('greeting', conversation_kind='social')
    output = tmp_path / 'report.jsonl'
    with RunReport(output, layer='live_fixed_context', planned=[scenario.id], fixture={}) as report:
        run_one(controlled.harness, report, scenario)
    assert read_report(output)['automatic_result'] == 'PASS'
    rows = records(output)
    if fault == 'truncated':
        rows.pop()
    elif fault == 'duplicate':
        rows.insert(1, rows[1])
    elif fault == 'false_pass':
        rows[1]['checks']['completed'] = False
    elif fault == 'missing_case':
        rows[0]['planned'].append('never-executed')
    elif fault == 'no_model_calls':
        rows[1]['model_calls'] = []
    elif fault == 'no_metadata':
        del rows[0]['code']
    else:
        rows[1]['checks'] = {}
    output.write_text('\n'.join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError):
        read_report(output)


def test_case_modes_match_runtime_contract():
    from typing import get_args
    from agent_service.schemas import SessionMode
    from tests.case_library.schema import InitialState
    assert set(get_args(InitialState.model_fields['mode'].annotation)) == set(get_args(SessionMode))


def test_message_whitespace_is_not_silently_normalized(suite):
    value = suite[1].scenarios[0].model_dump()
    value['input'] = '  算了，晚点再学吧\n'
    assert Scenario.model_validate(value).input == value['input']
    value['input'] = ' \n'
    with pytest.raises(ValidationError):
        Scenario.model_validate(value)


def test_heading_only_case_cannot_bypass_inventory_gate(suite, monkeypatch):
    original = Path.read_text
    def changed(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return value + '\n## A999 未登记的问题\n' if path == ROOT / 'docs/agent-iteration.md' else value
    monkeypatch.setattr(Path, 'read_text', changed)
    with pytest.raises(ValueError, match='case/document mismatch'):
        validate(*suite)


def test_recorder_refuses_daily_database_before_reading(tmp_path, controlled):
    from types import SimpleNamespace
    fake = SimpleNamespace(store=SimpleNamespace(tasks=SimpleNamespace(path=ROOT / 'daily.sqlite3')))
    with RunReport(tmp_path / 'rejected.jsonl', layer='live_fixed_context', planned=['one'], fixture={}) as report:
        with pytest.raises(ValueError, match='temporary database'):
            report.turn(fake, 'sid', None)
    assert not report.passed
