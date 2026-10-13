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
            transport_requests=0, request_ids=[], usage_state='unavailable', usage=[], status='started'))
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
        identity = str(uuid.uuid4())
        call.setdefault('request_ids', []).append(identity)
        call['usage_state'] = _usage_state(call)
        return identity


def _identity(value):
    return value if isinstance(value, str) and value.strip() else None


def _same_request(left, right, requests):
    left_id, right_id = _identity(left.get('request_id')), _identity(right.get('request_id'))
    if left_id and right_id:
        return left_id == right_id
    # Legacy identified receipts retain their original deduplication. Never
    # merge two newly identified requests just because the supplier reused ID.
    left_response, right_response = _identity(left.get('response_id')), _identity(right.get('response_id'))
    if requests == 1:
        return True  # The single admitted request has unambiguous ownership.
    return bool(not left_id and not right_id and left_response and left_response == right_response)


def _usage_state(call):
    rows = call['usage']
    known = lambda value: type(value) is int and value >= 0
    if not any(known(row.get(key)) for row in rows for key in ('input_tokens', 'output_tokens')):
        return 'unavailable'
    if (len(rows) != max(1, call['transport_requests'])
            or not all(known(row.get(key)) for row in rows for key in ('input_tokens', 'output_tokens'))):
        return 'partial'
    identities = call.get('request_ids', [])
    if identities:
        if (len(identities) != call['transport_requests']
                or {_identity(row.get('request_id')) for row in rows} != set(identities)):
            return 'partial'
    elif call['transport_requests'] > 1 and any(not _identity(row.get('response_id')) for row in rows):
        return 'partial'  # Do not infer the identity of anonymous legacy requests.
    return 'reported'


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
                incoming = dict(usage)
                identities = call.get('request_ids', [])
                if not _identity(incoming.get('request_id')) and call['transport_requests'] == len(identities) == 1:
                    incoming['request_id'] = identities[0]
                existing = next((row for row in call['usage']
                                 if _same_request(row, incoming, call['transport_requests'])), None)
                if existing is None:
                    call['usage'].append(incoming)
                else:
                    # A later receipt supplements or corrects this request;
                    # omitted values must not erase already known measurements.
                    existing.update({key: value for key, value in incoming.items() if value is not None})
                call['usage_state'] = _usage_state(call)
            if status:
                call['status'] = status
    except ValueError as exc:
        if str(exc) != 'RT.SESSION.DELETED':
            raise
