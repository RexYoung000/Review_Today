"""Offline preflight and one-field intervention for an isolated Harness replay."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import statistics

from .boundaries import analyze, file_hash, load_scenarios, plan, trial, verify_selection
from .calibration import gate_reasons
from .cases import ROOT, digest
from .reporting import price_range


def load_cache(selection_path, validation_path):
    selected = verify_selection(selection_path)
    if selected['candidate'] != 'resource':
        raise ValueError('this limited replay only supports the resource candidate')
    validation = analyze(validation_path)
    candidate, baseline = (validation['groups']['validation/' + v] for v in ('resource', 'v1'))
    if (not validation['all_calls_valid'] or candidate['exact'] <= baseline['exact']
            or candidate['risk_cases'] >= baseline['risk_cases']
            or validation['paired']['validation/resource']['new_risks']):
        raise ValueError('validation did not meet the frozen Harness experiment conditions')
    values = [json.loads(s) for s in Path(validation_path).read_text().splitlines() if s.strip()]
    _, expected = plan([s for s in load_scenarios() if s.split == 'validation'], ('v0', 'v1', 'resource'))
    if values[0]['experiment'] != expected:
        raise ValueError('full frozen validation plan required')
    evidence = ROOT / selected['evidence'][0]['path']
    cache = {row['id'].split('/')[1]: row for row in
             (json.loads(s) for s in evidence.read_text().splitlines())
             if row['type'] == 'result' and row['id'].endswith('/resource')}
    return cache, dict(kind='cached_resource_field_intervention', candidate='resource',
        selection_sha256=file_hash(selection_path), validation_sha256=file_hash(validation_path),
        regression_sha256=file_hash(evidence),
        limitations=['Known 31 scenarios, cached Jev labels; not an independent semantic validation.',
                    'DeepSeek generates full intent and replies; only the resource field may be changed.',
                    'Elapsed time excludes fresh Jev inference; no App acceleration or production adoption claim.'])


def project(original, cached):
    """Never derive a full intent or a missing knowledge excerpt from a label."""
    reason, candidate = None, None
    if cached.get('status') != 'ok':
        reason = 'jev_call_failed'
    else:
        labels = {k: v['choice'] for k, v in cached['answers'].items()}
        candidate = labels['resource_boundary']
        reasons = gate_reasons(labels, labels, cached['input']['state'])
        if reasons:
            reason = 'judgment_review:' + ','.join(reasons)
        elif candidate == 'mixed_learning':
            excerpt = original.get('resource_learning_request', '').strip()
            text = cached['input']['state']['current_input']
            if not excerpt or excerpt == text.strip() or excerpt not in text:
                reason = 'missing_independent_learning_excerpt'
        if candidate not in {'none', 'capability_question', 'resource_delivery', 'mixed_learning'}:
            reason = 'invalid_resource_label'
    after = copy.deepcopy(original)
    if reason is None:
        after['resource_boundary'] = candidate
    return dict(source_id=cached.get('id'), candidate=candidate, applied=reason is None,
        fallback_reason=reason, before=copy.deepcopy(original), after=after)


def bind_interceptor(observed_parse, current_context):
    """Bind identity BEFORE I/O: a timed-out call may finish in a later turn."""
    def intercept(system, user, schema, **kwargs):
        context = current_context()
        value = observed_parse(system, user, schema, **kwargs)
        if context['variant'] == 'resource' and schema.__name__ == 'IntentDecision' and not context['events']:
            event = project(value.model_dump(), context['cached'])
            context['events'].append(event)
            return schema.model_validate(event['after'])
        return value
    return intercept


def observed_boundaries(record, expected):
    """Additional audit against existing scope contracts, not a new gold label.

    Legacy reply assertions may pass a generic resource refusal for a coding
    capability request. Check the branch actually executed, retaining both scores.
    """
    if record['run']['status'] != 'completed':
        return dict(scored=False, passed=False, errors=['execution_incomplete'])
    errors = []
    resource = bool(record['run'].get('resource_scope_reply'))
    programming = bool(record['run'].get('programming_scope_reply'))
    if resource != (expected['resource_boundary'] != 'none'):
        errors.append('wrong_resource_reply' if resource else 'missing_resource_reply')
    if programming != (expected['programming_boundary'] != 'none'):
        errors.append('wrong_programming_reply' if programming else 'missing_programming_reply')
    return dict(scored=True, passed=not errors, errors=errors)


def summarize_harness(path):
    from tests.case_library.results import read_report
    from tests.case_library.schema import Scenario, digest
    from tests.case_library.replay import evaluate, facts
    base = read_report(Path(path))
    values = [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]
    header, rows = values[0], [v for v in values if v['type'] == 'result']
    fixture = header['fixture']
    if fixture.get('experiment', {}).get('kind') != 'cached_resource_field_intervention':
        raise ValueError('not a resource intervention report')
    scenarios = {s['id']: Scenario.model_validate(s) for s in fixture['scenarios']}
    if len(scenarios) != 31 or set(header['planned']) != {s + '/' + v for s in scenarios for v in ('deepseek', 'resource')}:
        raise ValueError('complete paired 31-scenario replay required')
    groups = {}
    gold = {s.base.id: s for s in load_scenarios() if s.split == 'regression' and s.base.id in scenarios}
    for identity in scenarios:
        if fixture['cached_judgments'][identity]['case_sha256'] != digest(trial(gold[identity], 'resource').model_dump()):
            raise ValueError('existing scope expectations changed since cached judgment')
    audits = {}
    for row in rows:
        identity, variant = row['id'].rsplit('/', 1)
        scenario = scenarios[identity]
        if row['scenario_sha256'] != digest(scenario.model_dump()) or row['input']['content'] != scenario.input:
            raise ValueError('scenario/input mismatch')
        assertions = evaluate(scenario.checks, facts(row))
        if row['assertions'] != assertions:
            raise ValueError('assertions disagree with observed Harness facts')
        for index, check in enumerate(assertions):
            key = f'{index}:{check["field"]}:{check["op"]}'
            if row['checks'][key] != check['passed']:
                raise ValueError('checks disagree with assertions')
        interventions = row['resource_interventions']
        if variant == 'deepseek' and interventions or len(interventions) > 1:
            raise ValueError('unexpected intervention')
        original = next((c['output'] for c in row['model_calls'] if c['schema'] == 'IntentDecision' and 'output' in c), None)
        for event in interventions:
            if event['before'] != original or event != project(original, fixture['cached_judgments'][identity]):
                raise ValueError('intervention does not preserve original DeepSeek output')
        if variant == 'resource' and original is not None and len(interventions) != 1:
            raise ValueError('missing intervention record')
        audits[row['id']] = observed_boundaries(row, gold[identity].base.expected)
    for variant in ('deepseek', 'resource'):
        current = [r for r in rows if r['id'].endswith('/' + variant)]
        times = [r['replay_elapsed_ms'] for r in current]
        ledger = [c for r in current for c in r['run'].get('model_calls', [])]
        usage = [u for c in ledger for u in c['usage']]
        costs = [price_range(c['model'], u, fixture['prices']) for c in ledger for u in c['usage']]
        requests = sum(c['transport_requests'] for c in ledger)
        groups[variant] = dict(planned=31, recorded=len(current), passed=sum(r['automatic_result'] == 'PASS' for r in current),
            semantic_calls=sum(len(r['model_calls']) for r in current),
            transport_requests=requests, usage_records=len(usage),
            input_tokens=sum(u.get('input_tokens') or 0 for u in usage),
            output_tokens=sum(u.get('output_tokens') or 0 for u in usage),
            usage_complete=bool(requests) and len(usage) == requests and all(c is not None for c in costs),
            known_cost_usd_range=[sum(c[i] for c in costs if c is not None) for i in (0, 1)] if any(c is not None for c in costs) else None,
            assertions=sum(len(r['checks']) for r in current),
            assertions_passed=sum(sum(r['checks'].values()) for r in current),
            scope_audit_scored=sum(audits[r['id']]['scored'] for r in current),
            scope_audit_passed=sum(audits[r['id']]['passed'] for r in current),
            scope_audit_failed=[r['id'] for r in current if audits[r['id']]['scored'] and not audits[r['id']]['passed']],
            combined_passed=sum(r['automatic_result'] == 'PASS' and audits[r['id']]['passed'] for r in current),
            median_ms=statistics.median(times) if times else None,
            min_ms=min(times) if times else None, max_ms=max(times) if times else None,
            applied=sum(e['applied'] for r in current for e in r['resource_interventions']),
            changed=sum(e['before'] != e['after'] for r in current for e in r['resource_interventions']),
            fallback=sum(bool(e['fallback_reason']) for r in current for e in r['resource_interventions']),
            failed=[r['id'] for r in current if r['automatic_result'] != 'PASS'])
    paired = dict(fixed=[], regressed=[], scope_regressed=[], execution_differences=[])
    by_id = {r['id']: r for r in rows}
    for identity in scenarios:
        baseline, candidate = (by_id.get(identity + '/' + v) for v in ('deepseek', 'resource'))
        if baseline and candidate:
            if baseline['run']['status'] != 'completed' or candidate['run']['status'] != 'completed':
                paired['execution_differences'].append(dict(id=identity,
                    deepseek=baseline['run']['status'], resource=candidate['run']['status']))
                continue  # A transport failure is not a semantic improvement.
            if baseline['automatic_result'] != 'PASS' and candidate['automatic_result'] == 'PASS':
                paired['fixed'].append(identity)
            if baseline['automatic_result'] == 'PASS' and candidate['automatic_result'] != 'PASS':
                paired['regressed'].append(identity)
            if audits[baseline['id']]['passed'] and not audits[candidate['id']]['passed']:
                paired['scope_regressed'].append(identity)
    audited = base['automatic_result'] == 'PASS' and all(a['passed'] for a in audits.values())
    return dict(result=base, audited_result='PASS' if audited else 'FAIL',
        groups=groups, paired=paired, scope_audits=audits, new_jev_requests=0,
        timing_includes_fresh_jev=False, product_integrated=False)
