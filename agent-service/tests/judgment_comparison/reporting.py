"""Self-contained append-only evidence; recompute outcomes when reading it."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess

from .cases import Case, FIXTURES, ROOT, digest, evaluate


def code_version():
    files = sorted((ROOT / 'agent-service/tests/judgment_comparison').glob('*.py'))
    files += [ROOT / 'agent-service/tests/run_judgment_comparison.py',
              ROOT / 'agent-service/agent_service/config.py',
              ROOT / 'agent-service/agent_service/conversation_prompts.py']
    files += sorted(FIXTURES.glob('*.json'))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                source_sha256=digest(hashes), files=hashes)


def price_range(model, usage, prices):
    rates = prices['rates'].get(model)
    if not rates or not usage or any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('input_tokens', 'output_tokens')):
        return None
    inputs, outputs, cached = (usage.get(k) for k in ('input_tokens', 'output_tokens', 'cached_input_tokens'))
    if type(cached) is not int or not 0 <= cached <= inputs:
        lower = inputs * rates['cached'][0] + outputs * rates['output'][0]
        upper = inputs * rates['input'][1] + outputs * rates['output'][1]
    else:
        lower = (inputs - cached) * rates['input'][0] + cached * rates['cached'][0] + outputs * rates['output'][0]
        upper = (inputs - cached) * rates['input'][1] + cached * rates['cached'][1] + outputs * rates['output'][1]
    return [round(lower / 1_000_000, 10), round(upper / 1_000_000, 10)]


def summarize(header, rows, *, interrupted=False):
    planned = [(c['id'], p) for c in header['cases'] for p in header['providers']]
    observed = [(r['id'], r['provider']) for r in rows]
    missing = [list(pair) for pair in planned if pair not in observed]
    errors = [list(pair) for pair, r in zip(observed, rows) if r['status'] != 'ok']
    groups = {}
    for provider in header['providers']:
        for kind in ('dialogue', 'memory', 'source', 'grading'):
            values = [r for r in rows if r['provider'] == provider and r['kind'] == kind]
            if not values:
                continue
            valid = [r for r in values if r['status'] == 'ok']
            scores = [r['evaluation'] for r in valid]
            costs, usage, requests = [], [], 0
            for r in values:
                for attempt in r['attempts']:
                    requests += 1
                    reported = attempt.get('usage')
                    if reported is not None:
                        usage.append(reported)
                    cost = price_range(r['requested_model'], reported, header['prices'])
                    if cost is not None:
                        costs.append(cost)
            elapsed = [r['elapsed_ms'] for r in valid]
            warm = [r['elapsed_ms'] for r in valid if not r['cold_start']]
            review = sum(r['status'] != 'ok' or r['evaluation']['needs_review'] for r in values)
            question_count = sum(s['question_count'] for s in scores)
            correct = sum(s['correct_questions'] for s in scores)
            expected_rows = [c for c in header['cases'] if c['kind'] == kind]
            expected_questions = sum(len(c['questions']) for c in expected_rows)
            groups[provider + '/' + kind] = dict(planned=len(expected_rows), recorded=len(values), valid=len(valid),
                exact_cases=sum(s['all_match'] for s in scores),
                questions_scored=question_count, questions_expected=expected_questions, correct_questions=correct,
                accuracy_on_valid=round(correct / question_count, 6) if question_count else None,
                needs_review=review, review_rate=round(review / len(values), 6),
                false_selected=sum(len(s['false_selected']) for s in scores),
                missed_selected=sum(len(s['missed_selected']) for s in scores),
                false_mastery=sum(s['false_mastery'] for s in scores),
                median_ms=statistics.median(elapsed) if elapsed else None,
                warm_median_ms=statistics.median(warm) if warm else None,
                min_ms=min(elapsed) if elapsed else None, max_ms=max(elapsed) if elapsed else None,
                transport_requests=requests, usage_records=len(usage),
                reported_input_tokens=sum(u.get('input_tokens') or 0 for u in usage),
                reported_output_tokens=sum(u.get('output_tokens') or 0 for u in usage),
                cost_complete=len(costs) == requests and all(r['status'] != 'unavailable' for r in values),
                known_cost_usd_range=[round(sum(c[i] for c in costs), 8) for i in (0, 1)] if costs else None)
    return dict(type='summary', planned=len(planned), recorded=len(rows), missing=missing, errors=errors,
                interrupted=interrupted, execution_complete=not missing and not errors and not interrupted,
                all_assertions_match=bool(rows) and not missing and not errors and not interrupted
                    and all(r['evaluation']['all_match'] for r in rows), groups=groups,
                native_tested=False, product_integrated=False, rex_acceptance='not_requested')


def validate_report(path):
    values = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if len(values) < 2 or values[0].get('type') != 'header' or values[-1].get('type') != 'summary':
        raise ValueError('incomplete report: header and final summary required')
    header, rows, summary = values[0], values[1:-1], values[-1]
    if header.get('schema_version') != 1 or header.get('layer') != 'paired_component_judgment':
        raise ValueError('unsupported report schema/layer')
    if not header.get('started_at') or not header.get('code', {}).get('source_sha256'):
        raise ValueError('missing report provenance')
    if digest(header['code']['files']) != header['code']['source_sha256']:
        raise ValueError('inconsistent code fingerprint')
    providers = header.get('providers')
    if not isinstance(providers, list) or not providers or len(providers) != len(set(providers)) or set(providers) - {'jev', 'deepseek'}:
        raise ValueError('invalid provider plan')
    cases = [Case.model_validate(c) for c in header.get('cases', [])]
    lookup = {c.id: c for c in cases}
    if not cases or len(lookup) != len(cases) or digest(header['cases']) != header.get('suite_sha256'):
        raise ValueError('empty/duplicate/inconsistent case plan')
    seen = set()
    for row in rows:
        pair = (row.get('id'), row.get('provider'))
        if row.get('type') != 'result' or pair in seen or pair[0] not in lookup or pair[1] not in providers:
            raise ValueError('unknown/duplicate result')
        seen.add(pair)
        case = lookup[pair[0]]
        if row.get('case_sha256') != digest(case.model_dump()) or row.get('input') != case.payload() or row.get('kind') != case.kind:
            raise ValueError('recorded input/case mismatch')
        expected_model = 'jev-1.13.0' if pair[1] == 'jev' else header['deepseek_models'][case.model_role]
        if row.get('requested_model') != expected_model:
            raise ValueError('recorded model mismatch')
        request = row.get('request', {})
        if request.get('model') != expected_model:
            raise ValueError('request model mismatch')
        if pair[1] == 'jev':
            if request != dict(model=expected_model, **case.payload()):
                raise ValueError('actual request differs from shared input')
        else:
            from .adapters import response_schema
            expected_input = [dict(role='system', content=header['deepseek_system']),
                dict(role='user', content=json.dumps(case.payload(), ensure_ascii=False, sort_keys=True))]
            if (request.get('input') != expected_input or request.get('reasoning') != {'effort': 'none'}
                    or request.get('text', {}).get('format', {}).get('schema') != response_schema(case)):
                raise ValueError('DeepSeek request differs from declared comparison')
        if type(row.get('cold_start')) is not bool or type(row.get('elapsed_ms')) not in {int, float} or not math.isfinite(row['elapsed_ms']) or row['elapsed_ms'] < 0:
            raise ValueError('invalid timing metadata')
        attempts = row.get('attempts')
        if not isinstance(attempts, list) or len(attempts) > 2:
            raise ValueError('invalid attempt ledger')
        for index, attempt in enumerate(attempts):
            if attempt.get('number') != index + 1:
                raise ValueError('invalid attempt sequence')
            if attempt.get('status') is not None and type(attempt['status']) is not int:
                raise ValueError('invalid HTTP status')
            usage = attempt.get('usage')
            if usage is not None:
                if not isinstance(usage, dict) or set(usage) != {'input_tokens', 'output_tokens', 'cached_input_tokens'}:
                    raise ValueError('invalid usage metadata')
                if any(v is not None and (type(v) is not int or v < 0) for v in usage.values()):
                    raise ValueError('invalid token count')
                if usage['cached_input_tokens'] is not None and (usage['input_tokens'] is None or usage['cached_input_tokens'] > usage['input_tokens']):
                    raise ValueError('invalid cache count')
        if row['status'] not in {'ok', 'error', 'unavailable'}:
            raise ValueError('unknown result status')
        if row['status'] == 'ok':
            if not row.get('attempts') or row['attempts'][-1].get('status') != 200 or row['attempts'][-1].get('error') is not None:
                raise ValueError('success without successful request')
            if pair[1] == 'jev' and row.get('actual_model') != 'jev-1.13.0':
                raise ValueError('Jev version mismatch')
            raw = row.get('raw_response')
            if not isinstance(raw, dict) or raw.get('model') != row.get('actual_model'):
                raise ValueError('missing/inconsistent actual response')
            if pair[1] == 'jev':
                actual_answers = raw.get('answers')
            else:
                if raw.get('status') != 'completed':
                    raise ValueError('incomplete actual response')
                text = ''.join(p['text'] for o in raw.get('output', []) for p in o.get('content', []) if p.get('type') == 'output_text')
                actual_answers = json.loads(text).get('answers')
            if actual_answers != row['answers']:
                raise ValueError('reported answers differ from actual response')
            if evaluate(case, row['answers']) != row.get('evaluation'):
                raise ValueError('stored judgment disagrees with actual answers')
        elif row.get('evaluation') is not None or row.get('answers') is not None or not row.get('error'):
            raise ValueError('failure masquerades as a semantic answer')
        elif (row['status'] == 'error' and not attempts) or (row['status'] == 'unavailable' and attempts):
            raise ValueError('failed/blocked attempt mismatch')
    rebuilt = summarize(header, rows, interrupted=summary.get('interrupted', False))
    if summary != rebuilt:
        raise ValueError('summary disagrees with actual records')
    return rebuilt


def markdown_report(path):
    summary = validate_report(path)
    values = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    header, rows = values[0], values[1:-1]
    lines = ['# Jev / DeepSeek 局部判断对照', '',
        '本报告只衡量固定合成材料上的局部判断，不是完整会话、App 性能、权限执行或掌握状态验收。', '',
        f"执行完整：{summary['execution_complete']}；全部断言命中：{summary['all_assertions_match']}。",
        'needs_review 仅统计 unsure 或调用失败；并未据此校准自动接管阈值。DeepSeek 自报概率不视为已校准。', '',
        '| 模型 / 类别 | 有效 / 计划 | 整例命中 | 判断命中 | 待复核 | 耗时中位数 / 范围 ms | 已知费用 USD 范围 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for key, g in summary['groups'].items():
        timing = f"{g['median_ms']} / {g['min_ms']}–{g['max_ms']}"
        cost = str(g['known_cost_usd_range']) + ('' if g['cost_complete'] else '（用量不完整）')
        lines.append(f"| {key} | {g['valid']}/{g['planned']} | {g['exact_cases']} | {g['correct_questions']}/{g['questions_scored']} | {g['needs_review']} | {timing} | {cost} |")
    lines += ['', '## 所有差异与失败', '']
    for row in rows:
        if row['status'] != 'ok':
            lines.append(f"- {row['provider']} / {row['id']}：{row['status']} / {row['error']}")
        else:
            e = row['evaluation']
            for error in e['errors']:
                answer = row['answers'][error['question']]
                lines.append(f"- {row['provider']} / {row['id']} / {error['question']}：期望 {error['expected']}，实际 {error['actual']}，confidence={answer['confidence']}。")
            if e['false_selected'] or e['missed_selected']:
                lines.append(f"- {row['provider']} / {row['id']}：误选 {e['false_selected']}；漏选 {e['missed_selected']}。")
    if summary['missing']:
        lines += ['', '缺失结果：' + json.dumps(summary['missing'], ensure_ascii=False)]
    lines += ['', '## 计量边界', '',
        '- 每个样例每方一次有效判断；瞬时错误最多额外一次，失败也保留。首个请求 cold_start 单列于原始记录。',
        '- 候选只按明确 relevant 进入建议清单，同档保留输入顺序；去重、官方域名与数量限制由程序执行。未评测概率排序的长期收益。',
        '- 判断总数仅分母 questions_scored 是有效请求；失败/缺失另计，不能当作正确。',
        '- 费用是价格快照下的估算范围，不是账单；输出概率是模型结果，不是本业务正确率。',
        '- 输入含合成前文和任务/其他目标状态；标准答案与来源注释没有发送给模型。',
        '- 未运行完整 Harness 或原生 App；无法据此认定现有工作流可以被直接替换。', '',
        f"价格核对日：{header['prices']['checked_at']}；[TypeSafe]({header['prices']['sources']['jev']})；[DeepSeek]({header['prices']['sources']['deepseek']})。", '']
    return '\n'.join(lines)
