"""Per-Run admission budget and durable usage; no text, credentials or reasoning."""
import time
import uuid

from agent_service.call_errors import CallError

MODEL_ATTEMPTS = 12
ESTIMATED_INPUT_LIMIT = 512_000
RUN_SECONDS = 180


class RunBudgetError(CallError):
    namespace = 'RUN'


def begin(run):
    run.setdefault('model_calls', [])
    run.setdefault('execution_budget', dict(id=str(uuid.uuid4()), started=time.time(),
                                          attempts=0, estimated_input_tokens=0))


def remaining(run):
    budget = run.get('execution_budget')
    if not budget:
        return RUN_SECONDS
    value = RUN_SECONDS - (time.time() - budget['started'])
    if value <= 0:
        raise RunBudgetError('BUDGET_TIME', 'turn deadline exceeded')
    return value


def reserve(h, sid, rid, rev, *, node, model, estimated_input, background=False):
    with h.store.transaction(sid, None if background else rid, None if background else rev) as data:
        run = data['runs'][rid]
        if background:
            from agent_service.conversation_store import Superseded
            if data.get('foreground') or data.get('status', 'active') != 'active':
                raise Superseded()
            run.setdefault('maintenance_budget', dict(id=str(uuid.uuid4()), started=time.time(), attempts=0, estimated_input_tokens=0))
            budget = run['maintenance_budget']
            remaining({'execution_budget': budget})
        else:
            begin(run)
            remaining(run)
            budget = run['execution_budget']
        if budget['attempts'] >= MODEL_ATTEMPTS:
            raise RunBudgetError('BUDGET_CALLS', 'turn call limit reached')
        if budget['estimated_input_tokens'] + estimated_input > ESTIMATED_INPUT_LIMIT:
            raise RunBudgetError('BUDGET_INPUT', 'turn estimated input limit reached')
        budget['attempts'] += 1
        budget['estimated_input_tokens'] += estimated_input
        identity = str(uuid.uuid4())
        run.setdefault('model_calls', []).append(dict(id=identity, budget_id=budget['id'], revision=rev,
            background=background,
            node=node, model=model, estimated_input_tokens=estimated_input,
            transport_requests=0, usage_state='unavailable', usage=[], status='started'))
        return identity


def request(h, sid, rid, rev, call_id, *, background=False):
    with h.store.transaction(sid, None if background else rid, None if background else rev) as data:
        run = data['runs'][rid]
        if background:
            from agent_service.conversation_store import Superseded
            if data.get('foreground') or data.get('status', 'active') != 'active':
                raise Superseded()
        call = next(c for c in run['model_calls'] if c['id'] == call_id)
        budget = run['maintenance_budget' if background else 'execution_budget']
        remaining({'execution_budget': budget})
        # The first request is pre-reserved. An endpoint fallback is another
        # chargeable input even though it belongs to one logical model step.
        if call['transport_requests']:
            if budget['attempts'] >= MODEL_ATTEMPTS:
                raise RunBudgetError('BUDGET_CALLS')
            if budget['estimated_input_tokens'] + call['estimated_input_tokens'] > ESTIMATED_INPUT_LIMIT:
                raise RunBudgetError('BUDGET_INPUT')
            budget['attempts'] += 1
            budget['estimated_input_tokens'] += call['estimated_input_tokens']
        call['transport_requests'] += 1
        if call['usage'] and len(call['usage']) < call['transport_requests']:
            call['usage_state'] = 'partial'


def record(h, sid, rid, call_id, *, usage=None, status=None):
    # Accounting may arrive after cancellation; never revives a Run or emits
    # text/progress/learning. Deletion is authoritative and must stay deleted.
    if h.store.deleted(sid):
        return
    try:
        with h.store.transaction(sid) as data:
            run = data['runs'].get(rid)
            call = next((c for c in (run or {}).get('model_calls', []) if c['id'] == call_id), None)
            if call is None:
                return
            if usage is not None:
                identity = usage.get('response_id')
                if not identity or not any(u.get('response_id') == identity for u in call['usage']):
                    call['usage'].append(usage)
                call['usage_state'] = ('partial' if len(call['usage']) < call['transport_requests'] else 'reported')
            if status:
                call['status'] = status
    except ValueError as exc:
        if str(exc) != 'RT.SESSION.DELETED':
            raise
