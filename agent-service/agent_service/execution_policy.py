"""One finite budget shared by compatible endpoints and approved fallback calls."""
import time
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from agent_service.config import MODEL_TIMEOUT_SECONDS


@dataclass
class AttemptBudget:
    limit: int = 2
    seconds: float = MODEL_TIMEOUT_SECONDS
    attempts: int = 0
    started: float = field(default_factory=time.monotonic)
    closers: list = field(default_factory=list)
    expired: bool = False
    abandoned: bool = False
    first_output_seconds: float | None = None
    idle_seconds: float | None = None
    last_output: float | None = None
    wake: threading.Event = field(default_factory=threading.Event, repr=False)

    def remaining(self):
        from agent_service.call_errors import ModelCallError
        now = time.monotonic()
        remaining = self.seconds - (now - self.started)
        reason = "step deadline exceeded"
        if self.first_output_seconds is not None:
            output_deadline = (self.started + self.first_output_seconds if self.last_output is None
                               else self.last_output + self.idle_seconds)
            if output_deadline - now < remaining:
                remaining = output_deadline - now
                reason = "first output deadline exceeded" if self.last_output is None else "stream idle deadline exceeded"
        if remaining <= 0 or self.expired:
            raise ModelCallError("TIMEOUT", reason)
        return remaining

    def output_progress(self):
        # A late chunk cannot resurrect an expired or cancelled generation.
        self.remaining()
        self.last_output = time.monotonic()
        self.wake.set()

    def register(self, close):
        self.closers.append(close)
        if self.expired:
            close()
            self.remaining()

    def close(self, expired=False):
        self.expired = self.expired or expired
        for close in list(self.closers):
            try: close()
            except Exception: pass  # cancellation must not conceal the original error

    def abandon(self):
        # A close callback itself can block. Leave it with the detached request,
        # never on the Session worker that must process stop/steering.
        self.abandoned = True
        self.expired = True
        threading.Thread(target=self.close, daemon=True, name='review-today-close').start()

    def take(self):
        from agent_service.call_errors import ModelCallError
        if self.attempts >= self.limit:
            raise ModelCallError("ATTEMPTS_EXHAUSTED")
        remaining = self.remaining()
        self.attempts += 1
        return remaining


current_budget = ContextVar("review_today_attempt_budget", default=None)


@contextmanager
def budget_scope(seconds=MODEL_TIMEOUT_SECONDS, *, limit=2, isolated=False,
                 first_output_seconds=None, idle_seconds=None):
    existing = current_budget.get()
    if existing and not isolated:
        yield existing
        return
    budget = AttemptBudget(seconds=seconds, limit=limit,
                           first_output_seconds=first_output_seconds, idle_seconds=idle_seconds)
    token = current_budget.set(budget)
    finished = threading.Event()
    def watch():
        from agent_service.call_errors import ModelCallError
        while not finished.is_set():
            try:
                delay = budget.remaining()
            except ModelCallError:
                if not finished.is_set():
                    budget.close(expired=True)
                return
            budget.wake.wait(delay)
            budget.wake.clear()
    threading.Thread(target=watch, daemon=True, name='review-today-model-deadline').start()
    try:
        yield budget
    finally:
        finished.set()
        budget.wake.set()
        if not budget.abandoned:
            budget.close()
        current_budget.reset(token)


@dataclass(frozen=True)
class ApprovedAlternative:
    model: str
    strengths: frozenset[str]
    structured: bool
    streaming: bool
    same_data_boundary: bool
    verified: bool


# Deliberately empty. Configuration/verification is separate authorization;
# adding this engine does not approve a supplier or a different model.
APPROVED_ALTERNATIVES: dict[str, tuple[ApprovedAlternative, ...]] = {}


def alternatives(primary, strength, streaming):
    return [value.model for value in APPROVED_ALTERNATIVES.get(primary, ())
            if value.verified and value.same_data_boundary and value.structured
            and (not streaming or value.streaming) and strength in value.strengths and value.model != primary]
