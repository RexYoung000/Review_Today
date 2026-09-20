"""Frozen Jev dialogue ablation: factual input projection, atomic questions and gates.

Only test tooling imports this module. No App, store, model or credential import.
"""
from __future__ import annotations

import copy
import json
import statistics

from pydantic import Field, model_validator

from tests.case_library.schema import InitialState
from .cases import Case, FIXTURES, Question, Strict, digest, load_suite, question
from .reporting import price_range, validate_report

VERSION = 'jev-dialogue-ablation-1'
VARIANTS = ('v0', 'v1', 'v2')
CONTRACT_KEYS = {'conversation_kind', 'knowledge_request', 'progress', 'programming_boundary',
                 'resource_boundary', 'conversation_repair', 'web_scope'}


def yn(instructions, yes, no):
    return question(instructions, {'yes': yes, 'no': no})


def atomic_questions(original):
    return {
        'asks_knowledge': yn(
            '阅读 current_input 和 recent_exchange。用户本轮是否要求获得具体知识解释或理解材料？'
            '沿用前文主题的举例、类比、换一种解释也算。会话流程纠错单独由 conversation_repair 判断。',
            '要求解释、比较、举例、类比、解读或分析给定材料；混合请求中存在这些要求也选 yes。',
            '仅问候、陪伴、学习状态建议、改变模式/进度、问助手能力、资源代办或纠正会话流程。'),
        'prior_knowledge_unanswered': yn(
            '只读 recent_exchange：其中 user 请求了具体知识解释，而 coach 尚未提供这个解释吗？'
            '没有前文时选 no。正常解释后再举例不属于尚未回答。',
            '最近用户问知识，助手却只让用户选择流程、澄清学习目标或做了无关回应，原知识问题仍未答。',
            '没有前文，或最近用户并非问具体知识，或助手已经回答了该知识问题。'),
        'conversation_repair': copy.deepcopy(original['conversation_repair']),
        'requests_defer': yn(
            '只判断 current_input 是否明确要求本轮暂缓/停止学习。状态建议、学习困难或切模式本身不算暂缓。',
            '用户明确要求今天先不学、晚些再学、先暂停；与其他要求并存也选 yes。',
            '没有要求暂缓；仅询问知识、学习困难建议、能力、切模式或继续。'),
        'requests_next': yn(
            '只判断 current_input 是否明确要求学习下一个内容或计划下一步。不要根据词语“学习”推断。',
            '明确要换下一个学习内容或向学习计划下一步推进。',
            '没有下一内容/下一步要求；仅说继续、切模式、举例、提问、暂缓或找资源。'),
        'continuation_reference': question(
            '判断 current_input 的续接指向。recent_exchange 是当前会话最近一轮，current_task 是当前会话任务。'
            '不要从其他会话猜目标；明确恢复旧学习与仅承接最近请求分开。',
            {'none': '没有恢复/接着做的要求；新问题、举例、下一主题、切模式、暂缓不算。',
             'recent_request': '本轮只说继续、接着做等省略对象的话，承接 recent_exchange 中最近请求；即使该请求被拒绝也仍指向它。',
             'prior_learning': '本轮明确要求恢复上次/之前未完成的学习目标，是否存在记录不影响此意图。'}),
        'requests_mode_change': yn(
            '本轮是否明确要求改变 Review Today 的学习模式？只用 current_input 的实际要求判断。',
            '明确要求切换为资料学习、主题探索、问题攻克、记忆整理等模式。',
            '未要求切模式；只是提到模式词语、提问或推进学习。'),
        'resource_request': question(
            '只判断 current_input 本身提出的资源请求。省略对象的“继续”由另题处理；'
            '引用文字、否定代办和解释下载技术本身均不是执行要求。',
            {'none': '没有让助手找下载资源/执行代办，也没有咨询这类能力；包含引用、否定或知识解释。',
             'capability_question': '主要问助手有没有找资源、下载或代办的能力，例如询问能否帮忙；不是明确下达找链接或下载指令。',
             'resource_delivery': '明确让助手找下载链接、下载或执行外部事务；附带知识问题、切模式或暂缓仍保留此请求。'}),
        'prior_resource_request': question(
            '只判断 recent_exchange.user 是否曾要求资源代办/咨询其能力。不要把助手的话当用户要求。'
            '没有 recent_exchange 时选 none。',
            {'none': '无前文，或最近用户仅问知识、推荐读物、学习控制、引用句子或否定代办。',
             'capability_question': '最近用户询问助手是否具备找资源、下载或代办能力。',
             'resource_delivery': '最近用户明确要求找下载链接、下载或执行资源代办。'}),
        'social_purpose': question(
            '只判断 current_input 是否表达问候感谢、明确陪聊或学习困难支持需求。'
            '这只是社交成分，是否同时有实质请求由程序结合其他问题判断。',
            {'none': '无上述社交目的；暂缓、切模式、普通知识请求或纠正流程本身不等于陪伴。',
             'social': '表达问候、感谢或简短社交收尾。',
             'companionship': '明确要求陪伴、随便聊天，包括今天不想学而想聊天。',
             'learning_support': '针对学习挫败、学不进去等寻求调整状态的建议。'}),
        'programming_boundary': copy.deepcopy(original['programming_boundary']),
        'web_scope': copy.deepcopy(original['web_scope']),
    }


