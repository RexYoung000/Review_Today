"""Build exact synthetic history/state before making any real semantic call."""
from __future__ import annotations

from dataclasses import asdict
import uuid

from .schema import digest

FIXED_TIME = '2026-09-17T00:00:00+00:00'


def identity(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'review-today-case/' + name))


def seed(harness, scenario):
    from agent_service.conversation import _new_run
    from agent_service.harness_store import HarnessTaskRecord
    from agent_service.learning_progress import set_plan

    sid = identity(scenario.id)

    def task_for(goal, owner, suffix):
        tid = identity(scenario.id + '/' + suffix)
        task = asdict(HarnessTaskRecord(task_id=tid, session_id=owner,
            client_message_id=identity(suffix + '/input'), content=goal.title,
            content_type='text', primary_language='zh', mode_preset=scenario.initial.mode,
            mode=goal.mode, status='awaiting_user', stage='teaching',
            created_at=FIXED_TIME, updated_at=FIXED_TIME,
            context=dict(conversation_managed=True, understanding=goal.understanding)))
        plan = set_plan(task, [step.title for step in goal.steps])
        for i, (step, given) in enumerate(zip(plan['steps'], goal.steps)):
            step.update(given.model_dump(), id=identity(tid + f'/step/{i}'))
        plan['current_step_id'] = plan['steps'][goal.current_step]['id']
        return tid, task

    with harness.store.transaction(sid) as data:
        data.update(mode=scenario.initial.mode, thinking_strength=scenario.initial.thinking_strength,
                    summary=scenario.initial.summary, paused=scenario.initial.paused,
                    pending=scenario.initial.pending, draft=scenario.initial.draft)
        for i, exchange in enumerate(scenario.initial.history):
            mid = identity(scenario.id + f'/history/{i}/user')
            run = _new_run(sid, mid, 'completed')
            run.update(run_id=identity(scenario.id + f'/history/{i}/run'),
                       created_at=FIXED_TIME, updated_at=FIXED_TIME, completed_at=FIXED_TIME,
                       social_reply_kind=exchange.social_reply_kind)
            data['runs'][run['run_id']] = run
            for role, content in [('user', exchange.user), ('coach', exchange.coach)]:
                data['messages'].append(dict(message_id=mid if role == 'user' else identity(mid + '/coach'),
                    role=role, content=content, content_type='text', created_at=FIXED_TIME,
                    run_id=run['run_id'], task_id=None, context={}, operation=None))
        if scenario.initial.current_task:
            tid, task = task_for(scenario.initial.current_task, sid, 'current-goal')
            index = scenario.initial.task_history_index
            origin_id = identity(scenario.id + f'/history/{index}/run')
            user_id = identity(scenario.id + f'/history/{index}/user')
            task['client_message_id'] = user_id
            task['context']['origin_run_id'] = origin_id
            current = task['context']['learning_plan']['steps'][scenario.initial.current_task.current_step]
            if current['state'] != 'pending':
                current['message_ids'] = [identity(user_id + '/coach')]
            for message in data['messages']:
                if message['run_id'] == origin_id:
                    message['task_id'] = tid
            data['runs'][origin_id]['task_id'] = tid
            data['tasks'][tid] = task
            data['active_task_id'] = tid

    others = []
    for i, goal in enumerate(scenario.initial.other_goals):
        owner = identity(scenario.id + f'/other/{i}')
        tid, task = task_for(goal, owner, f'other-goal/{i}')
        with harness.store.transaction(owner) as data:
            data['tasks'][tid] = task
            data['active_task_id'] = tid
        harness.memory_policy(owner, allowed=True, policy_version=0, content_version=0)
        others.append(owner)
    return sid, others


def facts(record):
    before, after, run = record['before'], record['after'], record['run']
    def plan_ids(data):
        return {key: [s['id'] for s in value['context'].get('learning_plan', {}).get('steps', [])]
                for key, value in data['tasks'].items()}
    current = after['tasks'].get(after['active_task_id'], {})
    reply = '\n'.join(record['replies'])
    intent = run.get('intent') or {}
    return {
        **{'intent.' + key: intent.get(key) for key in ('conversation_kind', 'clarification_kind', 'intents')},
        'social_reply_kind': run.get('social_reply_kind'), 'reply': reply, 'reply_length': len(reply),
        'stages': [e['stage'] for e in record['events']], 'task_count': len(after['tasks']),
        'tasks_unchanged': before['tasks'] == after['tasks'],
        'plan_ids_unchanged': plan_ids(before) == plan_ids(after) and bool(before['tasks']),
        'old_goals_unchanged': record['other_before'] == record['other_after'],
        'capture_offer_count': len(after.get('capture_offers') or {}),
        'goal_transfer': bool(run.get('goal_transfer')),
        'current_understanding': current.get('context', {}).get('understanding'),
    }


def evaluate(checks, observed):
    detail = []
    for check in checks:
        actual = observed[check.field]
        if check.op == 'eq':
            passed = type(actual) is type(check.value) and actual == check.value
        elif check.op in {'contains', 'excludes'}:
            passed = actual is not None and ((check.value in actual) == (check.op == 'contains'))
        else:
            passed = type(actual) is int and (actual >= check.value if check.op == 'gte' else actual <= check.value)
        detail.append(dict(field=check.field, op=check.op, expected=check.value, actual=actual, passed=passed))
    return detail


def run_one(harness, report, scenario):
    from agent_service.schemas import SessionMessageRequest
    sid, others = seed(harness, scenario)
    other_before = {s: harness.store.get(s) for s in others}
    record = report.turn(harness, sid, SessionMessageRequest(
        client_message_id=identity(scenario.id + '/target-input'), content=scenario.input,
        mode_preset=scenario.initial.mode, thinking_strength=scenario.initial.thinking_strength))
    record.update(other_before=other_before, other_after={s: harness.store.get(s) for s in others},
                  scenario_sha256=digest(scenario.model_dump()), provenance=scenario.provenance,
                  manual_review=scenario.manual_review)
    detail = evaluate(scenario.checks, facts(record))
    record['assertions'] = detail
    checks = {f'{i}:{d["field"]}:{d["op"]}': d['passed'] for i, d in enumerate(detail)}
    old_messages = record['before']['messages']
    checks['history_preserved'] = record['after']['messages'][:len(old_messages)] == old_messages
    report.add(scenario.id, record, checks)
