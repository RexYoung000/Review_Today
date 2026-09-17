"""Finite, cancellable provider failover. No model calls or credential logging."""
import hashlib
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from agent_service.call_errors import CallError, WebToolError
from agent_service.execution_policy import budget_scope

ROUND_SECONDS = 60
ROUND_CALLS = 10
CHAIN_SECONDS = 30
PROVIDER_SECONDS = 12
QUEUE_SECONDS = 2


@dataclass
class WebRound:
    spent: float = 0
    calls: int = 0
    on_event: object = None
    check_cancel: object = None

    def check(self):
        if self.check_cancel:
            self.check_cancel()
        if self.spent >= ROUND_SECONDS or self.calls >= ROUND_CALLS:
            raise WebToolError('BUDGET_EXHAUSTED')


active_round = ContextVar('web_round', default=None)


@contextmanager
def web_round_scope(*, on_event=None, check_cancel=None):
    if active_round.get() is not None:
        yield active_round.get()
        return
    state = WebRound(on_event=on_event, check_cancel=check_cancel)
    token = active_round.set(state)
    try:
        yield state
    finally:
        active_round.reset(token)


@dataclass
class ProviderState:
    slot: threading.Lock = field(default_factory=threading.Lock)
    until: float = 0
    next_start: float = 0
    reason: str = ''


_states = {}
_states_lock = threading.Lock()


def provider_state(provider):
    # Configuration changes select a new state, but neither keys nor hashes leave memory.
    config = '|'.join([provider, os.getenv(provider.upper() + '_API_KEY', ''),
                       os.getenv('REVIEW_TODAY_TAVILY_KEYLESS', '')])
    key = hashlib.sha256(config.encode()).digest()
    with _states_lock:
        return _states.setdefault(key, ProviderState())


def emit(state, provider, operation, status, code=''):
    if state.on_event:
        state.on_event(dict(provider=provider, operation=operation, status=status, code=code))


def cooldown(error):
    kind = error.code.rsplit('.', 1)[-1]
    diagnostic = getattr(error, 'diagnostic', '')
    if kind == 'RATE_LIMIT' or diagnostic == 'HTTP 429':
        return getattr(error, 'retry_after', None) or 300
    if kind in {'AUTH_REQUIRED', 'NO_KEY'} or diagnostic in {'HTTP 401', 'HTTP 403'}:
        return 3600
    if kind in {'TIMEOUT', 'CONNECTION', 'PROTOCOL', 'INCOMPLETE', 'TOOL_FAILED'} or diagnostic.startswith('HTTP 5'):
        return 30
    return 0


def route(providers, operation, invoke, *, on_cancel_handle=None):
    """Each enabled provider tried once; no secondary model/endpoint retry loop."""
    cancelled = threading.Event()
    callbacks, callback_lock = [], threading.Lock()

    def cancel():
        cancelled.set()
        with callback_lock:
            closers = list(callbacks)
        for close in closers:
            try: close()
            except Exception: pass

    def register(close):
        with callback_lock:
            callbacks.append(close)
        if cancelled.is_set():
            close()
            raise WebToolError('CANCELLED')

    if on_cancel_handle:
        on_cancel_handle(cancel)
    with web_round_scope() as state:
        started = time.monotonic()
        deadline = started + min(CHAIN_SECONDS, ROUND_SECONDS - state.spent)
        empty_result = None
        empty_searches = 0
        last_error = WebToolError('NOT_CONFIGURED')

        def check():
            if cancelled.is_set(): raise WebToolError('CANCELLED')
            state.check()
            if time.monotonic() >= deadline: raise WebToolError('BUDGET_EXHAUSTED')

        try:
            for provider in providers:
                check()
                shared = provider_state(provider)
                if shared.until > time.monotonic():
                    emit(state, provider, operation, 'skipped', shared.reason)
                    continue
                # Health/configuration checks do not consume requests or queue slots.
                try:
                    backend = invoke(provider, None, None)
                except WebToolError as error:
                    emit(state, provider, operation, 'skipped', error.code)
                    last_error = error
                    continue
                acquired = False
                try:
                    queue_deadline = min(deadline, time.monotonic() + QUEUE_SECONDS)
                    while not shared.slot.acquire(timeout=.05):
                        check()
                        if time.monotonic() >= queue_deadline:
                            break
                    else:
                        acquired = True
                    if not acquired:
                        emit(state, provider, operation, 'skipped', 'RT.WEB.BUSY')
                        continue
                    check()
                    if shared.until > time.monotonic():
                        emit(state, provider, operation, 'skipped', shared.reason)
                        continue
                    while time.monotonic() < shared.next_start:
                        check()
                        cancelled.wait(min(.05, max(0, shared.next_start - time.monotonic())))
                    check()
                    state.calls += 1
                    shared.next_start = time.monotonic() + (.55 if provider == 'exa' else .1)
                    emit(state, provider, operation, 'started')
                    try:
                        with budget_scope(seconds=min(PROVIDER_SECONDS, deadline - time.monotonic()), limit=1, isolated=True):
                            result = invoke(provider, backend, register)
                        if cancelled.is_set(): raise WebToolError('CANCELLED')
                        if state.check_cancel: state.check_cancel()
                        if time.monotonic() >= deadline: raise WebToolError('BUDGET_EXHAUSTED')
                        if operation in {'search', 'context'} and not result:
                            emit(state, provider, operation, 'empty')
                            empty_result = (provider, result)
                            empty_searches += 1
                            if empty_searches >= 2: return empty_result
                            continue
                        emit(state, provider, operation, 'succeeded')
                        return provider, result
                    except CallError as error:
                        if cancelled.is_set(): raise WebToolError('CANCELLED') from None
                        if state.check_cancel: state.check_cancel()
                        if error.code.endswith(('CANCELLED', 'INVALID_QUERY', 'BUDGET_EXHAUSTED')): raise
                        last_error = error
                        wait = cooldown(error)
                        if wait:
                            shared.until = time.monotonic() + wait
                            shared.reason = error.code
                        emit(state, provider, operation, 'failed', error.code)
                finally:
                    if acquired: shared.slot.release()
            if empty_result is not None:
                return empty_result
            error = WebToolError('CHAIN_FAILED', last_error.code)
            raise error
        finally:
            state.spent += time.monotonic() - started


def bounded_web_round(function):
    from functools import wraps
    @wraps(function)
    def wrapped(*args, **kwargs):
        with web_round_scope():
            return function(*args, **kwargs)
    return wrapped
