"""Zero-request component replay of the observed parsed null preview."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def main():
    setup = json.loads((OUT / 'setup.json').read_text())
    directory = Path(setup['directory'])
    isolated = Path(tempfile.mkdtemp(prefix='review-today-preview-null-diagnosis-', dir='/tmp')).resolve()
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(isolated / 'checkpoint.sqlite3'), REVIEW_TODAY_JEV_TEST='0')
    def audit(event, args):
        if event == 'socket.connect': raise AssertionError('No network in diagnosis')
        if event == 'sqlite3.connect' and args[0] != ':memory:':
            assert Path(args[0]).resolve().is_relative_to(isolated)
    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT / 'agent-service'))
    from agent_service.schemas import MasteryEvaluation
    from agent_service.capture_preview import grounded_fields, optional_preview
    rows = [json.loads(line) for line in (directory / 'live-events.jsonl').read_text().splitlines()]
    output = [r for r in rows if r['type'] == 'semantic_output' and r['schema'] == 'MasteryEvaluation'][-1]
    request = next(r for r in rows if r['type'] == 'semantic_start' and r['call_id'] == output['call_id'])['input']
    data = json.loads((OUT / 'complete-answer-final.json').read_text())
    offer = next(iter(data['capture_offers'].values()))
    value = MasteryEvaluation.model_validate(copy.deepcopy(output['output']))
    value.validate_request(request)
    assert value.passed and value.capture_preview is None
    assert value.capture_quotes and all(q in request['reference'] for q in value.capture_quotes)
    assert value.capture_feedback_quotes and all(q in value.feedback for q in value.capture_feedback_quotes)
    assert grounded_fields(value.capture_preview, offer['fragments']) == {}
    controlled = dict(points=[
        dict(text='生成模型可能混入自身记忆、过度概括或补全无依据内容。', evidence_quotes=[value.capture_quotes[0]]),
        dict(text='需要核对来源的发布者和时间，以及地区、版本和适用前提。', evidence_quotes=[value.capture_quotes[1]])],
        summary=dict(text='检索相关不保证生成正确，仍需核对来源和适用条件。', evidence_quotes=value.capture_quotes[:2]))
    fields = grounded_fields(controlled, offer['fragments'])
    assert len(fields['preview_points']) == 2 and fields['preview_summary']
    assert optional_preview(None) is None and optional_preview({'points': [], 'summary': {}}) is None
    result = dict(outcome='REPRODUCED_PARSED_NULL_ACCEPTED_WITH_VALID_SELECTED_SOURCES',
        actual_model_requests=0, actual_web_operations=0,
        observed_evaluation_passed=True, parsed_preview=None,
        original_capture_quote_count=len(value.capture_quotes), original_feedback_quote_count=len(value.capture_feedback_quotes),
        selected_quotes_match_request_and_feedback=True, original_null_passes_request_validation=True,
        original_grounded_fields={}, offer_has_structured_preview=False,
        controlled_candidate_can_be_grounded=True, controlled_candidate_is_not_real_model_output=True,
        raw_provider_preview_available=False,
        raw_null_or_missing_vs_malformed_coercion_cannot_be_distinguished=True,
        optional_null_and_malformed_values_both_normalize_to_none=True,
        observed_chain='parsed MasteryEvaluation.capture_preview=None -> Run.capture_preview=None -> replace(None) clears fields -> native scope-summary fallback',
        limitation='Observer recorded the parsed schema, not the raw SDK response. Do not attribute null exclusively to a provider omission.',
        proposed_next_scope='Discuss a bounded missing-preview validation/repair handoff for new passed-answer invitations with valid sources; preserve grading, provenance, old-data fallback and one-repair limit. No implementation in this batch.')
    (OUT / 'preview-diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
