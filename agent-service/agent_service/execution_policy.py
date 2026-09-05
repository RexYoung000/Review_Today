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

    def remaining(self):
        from agent_service.openai_client import ModelCallError
        remaining = self.seconds - (time.monotonic() - self.started)
        if remaining <= 0 or self.expired:
            raise ModelCallError("TIMEOUT", "step deadline exceeded")
        return remaining

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

    def take(self):
        from agent_service.openai_client import ModelCallError
        if self.attempts >= self.limit:
            raise ModelCallError("ATTEMPTS_EXHAUSTED")
        remaining = self.remaining()
        self.attempts += 1
        return remaining


current_budget = ContextVar("review_today_attempt_budget", default=None)


@contextmanager
def budget_scope(seconds=MODEL_TIMEOUT_SECONDS):
    existing = current_budget.get()
    if existing:
        yield existing
        return
    budget = AttemptBudget(seconds=seconds)
    token = current_budget.set(budget)
    timer = threading.Timer(budget.seconds, lambda: budget.close(expired=True))
    timer.daemon = True
    timer.start()
    try:
        yield budget
    finally:
        timer.cancel()
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
