"""Offline accounting guards for the opt-in complete-conversation comparison."""
import pytest
from tests.compare_web_ab_live import Admission, mask_labels


def budget(**changes):
    return dict(max_requests_per_model_step=2, max_model_requests_per_job=3,
                max_model_requests=4, max_tool_requests_per_job=2, max_web_requests=3, **changes)


def test_normal_repair_is_admitted_but_third_request_is_blocked():
    report = dict(model_requests=[], web_requests=[])
    admission = Admission(budget(), report, lambda: None)
    step = dict(id='step', node='intent')
    first = admission.model(step, 'a', 'model', 'Schema')
    first['status'] = 'failed'
    admission.model(step, 'a', 'model', 'Schema')
    with pytest.raises(RuntimeError, match='MODEL_ADMISSION_STOPPED'):
        admission.model(step, 'a', 'model', 'Schema')
    assert len(report['model_requests']) == 2
    assert report['model_requests'][1]['attempt'] == 2


def test_per_job_and_global_limits_apply_before_dispatch():
    report = dict(model_requests=[], web_requests=[])
    admission = Admission(budget(), report, lambda: None)
    for index in range(3):
        admission.model(dict(id=str(index), node='answer'), 'a', 'm', 'S')
    with pytest.raises(RuntimeError):
        admission.model(dict(id='new', node='answer'), 'a', 'm', 'S')
    admission.model(dict(id='other', node='answer'), 'b', 'm', 'S')
    with pytest.raises(RuntimeError):
        admission.model(dict(id='last', node='answer'), 'c', 'm', 'S')
    assert len(report['model_requests']) == 4


def test_web_failures_keep_slots_and_other_jobs_cannot_exceed_global_limit():
    report = dict(model_requests=[], web_requests=[])
    admission = Admission(budget(), report, lambda: None)
    admission.web('a', 'exa', 'read', 'public-url')['status'] = 'failed'
    admission.web('a', 'deepseek', 'search', 'public query')
    with pytest.raises(RuntimeError):
        admission.web('a', 'tavily', 'read', 'public-url')
    admission.web('b', 'exa', 'read', 'public-url')
    with pytest.raises(RuntimeError):
        admission.web('c', 'exa', 'read', 'public-url')
    assert len(report['web_requests']) == 3


def test_label_mask_retains_source_claims_and_nested_public_prose():
    original = dict(provider='deepseek', sources=[dict(provider='exa', url='https://example.com',
                    content='DeepSeek public product documentation')], context=dict(runtime_models=['m'], current_inputs=['question']))
    masked = mask_labels(original)
    assert masked == dict(sources=[dict(url='https://example.com', content='DeepSeek public product documentation')],
                          context=dict(current_inputs=['question']))
    assert original['provider'] == 'deepseek'
