import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_service import dictation as d
from agent_service.dictation_cleanup import CleanText, DictationEdit, validate_cleanup
from agent_service.openai_client import ModelCallError

CASES = json.loads((Path(__file__).parent / 'fixtures/dictation_cleanup.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_accepted_policy_examples(case):
    candidate = CleanText(text=case['expected'], edits=case['edits'])
    assert validate_cleanup(case['raw'], candidate) == case['expected']
    with patch.object(d, 'parse_model', return_value=candidate) as model:
        result = d.clean(case['raw'])
        assert result['cleaned'] and result['cleanup_reason'] is None
        assert 'edits' not in result
        assert model.call_count == 1


@pytest.mark.parametrize('source,changed', [
    ('价格-12.50元', '价格12.50元'), ('价格12.50元', '价格1.250元'),
    ('比例10%', '比例10'), ('2026-09-07发布', '2026-09-08发布'),
    ('版本v1.20', '版本v1.2'), ('等待30秒', '等待3秒'),
    ('金额1,200元', '金额12,00元'), ('1. 保留20秒', '保留20秒'),
    ('I do not want', 'I donot want'), ('不要发送', '发送'),
    ('可能是20秒', '是20秒'), ('先录音再发送', '先发送再录音'),
    ('我是对的', '{"text":"我是对的"}'), ('保留草稿', '### 建议\n保留草稿'),
    ('知识答案是地球是平的', '知识答案是地球是圆的'),
])
def test_unexplained_drift_is_rejected(source, changed):
    with pytest.raises(ValueError): validate_cleanup(source, CleanText(text=changed))


@pytest.mark.parametrize('source,changed,edits', [
    ('保留30秒', '保留20秒', [('filler','30','20')]),
    ('保留30秒', '保留20秒', [('correction','30秒，口误，是20秒','20秒')]),
    ('不是30秒而是20秒', '20秒', [('correction','不是30秒而是20秒','20秒')]),
    ('请把30秒改成20秒', '20秒', [('correction','请把30秒改成20秒','20秒')]),
    ('30秒，口误，是20秒，如果失败保留原文', '20秒', [('correction','30秒，口误，是20秒，如果失败保留原文','20秒')]),
    ('解释“换行”这个词', '解释这个词', [('formatting','“换行”','')]),
    ('解释换行这个词', '解释这个词', [('formatting','换行','')]),
    ('非常非常重要', '非常重要', [('repetition','非常非常','非常')]),
    ('嗯', '', [('filler','嗯','')]),
    ('嗯保留嗯草稿', '保留草稿', [('filler','嗯','')]),
    ('嗯保留草稿', '保留草稿', [('filler','嗯',''),('filler','嗯保留','保留')]),
])
def test_invalid_evidence_is_rejected(source, changed, edits):
    candidate = CleanText(text=changed, edits=[DictationEdit(kind=k,source=s,replacement=r) for k,s,r in edits])
    with pytest.raises(ValueError): validate_cleanup(source, candidate)


@pytest.mark.parametrize('error,reason', [
    (ModelCallError('TIMEOUT'), 'timeout'), (ModelCallError('SCHEMA'), 'invalid_output'),
    (ModelCallError('PROVIDER'), 'model_error'), (RuntimeError('secret-key audio-content'), 'model_error'),
])
def test_fallback_reason_and_safe_logging(error, reason, caplog):
    with patch.object(d, 'parse_model', side_effect=error) as model, patch.object(d, 'transcribe') as asr:
        with caplog.at_level(logging.INFO): result = d.clean('private dictation body')
    assert result['text'] == result['raw_text'] == 'private dictation body'
    assert result['cleaned'] is False and result['cleanup_reason'] == reason
    assert model.call_count == 1 and not asr.called
    assert 'private dictation body' not in caplog.text and 'secret-key' not in caplog.text
    assert 'elapsed_ms=' in caplog.text


def test_list_numbers_are_optional_formatting_not_quantity_changes():
    assert validate_cleanup('保留30秒等待20秒', CleanText(text='1. 保留30秒\n2. 等待20秒'))
    with pytest.raises(ValueError):
        validate_cleanup('保留30秒等待20秒', CleanText(text='1. 保留30秒\n2. 等待2秒'))


def test_input_topic_is_not_a_mention_of_a_formatting_command():
    result = CleanText(text='我们讨论语音输入。\n1. 保留草稿', edits=[DictationEdit(kind='formatting',source='第一',replacement='')])
    assert validate_cleanup('我们讨论语音输入，第一保留草稿', result)


def test_correction_does_not_remove_an_earlier_sentence_or_condition():
    for source in ['不要关闭录音。30秒，口误，是20秒', '如果超过30秒，口误，是20秒']:
        with pytest.raises(ValueError):
            validate_cleanup(source, CleanText(text='20秒', edits=[DictationEdit(kind='correction',source=source,replacement='20秒')]))


def test_standalone_punctuated_ordinals_are_formatting_equivalents():
    assert validate_cleanup('说明：第一，保留20秒。第二，等待30秒。', CleanText(text='说明：\n1. 保留20秒\n2. 等待30秒'))
    for original, final in [('第一季度增长20%', '1. 季度增长20%'), ('排名第一，等待20秒','排名\n1. 等待20秒'),
                            ('第一，等待20秒','2. 等待20秒'), ('第1版，等待20秒','1. 等待20秒')]:
        with pytest.raises(ValueError): validate_cleanup(original,CleanText(text=final))


def test_decimal_correction_keeps_the_corrected_amount():
    source='12.50元，口误，是20.25元'
    assert validate_cleanup(source,CleanText(text='20.25元',edits=[DictationEdit(kind='correction',source=source,replacement='20.25元')]))