def focus_state(state):
    """Copy actual facts verbatim. No labels, inferred summaries or gold access."""
    initial = state['initial']
    history = copy.deepcopy(initial['history'])
    task = initial['current_task']
    return dict(current_input=state['current_input'],
        recent_exchange=copy.deepcopy(history[-1]) if history else None,
        earlier_exchanges=[dict(index=i, **exchange) for i, exchange in enumerate(history[:-1])],
        current_task=copy.deepcopy(task),
        current_step=copy.deepcopy(task['steps'][task['current_step']]) if task else None,
        task_history_index=initial['task_history_index'],
        mode=initial['mode'], paused=initial['paused'], summary=initial['summary'],
        pending=initial['pending'], draft=initial['draft'])


def compose(labels, state):
    """Project atomic judgments into the same seven contracts, without gold."""
    source = focus_state(state) if 'initial' in state else state
    repair = labels['conversation_repair']
    knowledge = labels['asks_knowledge']
    if repair == 'yes' and knowledge != 'yes':
        knowledge = labels['prior_knowledge_unanswered']
    elif repair == 'unsure' and knowledge == 'no':
        knowledge = 'unsure'
    resource = labels['resource_request']
    reference = labels['continuation_reference']
    if resource == 'none' and reference == 'recent_request':
        prior = labels['prior_resource_request']
        resource = 'resource_delivery' if prior in {'resource_delivery', 'capability_question'} else prior
    if resource == 'resource_delivery' and knowledge == 'yes':
        resource = 'mixed_learning'
    if labels['requests_defer'] == 'yes':
        progress = 'defer'
    elif labels['requests_defer'] == 'unsure':
        progress = 'unsure'
    elif reference == 'prior_learning':
        progress = 'resume_prior'
    elif labels['requests_next'] == 'yes':
        progress = 'next_current' if source['current_task'] else 'clarify_next'
    elif labels['requests_next'] == 'unsure' or reference == 'unsure':
        progress = 'unsure'
    else:
        progress = 'none'
    substantive = (knowledge == 'yes' or repair == 'yes'
        or progress in {'resume_prior', 'next_current', 'clarify_next'}
        or labels['requests_mode_change'] == 'yes'
        or resource in {'resource_delivery', 'capability_question', 'mixed_learning'}
        or labels['programming_boundary'] not in {'none', 'unsure'})
    social = labels['social_purpose']
    kind = 'ordinary' if substantive or social == 'none' else social
    return dict(conversation_kind=kind, knowledge_request=knowledge, progress=progress,
        programming_boundary=labels['programming_boundary'], resource_boundary=resource,
        conversation_repair=repair, web_scope=labels['web_scope'])


