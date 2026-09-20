"""Opt-in experiment engine using the real Harness budget, checkpoints and fences."""
from __future__ import annotations

import json
import time
from pathlib import Path
import tempfile

from agent_service import run_accounting
from agent_service.call_errors import ModelCallError
from agent_service.execution_policy import budget_scope
from agent_service.interruptible_call import pool
from agent_service.judgment_types import MODEL, VERSION, JudgmentResult, digest


class JudgmentEngine:
    def __init__(self, client, *, timeout=5, observer=None):
        if not 0 < timeout <= 5:
            raise ValueError("Jev timeout must be at most five seconds")
        self.client, self.timeout, self.observer = client, timeout, observer

    def check_isolation(self, store):
        # No production flag/env configuration in this phase. Explicit injection
        # additionally requires a database in the OS temporary directory.
        path = Path(store.tasks.path).resolve()
        if not any(path.is_relative_to(root.resolve()) for root in (Path(tempfile.gettempdir()), Path("/tmp"))):
            raise ValueError("Jev experiment requires a temporary database")

    def judge(self, h, sid, rid, rev, request):
        data, run = h._snapshot(sid, rid, rev)
        binding = dict(input_ids=run["input_ids"], revision=rev, mode=data["mode"],
                       lifecycle=data.get("lifecycle_revision", 0))
        identity = digest(dict(request=request.model_dump(), model=MODEL, binding=binding))
        cached = run.get("judgment_cache", {}).get(identity)
        if cached:
            result = JudgmentResult.model_validate(cached).model_copy(update={"cached": True})
            self._record(h, sid, rid, rev, request, result, identity, raw=None)
            return result
        result = JudgmentResult(node=request.node, version=request.version,
                                input_hash=identity, status="skipped", sources=request.sources)
        encoded = json.dumps(request.payload(), ensure_ascii=False)
        estimated = len(encoded.encode("utf-8"))  # conservative upper bound, not reported token usage
        budget = run.get("execution_budget", {})
        reason = ""
        if self.client.blocked.is_set():
            reason = "authentication_disabled"
        elif len(encoded) > 48000:
            reason = "input_too_large"
        elif (budget.get("attempts", 0) + 3 > run_accounting.MODEL_ATTEMPTS or
              budget.get("estimated_input_tokens", 0) + estimated * 2 > run_accounting.ESTIMATED_INPUT_LIMIT or
              run_accounting.remaining(run) <= self.timeout + 1):
            reason = "fallback_budget_reserved"
        if reason:
            result.reason = reason
            self._record(h, sid, rid, rev, request, result, identity, raw=None)
            return result
        call_id = run_accounting.reserve(h, sid, rid, rev, node="jev_" + request.node,
                                        model=MODEL, estimated_input=estimated)
        start = time.perf_counter()
        raw = None
        with budget_scope(seconds=min(self.timeout, run_accounting.remaining(run)), isolated=True, limit=1) as call_budget:
            def invoke():
                try:
                    value = self.client.call(request, timeout=call_budget.remaining(),
                        on_request=lambda: run_accounting.request(h, sid, rid, rev, call_id),
                        on_usage=lambda usage: run_accounting.record(h, sid, rid, call_id, usage=usage))
                    run_accounting.record(h, sid, rid, call_id, status="late_return" if call_budget.abandoned else value[0].status)
                    return value
                except BaseException:
                    run_accounting.record(h, sid, rid, call_id, status="failed_or_cancelled")
                    raise
            try:
                result, raw = pool.invoke((sid, rid), invoke,
                    check=lambda: h._snapshot(sid, rid, rev), budget=call_budget)
                result.input_hash = identity
            except ModelCallError as exc:
                # Superseded is deliberately NOT caught: cancellation cannot fall back.
                result.status, result.reason = "failed", "timeout" if exc.code.endswith("TIMEOUT") else "transport_unavailable"
                result.elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
                run_accounting.record(h, sid, rid, call_id, status=result.reason)
        h._snapshot(sid, rid, rev)
        if result.status in {"ok", "uncertain"}:
            with h.store.transaction(sid, rid, rev) as current:
                current["runs"][rid].setdefault("judgment_cache", {})[identity] = result.model_dump()
        self._record(h, sid, rid, rev, request, result, identity, raw=raw)
        return result

    def _record(self, h, sid, rid, rev, request, result, identity, raw):
        with h.store.transaction(sid, rid, rev) as data:
            data["runs"][rid].setdefault("judgments", []).append(result.model_dump())
            h.store.event(data, data["runs"][rid], "judgment", "局部判断已记录", model=MODEL,
                          duration_ms=int(result.elapsed_ms),
                          payload={"node": request.node, "status": result.status, "input_hash": identity})
        if self.observer:
            # Only the explicitly installed synthetic experiment recorder receives
            # original input/output. Normal checkpoints keep metadata and choices.
            self.observer(dict(session_id=sid, run_id=rid, revision=rev,
                               request=request.model_dump(), result=result.model_dump(), raw_response=raw))

    def disposition(self, h, sid, rid, rev, result, *, applied, reason="", field_decisions=None):
        if result is None:
            return
        # Keep transport/validation/uncertainty causes when a caller records
        # the subsequent LLM fallback; the fallback must not erase the fault.
        result.applied, result.reason = applied, result.reason or reason
        if field_decisions is not None:
            result.field_decisions = field_decisions
        fields = {k: v.model_dump() for k, v in result.field_decisions.items()}
        with h.store.transaction(sid, rid, rev) as data:
            records = data["runs"][rid].get("judgments", [])
            for item in reversed(records):
                if item["input_hash"] == result.input_hash:
                    item.update(applied=applied, reason=result.reason, field_decisions=fields)
                    break
        if self.observer:
            self.observer(dict(type="disposition", session_id=sid, run_id=rid, revision=rev,
                               input_hash=result.input_hash, applied=applied, reason=result.reason, field_decisions=fields))
