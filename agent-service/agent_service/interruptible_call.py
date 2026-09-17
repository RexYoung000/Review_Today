"""Release orchestration promptly even when a synchronous socket ignores close.

Detached calls keep bounded slots until they really return. Revision checks still
fence their callbacks; detaching is not a promise of upstream billing cancellation.
"""
from contextvars import copy_context
import threading
import time

from agent_service.call_errors import ModelCallError


class CallPool:
    def __init__(self, limit=8, per_run=2):
        self.limit, self.per_run = limit, per_run
        self.lock = threading.Lock()
        self.active = {}

    def invoke(self, key, fn, *, check, budget):
        deadline = time.monotonic() + min(2, budget.remaining())
        while True:
            check()
            budget.remaining()
            with self.lock:
                if sum(self.active.values()) < self.limit and self.active.get(key, 0) < self.per_run:
                    self.active[key] = self.active.get(key, 0) + 1
                    break
            if time.monotonic() >= deadline:
                raise ModelCallError("BUSY", "bounded transport slots occupied")
            threading.Event().wait(.025)
        done = threading.Event()
        result = {}
        context = copy_context()

        def work():
            try:
                result['value'] = context.run(fn)
            except BaseException as exc:
                result['error'] = exc
            finally:
                with self.lock:
                    self.active[key] -= 1
                    if not self.active[key]:
                        del self.active[key]
                done.set()

        threading.Thread(target=work, daemon=True, name='review-today-model-transport').start()
        try:
            while not done.wait(.025):
                check()
                budget.remaining()
            check()
            if 'error' in result:
                raise result['error']
            return result['value']
        finally:
            if not done.is_set():
                budget.abandon()


pool = CallPool()