class Scenario(Strict):
    split: str
    family: str = Field(min_length=1)
    base: Case
    atoms: dict[str, str]

    @model_validator(mode='after')
    def coherent(self):
        if self.split not in {'development', 'validation'} or self.base.kind != 'dialogue':
            raise ValueError('invalid calibration split/kind')
        if set(self.base.questions) != CONTRACT_KEYS or set(self.base.state) != {'initial', 'current_input'}:
            raise ValueError('invalid source contracts/state')
        InitialState.model_validate(self.base.state['initial'])
        if not isinstance(self.base.state['current_input'], str) or not self.base.state['current_input'].strip():
            raise ValueError('missing current input')
        questions = atomic_questions(self.base.questions)
        if self.atoms.keys() != questions.keys() or any(self.atoms[k] not in q.criteria or self.atoms[k] == 'unsure' for k, q in questions.items()):
            raise ValueError('missing/invalid atomic annotation')
        if compose(self.atoms, self.base.state) != self.base.expected:
            raise ValueError('atomic gold disagrees with fixed contract: ' + self.base.id)
        return self


def trial(scenario, variant):
    if variant not in VARIANTS:
        raise ValueError('unknown variant')
    base = scenario.base
    return Case(id=f'{scenario.split}/{base.id}/{variant}', kind='dialogue', model_role='router',
        state=copy.deepcopy(base.state) if variant == 'v0' else focus_state(base.state),
        questions=copy.deepcopy(base.questions) if variant != 'v2' else atomic_questions(base.questions),
        expected=dict(base.expected) if variant != 'v2' else dict(scenario.atoms),
        sources=base.sources, manual_review=base.manual_review)


def load_scenarios():
    fixture = json.loads((FIXTURES / 'calibration.json').read_text())
    base = [c for c in load_suite() if c.kind == 'dialogue']
    if fixture['version'] != VERSION or fixture['development_sha256'] != digest([c.model_dump() for c in base]):
        raise ValueError('development baseline changed; annotation review required')
    if fixture['atomic_questions_sha256'] != digest({k: q.model_dump() for k, q in atomic_questions(base[0].questions).items()}):
        raise ValueError('frozen atomic questions changed')
    if set(fixture['development_atoms']) != {c.id for c in base}:
        raise ValueError('development annotations missing/extra')
    scenarios = [Scenario(split='development', family=c.id.split('-')[0], base=c,
        atoms=fixture['development_atoms'][c.id]) for c in base]
    scenarios += [Scenario.model_validate({**s, 'base': {**s['base'], 'questions': base[0].questions}})
                  for s in fixture['validation']]
    if len(scenarios) != 55 or sum(s.split == 'validation' for s in scenarios) != 24:
        raise ValueError('expected 31 development and 24 validation scenarios')
    validate_scenarios(scenarios)
    return scenarios


def validate_scenarios(scenarios):
    if not scenarios or len({s.base.id for s in scenarios}) != len(scenarios):
        raise ValueError('empty/duplicate scenario plan')
    families = [{s.family for s in scenarios if s.split == split} for split in ('development', 'validation')]
    if families[0] & families[1]:
        raise ValueError('scenario family leaked across splits')
    prompts = [{s.base.state['current_input'] for s in scenarios if s.split == split} for split in ('development', 'validation')]
    if prompts[0] & prompts[1]:
        raise ValueError('same target utterance leaked across splits')


def plan(scenarios):
    validate_scenarios(scenarios)
    cases = []
    for i, scenario in enumerate(scenarios):
        order = VARIANTS[i % 3:] + VARIANTS[:i % 3]
        cases += [trial(scenario, variant) for variant in order]
    snapshot = [s.model_dump() for s in scenarios]
    return cases, dict(version=VERSION, scenarios=snapshot, scenarios_sha256=digest(snapshot),
        variants=list(VARIANTS), order='rotate variant order per scenario; serial pooled HTTP',
        scope='local judgments and offline consistency gates; no live Harness integration')


