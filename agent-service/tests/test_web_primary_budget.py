"""Admission guards prevent paid retries and count unsuccessful attempts too."""
import pytest
from tests.compare_web_primary_live import Admission


def test_model_retry_and_global_cap_are_blocked_before_another_request():
    report = dict(model_requests=[], web_requests=[])
    admitted = Admission(report, lambda: None, max_models=2)
    step = {}
    admitted.model(step, 'first', 'configured-model', 'Schema')
    with pytest.raises(RuntimeError):
        admitted.model(step, 'first', 'configured-model', 'Schema')
    admitted.model({}, 'second', 'configured-model', 'Schema')
    with pytest.raises(RuntimeError):
        admitted.model({}, 'third', 'configured-model', 'Schema')
    assert len(report['model_requests']) == 2


def test_web_failure_keeps_its_reserved_slot():
    report = dict(model_requests=[], web_requests=[])
    admitted = Admission(report, lambda: None, max_web=1)
    record = admitted.web('first', 'deepseek', 'search', 'fixed public query')
    record['status'] = 'failed'
    with pytest.raises(RuntimeError):
        admitted.web('second', 'exa', 'search', 'fixed public query')
    assert len(report['web_requests']) == 1 and report['web_requests'][0]['status'] == 'failed'