def gate_reasons(projected, raw, state):
    reasons = []
    if 'unsure' in raw.values():
        reasons.append('uncertain_judgment')
    if projected['conversation_kind'] != 'ordinary' and (
            projected['knowledge_request'] == 'yes' or projected['conversation_repair'] == 'yes'
            or projected['progress'] in {'next_current', 'clarify_next', 'resume_prior'}
            or projected['programming_boundary'] not in {'none', 'unsure'}
            or projected['resource_boundary'] not in {'none', 'unsure'}):
        reasons.append('social_substantive_conflict')
    task = state['initial']['current_task'] if 'initial' in state else state['current_task']
    if projected['progress'] == 'next_current' and not task:
        reasons.append('missing_current_task')
    if projected['progress'] == 'clarify_next' and task:
        reasons.append('existing_plan_conflict')
    if projected['knowledge_request'] == 'yes' and projected['resource_boundary'] == 'resource_delivery':
        reasons.append('mixed_request_conflict')
    if 'requests_defer' in raw:
        if raw['requests_defer'] == raw['requests_next'] == 'yes':
            reasons.append('progress_conflict')
        if raw['continuation_reference'] == 'recent_request' and not state['recent_exchange']:
            reasons.append('missing_reference')
    return reasons


def inspect_result(scenario, variant, row):
    if row['status'] != 'ok':
        return dict(projected=None, errors=None, gate_reasons=['call_failed'], exact=False)
    raw = {k: a['choice'] for k, a in row['answers'].items()}
    projected = compose(raw, row['input']['state']) if variant == 'v2' else raw
    errors = [dict(question=k, expected=v, actual=projected[k]) for k, v in scenario.base.expected.items() if projected[k] != v]
    return dict(projected=projected, errors=errors,
        gate_reasons=gate_reasons(projected, raw, row['input']['state']), exact=not errors)


def analyze(path):
    from pathlib import Path
    validate_report(path)
    values = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    header, rows = values[0], values[1:-1]
    metadata = header.get('experiment', {})
    if metadata.get('version') != VERSION or metadata.get('variants') != list(VARIANTS):
        raise ValueError('not a supported calibration report')
    scenarios = [Scenario.model_validate(s) for s in metadata['scenarios']]
    expected_cases, expected_metadata = plan(scenarios)
    if metadata != expected_metadata or header['cases'] != [c.model_dump() for c in expected_cases] or header['providers'] != ['jev']:
        raise ValueError('calibration manifest/trial mismatch')
    by_id = {r['id']: r for r in rows}
    details = []
    for s in scenarios:
        for variant in VARIANTS:
            identity = f'{s.split}/{s.base.id}/{variant}'
            row = by_id.get(identity)
            if row is None:
                details.append(dict(id=s.base.id, split=s.split, variant=variant, status='missing',
                    projected=None, errors=None, gate_reasons=['missing_result'], exact=False))
            else:
                details.append(dict(id=s.base.id, split=s.split, variant=variant, status=row['status'],
                    **inspect_result(s, variant, row)))
    groups = {}
    for split in ('development', 'validation'):
        for variant in VARIANTS:
            entries = [d for d in details if d['split'] == split and d['variant'] == variant]
            if not entries:
                continue
            recorded = [by_id[f'{split}/{d["id"]}/{variant}'] for d in entries if d['status'] != 'missing']
            valid = [r for r in recorded if r['status'] == 'ok']
            times = [r['elapsed_ms'] for r in recorded if r['attempts']]
            attempts = [a for r in recorded for a in r['attempts']]
            costs = [price_range('jev-1.13.0', a.get('usage'), header['prices']) for a in attempts]
            groups[f'{split}/{variant}'] = dict(planned=len(entries), recorded=len(recorded), valid=len(valid),
                raw_correct=sum(r['evaluation']['correct_questions'] for r in valid),
                raw_scored=sum(r['evaluation']['question_count'] for r in valid),
                contract_exact=sum(d['exact'] for d in entries),
                contract_correct=sum(7 - len(d['errors']) for d in entries if d['errors'] is not None),
                contract_scored=len(valid) * 7,
                review_required=sum(bool(d['gate_reasons']) for d in entries),
                unflagged=sum(not d['gate_reasons'] for d in entries),
                unflagged_wrong=sum(not d['gate_reasons'] and not d['exact'] for d in entries),
                median_ms=statistics.median(times) if times else None,
                min_ms=min(times) if times else None, max_ms=max(times) if times else None,
                requests=len(attempts),
                reported_input_tokens=sum((a.get('usage') or {}).get('input_tokens') or 0 for a in attempts),
                reported_output_tokens=sum((a.get('usage') or {}).get('output_tokens') or 0 for a in attempts),
                cost_complete=bool(attempts) and all(c is not None for c in costs),
                known_cost_usd=sum(c[1] for c in costs if c is not None) if any(c is not None for c in costs) else None)
    pairs = {}
    for split in ('development', 'validation'):
        for variant in ('v1', 'v2'):
            pairs[f'{split}/{variant}'] = {'fixed': [], 'regressed': []}
            for s in [s for s in scenarios if s.split == split]:
                base = next(d for d in details if d['id'] == s.base.id and d['variant'] == 'v0')
                other = next(d for d in details if d['id'] == s.base.id and d['variant'] == variant)
                if base['status'] != 'ok' or other['status'] != 'ok':
                    continue
                if other['exact'] and not base['exact']:
                    pairs[f'{split}/{variant}']['fixed'].append(s.base.id)
                if base['exact'] and not other['exact']:
                    pairs[f'{split}/{variant}']['regressed'].append(s.base.id)
    return dict(version=VERSION, groups=groups, paired=pairs, details=details,
        all_calls_valid=all(d['status'] == 'ok' for d in details),
        production_integrated=False, calibrated_threshold=False)


def markdown(path):
    summary = analyze(path)
    lines = ['# Jev 对话输入与问题拆分对照', '',
        'v0 原版；v1 只整理上下文；v2 整理上下文并拆分问题。v2 的七项结果经过程序组合，不是原始模型输出。',
        '回退检查只发现不确定或部分矛盾，未校准自动接管阈值，也没有执行完整 Harness。', '',
        '| 分组 | 有效/计划 | 原始判断正确/评分 | 七项契约整例命中 | 七项判断正确/评分 | 需复核 | 未拦截错误/未拦截样例 | 耗时中位数/范围 ms | 请求数 | 估算 USD |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name, g in summary['groups'].items():
        timing = '未知' if g['median_ms'] is None else f"{g['median_ms']:.1f} / {g['min_ms']:.1f}–{g['max_ms']:.1f}"
        cost = '未知' if g['known_cost_usd'] is None else f"{g['known_cost_usd']:.6f}"
        if not g['cost_complete']:
            cost += '（不完整）'
        lines.append(f"| {name} | {g['valid']}/{g['planned']} | {g['raw_correct']}/{g['raw_scored']} | {g['contract_exact']}/{g['planned']} | {g['contract_correct']}/{g['contract_scored']} | {g['review_required']} | {g['unflagged_wrong']}/{g['unflagged']} | {timing} | {g['requests']} | {cost} |")
    lines += ['', '## 相对本轮 v0 的整例变化', '']
    for name, values in summary['paired'].items():
        lines.append(f"- {name}：修正 {values['fixed']}；新增错误 {values['regressed']}。")
    lines += ['', '## 全部契约差异、失败和回退项', '']
    for d in summary['details']:
        if not d['exact'] or d['gate_reasons']:
            lines.append(f"- {d['split']}/{d['id']}/{d['variant']}：{d['status']}；差异 {json.dumps(d['errors'], ensure_ascii=False)}；回退原因 {d['gate_reasons']}。")
    return '\n'.join(lines) + '\n'
