"""Five-mode conversation harness. Semantic proposals never directly authorize writes.

Network calls run outside transactions. Every checkpoint/publication is fenced by
the run revision, including Task projections consumed by the old Mac ACK path.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pydantic import ValidationError

from agent_service.capture import RISK_RULE, find_source_candidates, run_capture
from agent_service.capture.fetch import fetch_public_url, looks_like_url
from agent_service.config import COACH_MODEL, RISK_MODEL, ROUTER_MODEL
from agent_service.conversation_prompts import COACH_SYSTEM, EVALUATION_SYSTEM, INTENT_SYSTEM
from agent_service.conversation_store import ConversationStore, Superseded, conversation_store
from agent_service.harness import JD_SYSTEM, PROBLEM_SYSTEM, _render_problem
from agent_service.harness_store import HarnessTaskRecord, now_iso
from agent_service.openai_client import ModelCallError, parse_model, web_search_text
from agent_service.model_capabilities import require_model
from agent_service.service_diagnostics import diagnose
from agent_service.learning_progress import set_plan, current_step, record_understanding, advance, outcome
from agent_service.learning_memory import make_evidence, select_references, merge_references
from agent_service.execution_policy import budget_scope, alternatives
from agent_service.context_budget import prepare as prepare_context, configured_window
from agent_service.response_projection import public_preview
from agent_service.schemas import (
    ConversationOutput, EvidenceAssessmentV2, IntentDecision, JDAnalysis, MasteryEvaluation,
    MessageAccepted, ProblemCoachBundle, RunActionRequest, SessionMessageRequest, TaskEvent, ConversationSummary,
)

LABELS = {"auto": "Auto", "memory_organization": "知识整理", "source_learning": "资料学习",
          "topic_exploration": "主题探索", "problem_solving": "问题攻克"}
FINISHED = {"completed", "cancelled", "terminal_failed"}


def _new_run(session_id: str, message_id: str, status: str) -> dict:
    return dict(run_id=str(uuid.uuid4()), session_id=session_id, task_id=None, input_ids=[message_id],
                revision=1, status=status, stage="accepted", user_summary="已保存", attempt=0,
                intent=None, steps={}, action_ids=[], error_code=None, created_at=now_iso(), updated_at=now_iso(),
                started_at=None, elapsed_ms=0, attempt_durations=[], first_text_ms=None,
                activity_candidate=None, activity_kind=None, completed_at=None)


class ConversationHarness:
    def __init__(self, store: ConversationStore = conversation_store):
        self.store = store
        self._workers: set[str] = set()
        self._worker_lock = threading.Lock()
        self._cancel_handles: dict[tuple, object] = {}
        self._summary_workers: set[str] = set()

    def accept(self, session_id: str, body: SessionMessageRequest) -> MessageAccepted:
        with self.store.transaction(session_id) as data:
            if body.expected_event_seq and self.store.last_seq(data) < body.expected_event_seq:
                raise ValueError("RT.SESSION.CHECKPOINT_REQUIRED")
            if body.lifecycle_revision is not None and body.lifecycle_revision != data.get("lifecycle_revision", 0):
                raise ValueError("RT.SESSION.VERSION_CONFLICT")
            if data.get("status", "active") != "active":
                raise ValueError("RT.SESSION.ARCHIVED")
            receipts = data.setdefault("message_receipts", {})
            fingerprint = hashlib.sha256(json.dumps(dict(content=body.content, operation=body.operation.model_dump() if body.operation else None), sort_keys=True).encode()).hexdigest()
            receipt = receipts.get(body.client_message_id)
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise ValueError("RT.MESSAGE.IDEMPOTENCY_CONFLICT")
                run = data["runs"][receipt["run_id"]]
                return MessageAccepted(message_id=body.client_message_id, run_id=run["run_id"], task_id=run.get("task_id"), status=run["status"], revision=run["revision"])
            existing = next((m for m in data["messages"] if m.get("message_id") == body.client_message_id), None)
            if existing:
                # Same key with a different payload is not a second user instruction.
                if existing["content"] != body.content:
                    raise ValueError("RT.MESSAGE.IDEMPOTENCY_CONFLICT")
                run = data["runs"][existing["run_id"]]
            else:
                for invalid_id in body.context.invalid_memory_run_ids:
                    if invalid_id in data["runs"]:
                        data["runs"][invalid_id]["memory_invalidated"] = True
                self._invalidate_memory(data)
                if body.task_id:
                    task = data["tasks"].get(body.task_id)
                    if not task or task["session_id"] != session_id:
                        raise ValueError("RT.TASK.SESSION_MISMATCH")
                    data["active_task_id"] = body.task_id
                    task["context"]["conversation_managed"] = True
                    task["context"].setdefault("understanding", "unknown")
                    task["context"].setdefault("requires_mastery", task["mode"] == "problem_solving")
                # First message supplies the local Session preset. Subsequent changes
                # are explicit set_mode actions, never incidental stale submit fields.
                if not data["runs"]:
                    data["mode"] = body.mode_preset
                    data["thinking_strength"] = body.thinking_strength or "smart"
                active = data["runs"].get(data["foreground"])
                if active and active["status"] in {"running", "accepted"} and not active.get("execution_complete") and body.delivery == "steer":
                    run = active
                    self._end_response(data, run, "interrupted")
                    run["revision"] += 1
                    run["status"] = "accepted"
                    run["input_ids"].append(body.client_message_id)
                    summary = "已收到补充，正在调整"
                else:
                    paused_entry = data["paused"] and body.delivery == "steer"
                    run = _new_run(session_id, body.client_message_id, "queued" if active or (data["paused"] and not paused_entry) else "accepted")
                    run["paused_entry"] = paused_entry
                    data["runs"][run["run_id"]] = run
                    if not data["foreground"] and (not data["paused"] or paused_entry):
                        data["foreground"] = run["run_id"]
                    summary = "排队中" if run["status"] == "queued" else "已保存，准备回应"
                message = dict(message_id=body.client_message_id, role="user", content=body.content,
                               content_type=body.content_type, created_at=now_iso(), run_id=run["run_id"],
                               task_id=body.task_id, context=body.context.model_dump(),
                               operation=body.operation.model_dump() if body.operation else None)
                data["messages"].append(message)
                run["lifecycle_revision"] = data.get("lifecycle_revision", 0)
                if body.task_id:
                    data["tasks"][body.task_id]["context"]["latest_run_id"] = run["run_id"]
                receipts[body.client_message_id] = dict(fingerprint=fingerprint, run_id=run["run_id"])
                committing = data["tasks"].get(data["active_task_id"])
                if body.delivery == "steer" and committing and committing["status"] == "committing" and not committing["context"].get("commit_claimed"):
                    # Pause the write BEFORE intent inference. Otherwise the Mac
                    # could commit while "不要保存" is still waiting on the model.
                    committing["context"]["held_commit"] = committing["memory_package"]
                    committing["memory_package"] = None
                    committing.update(status="awaiting_user", stage="commit_held", user_summary="收到补充，已暂停尚未提交的入库")
                    if data.get("draft"):
                        data["pending"] = dict(kind="save", target_id=data["draft"]["id"], version=data["draft"]["version"])
                    self._project_event(data, run, committing)
                self.store.event(data, run, "queued" if run["status"] == "queued" else "received", summary)
            accepted = MessageAccepted(message_id=body.client_message_id, run_id=run["run_id"],
                                       task_id=run.get("task_id"), status=run["status"], revision=run["revision"])
        self._cancel_older(session_id, accepted.run_id, accepted.revision)
        return accepted

    def action(self, run_id: str, body: RunActionRequest) -> dict:
        found = self.store.locate_run(run_id)
        if not found:
            raise ValueError("RT.RUN.UNKNOWN")
        with self.store.transaction(found["session_id"]) as data:
            if data.get("status", "active") != "active":
                raise ValueError("RT.SESSION.ARCHIVED")
            run = data["runs"][run_id]
            action_fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
            prior_action = run.setdefault("action_receipts", {}).get(body.action_id)
            if prior_action is not None and prior_action != action_fingerprint:
                raise ValueError("RT.RUN.IDEMPOTENCY_CONFLICT")
            if body.action_id in run["action_ids"]:
                return dict(run)
            run["action_ids"].append(body.action_id)
            run["action_receipts"][body.action_id] = action_fingerprint
            # Controls address the foreground when sent from an older completed run.
            target = data["runs"].get(data["foreground"]) or run
            if body.action == "set_mode":
                if body.mode not in LABELS:
                    raise ValueError("RT.MODE.INVALID")
                data["mode"] = body.mode
                task = data["tasks"].get(data["active_task_id"])
                if task:
                    task["mode_preset"] = body.mode
                    task["context"]["mode_changed"] = True
                    if body.mode != "auto":
                        task["mode"] = body.mode
                if target["status"] in {"running", "accepted"}:
                    self._end_response(data, target, "interrupted")
                    target["revision"] += 1
                    target["status"] = "accepted"
                self.store.event(data, target, "mode_changed", f"已选择{LABELS[body.mode]}，从下一步生效")
            elif body.action == "set_thinking":
                if body.thinking_strength not in {"smart", "deep"}:
                    raise ValueError("RT.THINKING.INVALID")
                data["thinking_strength"] = body.thinking_strength
                target["thinking_strength"] = body.thinking_strength
                if target["status"] in {"running", "accepted"}:
                    self._end_response(data, target, "interrupted")
                    target["revision"] += 1
                    target["status"] = "accepted"
                self.store.event(data, target, "thinking_changed", "思考强度已保存，从下一步生效")
            elif body.action in {"stop", "cancel_task"}:
                if body.action == "cancel_task" and run.get("task_id") != data["active_task_id"]:
                    task = data["tasks"].get(run.get("task_id"))
                    if task and not task["context"].get("commit_claimed"):
                        task.update(status="cancelled", stage="cancelled", user_summary="此学习目标已取消，历史保留", memory_package=None)
                        self._project_event(data, run, task)
                else:
                    self._stop(data, target, cancel=body.action == "cancel_task")
            else:
                if body.action == "retry" and run["status"] not in {"retryable_failed", "terminal_failed"}:
                    raise ValueError("RT.RUN.NOT_RETRYABLE")
                if target["status"] == "running":
                    raise ValueError("RT.RUN.ALREADY_RUNNING")
                data["paused"] = False
                if run.get("control_only"):
                    run["status"] = "completed"
                if run["status"] in {"interrupted", "retryable_failed", "terminal_failed", "queued"}:
                    run["revision"] += 1
                    run["lifecycle_revision"] = data.get("lifecycle_revision", 0)
                    run["status"] = "accepted"
                    data["foreground"] = run_id
                self.store.event(data, run, "resuming", "已恢复，将从未完成的步骤继续")
            result = dict(run)
        self._cancel_older(found["session_id"], target["run_id"], target["revision"])
        return result

    def session_action(self, sid, action_id, action, lifecycle_revision):
        if action not in {"archive", "restore"} or lifecycle_revision < 1:
            raise ValueError("RT.SESSION.INVALID_ACTION")
        cancelled = []
        with self.store.transaction(sid) as data:
            receipt = dict(action=action, revision=lifecycle_revision)
            receipts = data.setdefault("lifecycle_actions", {})
            if action_id in receipts:
                if receipts[action_id] != receipt:
                    raise ValueError("RT.SESSION.IDEMPOTENCY_CONFLICT")
                return dict(status=data.get("status", "active"), lifecycle_revision=data.get("lifecycle_revision", 0))
            if lifecycle_revision <= data.get("lifecycle_revision", 0):
                raise ValueError("RT.SESSION.VERSION_CONFLICT")
            data["lifecycle_revision"] = lifecycle_revision
            data["status"] = "archived" if action == "archive" else "active"
            data["paused"] = True
            data["pending"] = None
            if data.get("draft"):
                data["draft"]["invalidated"] = True
            for run in data["runs"].values():
                if run["status"] in {"running", "accepted", "queued"}:
                    self._stop(data, run)
                    cancelled.append((run["run_id"], run["revision"]))
            data["foreground"] = None
            for task in data["tasks"].values():
                if task["status"] not in FINISHED and not task["context"].get("commit_claimed"):
                    task.update(status="awaiting_user", stage="stopped", memory_package=None,
                                required_action=None, user_summary="已暂停，历史和进度保留")
            receipts[action_id] = receipt
        for rid, rev in cancelled:
            self._cancel_older(sid, rid, rev)
        return dict(status=data["status"], lifecycle_revision=lifecycle_revision)

    def memory_policy(self, sid, *, allowed, policy_version, content_version):
        cancelled = []
        with self.store._lock:
            self.store.set_memory_policy(sid, dict(allowed=allowed, policy_version=policy_version, content_version=content_version))
            for owner in self.store.sessions():
                existing = self.store.get(owner)
                if not any(not self.store.memory_valid(r.get("memory_references", [])) for r in existing["runs"].values()):
                    continue
                with self.store.transaction(owner) as data:
                    self._invalidate_memory(data)
                    for run in data["runs"].values():
                        if not self.store.memory_valid(run.get("memory_references", [])) and run["status"] in {"running", "accepted", "queued"}:
                            self._stop(data, run)
                            cancelled.append((owner, run["run_id"], run["revision"]))
        for owner, rid, revision in cancelled:
            self._cancel_older(owner, rid, revision)
        return dict(status="saved", policy_version=policy_version, content_version=content_version)

    def _memory_run_valid(self, run):
        return not run.get("memory_invalidated") and self.store.memory_valid(run.get("memory_references", []))

    def _invalidate_memory(self, data):
        invalid = [r for r in data["runs"].values() if not self._memory_run_valid(r) and not r.get("memory_invalidation_applied")]
        if not invalid:
            return
        data["summary"] = ""
        data["summary_memory_references"] = []
        data["summary_invalidated"] = True
        data["summary_version"] += 1
        data["pending"] = None
        invalid_ids = {r["run_id"] for r in invalid}
        for run in invalid:
            run["memory_invalidated"] = True
            run["memory_invalidation_applied"] = True
        for task in data["tasks"].values():
            ctx = task["context"]
            if ctx.get("latest_run_id") in invalid_ids or not self.store.memory_valid(ctx.get("memory_references", [])):
                ctx["memory_invalidated"] = True
                task["required_action"] = None
                if task["status"] != "completed":
                    task.update(status="awaiting_user", stage="memory_updated", memory_package=None,
                                user_summary="关联学习内容已更新，需要重新明确学习依据")
        if data.get("draft") and (not self.store.memory_valid(data["draft"].get("memory_references", [])) or
                                 data["tasks"].get(data["draft"].get("id"), {}).get("context", {}).get("memory_invalidated")):
            data["draft"]["invalidated"] = True

    def export_snapshot(self, sid):
        data = self.store.get(sid)
        if data is None:
            raise ValueError("RT.SESSION.UNKNOWN")
        from agent_service.checkpoint_delta import recovery_projection
        return dict(schema_version=1, session_id=sid, checkpoint=recovery_projection(data),
                    recovery_version=data.get("recovery_version", 0))

    def restore_snapshot(self, sid, snapshot):
        if snapshot.get("schema_version") != 1 or snapshot.get("session_id") != sid:
            raise ValueError("RT.SESSION.SNAPSHOT_INVALID")
        incoming = json.loads(json.dumps(snapshot.get("checkpoint", {})))
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        if incoming.get("session_id") != sid or not isinstance(incoming.get("runs"), dict):
            raise ValueError("RT.SESSION.SNAPSHOT_INVALID")
        # Serialized with the store lock, including the absence check.
        with self.store._lock:
            existing = self.store.get(sid)
            if existing and existing.get("restore_fingerprint") == fingerprint:
                return self.export_snapshot(sid)
            if existing is not None:
                raise ValueError("RT.SESSION.SNAPSHOT_EXISTS")
            for task in incoming.get("tasks", {}).values():
                if task.get("session_id") != sid:
                    raise ValueError("RT.SESSION.SNAPSHOT_INVALID")
                HarnessTaskRecord(**task)  # validate shape before any write
                if task.get("status") == "committing":
                    task.update(status="awaiting_user", stage="stopped", memory_package=None, required_action=None)
                    task["context"].pop("commit_claimed", None)
            for run in incoming["runs"].values():
                if run.get("session_id") != sid:
                    raise ValueError("RT.SESSION.SNAPSHOT_INVALID")
                run.setdefault("steps", {})
                run.setdefault("action_ids", [])
                if run["status"] not in {"completed", "cancelled", "terminal_failed", "retryable_failed"}:
                    run.update(status="interrupted", started_at=None, revision=run["revision"] + 1)
            incoming.update(foreground=None, paused=True, pending=None, restore_fingerprint=fingerprint)
            if incoming.get("draft"):
                incoming["draft"]["invalidated"] = True
            with self.store.transaction(sid) as data:
                data.update(incoming)
        return self.export_snapshot(sid)

    def _cancel_older(self, sid, rid, revision):
        with self._worker_lock:
            handles = [handle for key, handle in self._cancel_handles.items() if key[:2] == (sid, rid) and key[2] != revision]
        for handle in handles:
            # Closing a transport can block; never delay the durable control ACK.
            def close(callback=handle):
                try: callback()
                except Exception: pass
            threading.Thread(target=close, daemon=True).start()

    def _stop(self, data: dict, run: dict, *, cancel: bool = False):
        already_replied = run["status"] == "completed"
        self._end_response(data, run, "interrupted")
        self._freeze_clock(run)
        run["revision"] += 1
        run["status"] = "completed" if already_replied else "interrupted"
        if already_replied:
            run["control_only"] = True
        data["paused"] = True
        data["foreground"] = None
        task = data["tasks"].get(data["active_task_id"])
        if task and task["status"] not in FINISHED:
            # Unclaimed output can still be revoked. A Mac commit claim is the
            # documented atomic boundary: already-committed data is not rolled back.
            if not task["context"].get("commit_claimed"):
                task["status"] = "cancelled" if cancel else "awaiting_user"
                task["stage"] = "cancelled" if cancel else "stopped"
                task["user_summary"] = "目标已取消" if cancel else "已停止回复，目标与进度保留"
                task["memory_package"] = None
                if cancel:
                    data["active_task_id"] = None
                self._project_event(data, run, task)
        self.store.event(data, run, "cancelled" if cancel else "stopped",
                         "目标已取消，历史已保留" if cancel else "本轮已结束，队列已暂停" if already_replied else "已停止回复；目标与进度保留，队列已暂停")

    def start(self, session_id: str):
        from agent_service.model_capabilities import snapshot
        data = self.store.get(session_id)
        if not data or data.get("status", "active") != "active":
            return
        foreground = data["runs"].get(data.get("foreground"))
        if data.get("paused") and not (foreground and foreground.get("paused_entry") and foreground["status"] == "accepted"):
            return
        if not any(r["status"] in {"accepted", "queued"} for r in data["runs"].values()):
            return
        candidate = foreground if foreground and foreground["status"] in {"accepted", "queued"} else next(r for r in data["runs"].values() if r["status"] in {"accepted", "queued"})
        last = next((m for m in data["messages"] if m["message_id"] == candidate["input_ids"][-1]), {})
        cached_intent = candidate.get("intent") and candidate.get("decision_input_ids") == candidate["input_ids"] and candidate.get("decision_mode") == data["mode"]
        if not last.get("operation") and not cached_intent and snapshot()["router"]["status"] != "ready":
            return
        with self._worker_lock:
            if session_id in self._workers:
                return
            self._workers.add(session_id)
        threading.Thread(target=self._worker, args=(session_id,), daemon=True,
                         name=f"review-today-session-{session_id[:8]}").start()

    def _worker(self, session_id: str):
        try:
            self.drain(session_id)
        finally:
            with self._worker_lock:
                self._workers.discard(session_id)
            data = self.store.get(session_id)
            if data and not data["paused"] and any(r["status"] in {"accepted", "queued"} for r in data["runs"].values()):
                self.start(session_id)  # closes the submit/worker-exit race
            self._schedule_summary(session_id)

    def recover(self):
        for session_id in self.store.sessions():
            with self.store.transaction(session_id) as data:
                for run in data["runs"].values():
                    if run["status"] == "running":
                        if run.get("execution_complete"):
                            self._freeze_clock(run)
                            run["status"] = "completed"
                            data["foreground"] = None
                        else:
                            self._stop(data, run)
                            self.store.event(data, run, "interrupted", "服务中断，内容已保留；请手动重试未完成步骤")
            self.start(session_id)

    def drain(self, session_id: str):
        """Synchronous worker entry for deterministic tests; one worker per Session."""
        while True:
            with self.store.transaction(session_id) as data:
                if data.get("status", "active") != "active":
                    return
                run = data["runs"].get(data["foreground"])
                if data["paused"] and not (run and run.get("paused_entry") and run["status"] == "accepted"):
                    return
                if not run or run["status"] not in {"accepted", "queued"}:
                    run = next((r for r in data["runs"].values() if r["status"] in {"accepted", "queued"}), None)
                if not run:
                    return
                data["foreground"] = run["run_id"]
                run["status"] = "running"
                run["thinking_strength"] = data.get("thinking_strength", "smart")
                run["attempt"] += 1
                if not run.get("started_at"):
                    run.update(started_at=now_iso(), elapsed_ms=0, first_text_ms=None)
                run_id, revision = run["run_id"], run["revision"]
                bound_input = next((m.get("operation") for m in data["messages"] if m["message_id"] == run["input_ids"][-1]), None)
                self.store.event(data, run, "understanding", "正在校验这次明确操作" if bound_input else "正在理解本轮意图", model="" if bound_input else ROUTER_MODEL)
            try:
                if not run.get("execution_complete"):
                    self._execute(session_id, run_id, revision)
                    with self.store.transaction(session_id, run_id, revision) as data:
                        data["runs"][run_id]["execution_complete"] = True
                with self.store.transaction(session_id, run_id, revision) as data:
                    run = data["runs"][run_id]
                    for task in data["tasks"].values():
                        held = task["context"].get("held_commit")
                        if not held:
                            continue
                        intents = set((run.get("intent") or {}).get("intents", []))
                        last_input = next((m["content"] for m in data["messages"] if m["message_id"] == run["input_ids"][-1]), "")
                        operations = (run.get("intent") or {}).get("proposed_actions", [])
                        uncertain_write = any(op["kind"] == "save" and (op["disposition"] not in {"confirm", "request"} or not self._explicit(op, last_input)) for op in operations)
                        if intents & {"reject", "correction", "stop", "pause", "cancel"} or uncertain_write:
                            task["context"].pop("held_commit", None)
                            task.update(status="cancelled", stage="save_cancelled", user_summary="未提交的入库已取消，草稿保留")
                        elif task["stage"] == "commit_held" and not (run.get("intent") or {}).get("clarification"):
                            task["memory_package"] = task["context"].pop("held_commit")
                            task.update(status="committing", stage="committing", user_summary="已回应补充，继续原先确认的入库")
                            task["context"].update(origin_run_id=run_id, commit_revision=revision)
                            data["pending"] = None
                        self._project_event(data, run, task)
                    self._freeze_clock(run)
                    run["status"] = "completed"
                    run["activity_kind"] = self._activity_kind(data, run)
                    run["completed_at"] = now_iso() if run["activity_kind"] else None
                    reply = next((m for m in reversed(data["messages"]) if m.get("run_id") == run_id and m["role"] == "coach"), None)
                    evidence = make_evidence(run, self._task(data, run), reply["message_id"], reply["content"], session_id) if reply else None
                    if evidence:
                        self.store.event(data, run, "learning_evidence", "学习记录已更新", payload={"learning_evidence": evidence})
                    self.store.event(data, run, "completed", "本轮已回应")
                    data["foreground"] = None
            except Superseded:
                with self.store.transaction(session_id) as data:
                    obsolete = data["runs"].get(run_id)
                    if obsolete and obsolete["revision"] == revision and obsolete["status"] == "running" and not self._memory_run_valid(obsolete):
                        self._stop(data, obsolete)
                continue
            except Exception as exc:  # each failure is persisted, not swallowed as a blank UI
                try:
                    with self.store.transaction(session_id, run_id, revision) as data:
                        run = data["runs"][run_id]
                        code = exc.code if isinstance(exc, ModelCallError) else (
                            str(exc) if str(exc).startswith("RT.") else "RT.RUN.EXECUTION_FAILED")
                        if code == "RT.PLAN.INVALID_STEP_REFERENCE":
                            run["steps"] = {key: value for key, value in run["steps"].items() if not isinstance(value, dict) or "learning_plan" not in value}
                        self._end_response(data, run, "failed")
                        self._freeze_clock(run)
                        run["status"] = "retryable_failed"
                        task = self._task(data, run)
                        if task and task["status"] not in FINISHED | {"committing"}:
                            task.update(status="retryable_failed", user_summary="当前步骤未完成，可重试；学习进度保留", error_code=code)
                            self._project_event(data, run, task)
                        summary = "当前内容超过可处理的上下文容量，请缩小本次范围；输入已保留" if code.startswith("RT.CONTEXT.") else "这一步暂时无法完成，可重试；输入和进度已保留"
                        self.store.event(data, run, "failed", summary,
                                         error=code, detail=json.dumps(diagnose(exc), ensure_ascii=False))
                        data["foreground"] = None
                        data["paused"] = True
                except Superseded:
                    pass

    def _snapshot(self, session_id, run_id, revision):
        data = self.store.get(session_id)
        run = data["runs"][run_id]
        if (data.get("status", "active") != "active" or run["revision"] != revision or run["status"] != "running"
                or run.get("lifecycle_revision", 0) != data.get("lifecycle_revision", 0)
                or not self._memory_run_valid(run)):
            raise Superseded()
        return data, run

    def _schedule_summary(self, sid):
        with self._worker_lock:
            if sid in self._summary_workers:
                return
            self._summary_workers.add(sid)
        def work():
            try:
                self.maintain_summary(sid)
            finally:
                with self._worker_lock:
                    self._summary_workers.discard(sid)
        threading.Thread(target=work, daemon=True, name="review-today-summary").start()

    def maintain_summary(self, sid):
        """Best-effort maintenance: never owns a foreground Run or its success."""
        data = self.store.get(sid)
        if not data or data.get("status", "active") != "active" or data.get("foreground"):
            return
        end = len(data["messages"]) - 12
        if end - data.get("summarized_count", 0) < 12:
            return
        version = (self.store.last_seq(data), data.get("lifecycle_revision", 0), data["summary_version"])
        older = [dict(role=m["role"], content=m["content"][:3000]) for m in data["messages"][data.get("summarized_count", 0):end]
                 if data["runs"].get(m.get("run_id"), {}).get("status") == "completed" and self._memory_run_valid(data["runs"].get(m.get("run_id"), {}))]
        dependencies = merge_references(data.get("summary_memory_references", []), *[
            data["runs"].get(m.get("run_id"), {}).get("memory_references", [])
            for m in data["messages"][data.get("summarized_count", 0):end]
            if self._memory_run_valid(data["runs"].get(m.get("run_id"), {}))])
        try:
            output = parse_model(
                "压缩已完成对话为交接摘要。保留目标、明确决定、未解决问题；不推断理解或授权。",
                json.dumps(dict(previous=data["summary"], messages=older), ensure_ascii=False), ConversationSummary, model=ROUTER_MODEL)
        except Exception as exc:
            with self.store.transaction(sid) as current:
                current["summary_error"] = dict(code=getattr(exc, "code", "RT.SUMMARY.FAILED"), at=now_iso())
            return
        with self.store.transaction(sid) as current:
            if version != (self.store.last_seq(current), current.get("lifecycle_revision", 0), current["summary_version"]) or current.get("foreground"):
                return
            current["summary"] = output.summary[:10000]
            current["summary_memory_references"] = dependencies
            current["summary_invalidated"] = False
            current["summary_version"] += 1
            current["summarized_count"] = end
            current.pop("summary_error", None)
            run = next((r for r in reversed(list(current["runs"].values())) if r["status"] == "completed"), None)
            if run:
                old_run = dict(run)
                self.store.event(current, run, "session_summary", "上下文摘要已更新，原文仍保留",
                                 payload={"session_summary": dict(output.model_dump(), version=current["summary_version"])})
                run.update(old_run)

    def _call(self, session_id, run_id, revision, node, system, prompt, schema, model=COACH_MODEL):
        data, run = self._snapshot(session_id, run_id, revision)
        strength = run.get("thinking_strength", data.get("thinking_strength", "smart"))
        prompt, capacity = prepare_context(system, prompt, window=configured_window(model), schema=schema.model_json_schema())
        key = hashlib.sha256((node + system + prompt + model + strength).encode()).hexdigest()
        if key in run["steps"]:
            return schema.model_validate(run["steps"][key])
        with self.store.transaction(session_id, run_id, revision) as data:
            data["runs"][run_id]["context_capacity"] = capacity
            self.store.event(data, data["runs"][run_id], node,
                             {"intent": "正在理解本轮意图", "evaluate": "正在评价这次独立作答",
                              "answer": "正在准备回答", "lesson": "正在准备讲解", "organize": "正在整理知识关系",
                              "problem_answer": "正在组织基础答案与学习路径", "jd_analysis": "正在拆解岗位要求",
                              "evidence_assessment": "正在核验回答依据", "session_summary": "正在整理会话摘要"}.get(node, "正在处理当前步骤"), model=model,
                             payload={"context_capacity": capacity})
        started = time.monotonic()
        last_emit = 0.0
        latest = ""

        def emit(partial, *, force=False):
            nonlocal last_emit, latest
            # Check even non-public chunks: a stopped generation closes promptly.
            self._snapshot(session_id, run_id, revision)
            text = public_preview(node, partial)
            if not text:
                return
            latest = text
            if not force and time.monotonic() - last_emit < 0.075:
                return
            with self.store.transaction(session_id, run_id, revision) as current:
                active = current["runs"][run_id]
                response = active.get("active_response")
                if not response or response["revision"] != revision or response["status"] != "streaming":
                    response = dict(response_id=str(uuid.uuid4()), revision=revision, chunk_seq=0, text="", delta="", status="streaming")
                    active["active_response"] = response
                    self.store.event(current, active, "response.started", "开始输出正文", payload={"response": dict(response)})
                if response["text"] == text:
                    return
                previous = response["text"]
                response.update(chunk_seq=response["chunk_seq"] + 1, text=text, delta=text[len(previous):] if text.startswith(previous) else "")
                if active.get("first_text_ms") is None:
                    active["first_text_ms"] = self._elapsed(active)
                self.store.event(current, active, "response.delta", "正文增量", model=model, payload={"response": dict(response)})
            last_emit = time.monotonic()

        def transport(kind):
            if kind == "buffered":
                with self.store.transaction(session_id, run_id, revision) as current:
                    active = current["runs"][run_id]
                    active["transport"] = "buffered"
                    self.store.event(current, active, "transport", "当前模型服务整段返回，未通过实时流式验收", model=model)

        handle_key = (session_id, run_id, revision)
        def register_cancel(handle):
            with self._worker_lock:
                self._cancel_handles[handle_key] = handle
            try:
                self._snapshot(session_id, run_id, revision)
            except Superseded:
                handle()
                raise

        try:
            streamable = node in {"answer", "lesson", "organize", "problem_answer", "evaluate", "jd_analysis"}
            with budget_scope() as budget:
                choices = ([model] + alternatives(model, strength, streamable))[:2]
                repaired = False
                for index, selected_model in enumerate(choices):
                    try:
                        model = selected_model
                        require_model(selected_model, thinking_strength=strength)
                        parsed = parse_model(system, prompt, schema, model=selected_model, on_cancel_handle=register_cancel,
                                             timeout=budget.remaining(), reasoning_effort="high" if strength == "deep" else None,
                                             **({"on_partial": emit, "on_transport": transport} if streamable else {}))
                        model = selected_model
                        break
                    except ModelCallError as error:
                        # Never splice a second generation into already shown text,
                        # retry refusals/access restrictions or exceed shared budget.
                        if error.code == "RT.MODEL.SCHEMA" and not latest and not repaired and budget.attempts < budget.limit:
                            repaired = True
                            choices[index + 1:] = [selected_model]
                            prompt += "\n输出结构校验失败。仅重新生成严格符合已给定结构的结果；不补造授权、证据、来源或已掌握状态。"
                            prompt, repaired_capacity = prepare_context(system, prompt, window=configured_window(model), schema=schema.model_json_schema())
                            with self.store.transaction(session_id, run_id, revision) as current:
                                current["runs"][run_id]["context_capacity"] = repaired_capacity
                            continue
                        if latest or not diagnose(error)["retryable"] or index + 1 == len(choices) or budget.attempts >= budget.limit:
                            raise
                        self._snapshot(session_id, run_id, revision)
            if streamable and latest:
                emit(parsed.model_dump(), force=True)
        except ModelCallError as exc:
            with self.store.transaction(session_id, run_id, revision) as data:
                self.store.event(data, data["runs"][run_id], node, "模型步骤未完成", model=model,
                                 duration_ms=int((time.monotonic() - started) * 1000), error=exc.code, detail=exc.diagnostic)
            raise
        finally:
            with self._worker_lock:
                self._cancel_handles.pop(handle_key, None)
        if parsed is None:
            raise ModelCallError("EMPTY")
        try:
            output = schema.model_validate(parsed.model_dump())
        except ValidationError:
            raise ModelCallError("SCHEMA", "ValidationError") from None
        with self.store.transaction(session_id, run_id, revision) as data:
            run = data["runs"][run_id]
            run["steps"][key] = output.model_dump()
            self.store.event(data, run, node, "本步骤已完成", model=model,
                             duration_ms=int((time.monotonic() - started) * 1000))
        return output

    @staticmethod
    def _elapsed(run):
        if run.get("started_at"):
            return max(0, int((datetime.fromisoformat(now_iso()) - datetime.fromisoformat(run["started_at"])).total_seconds() * 1000))
        return run.get("elapsed_ms", 0)

    def _freeze_clock(self, run):
        if run.get("started_at"):
            run["elapsed_ms"] = self._elapsed(run)
            run.setdefault("attempt_durations", []).append(run["elapsed_ms"])
            run["started_at"] = None

    def _end_response(self, data, run, status):
        response = run.get("active_response")
        if response and response["status"] == "streaming":
            response.update(status=status, delta="", chunk_seq=response["chunk_seq"] + 1)
            self.store.event(data, run, f"response.{status}", "未完成内容已保留", payload={"response": dict(response)})

    def _task(self, data, run):
        return data["tasks"].get(run.get("task_id") or data["active_task_id"])

    def _project_event(self, data, run, task, message=None):
        task["context"]["memory_references"] = merge_references(task["context"].get("memory_references", []), run.get("memory_references", []))
        task["context"]["latest_run_id"] = run["run_id"]
        task["context"]["lifecycle_revision"] = data.get("lifecycle_revision", 0)
        event = TaskEvent(event_id=str(uuid.uuid4()), session_id=data["session_id"], task_id=task["task_id"],
                          seq=len(task["events"]) + 1, occurred_at=now_iso(), stage=task["stage"], state=task["status"],
                          node=task["stage"], user_summary=task["user_summary"], attempt=max(run["attempt"], 1),
                          required_action=task["required_action"], message=message)
        task["events"].append(event.model_dump())
        self.store.event(data, run, "task_updated", task["user_summary"],
                         payload={"task": HarnessTaskRecord(**task).view().model_dump(),
                                  "memory_references": task["context"].get("memory_references", run.get("memory_references", []))})

    def _publish(self, sid, rid, rev, text, *, stage=None, task_status="awaiting_user", required=None, draft=False, source_type=None, draft_content=None, complete=True):
        with self.store.transaction(sid, rid, rev) as data:
            run = data["runs"][rid]
            response = run.get("active_response")
            if response and response["revision"] == rev and response["status"] == "streaming":
                response.update(text=text, delta="", status="complete", chunk_seq=response["chunk_seq"] + 1)
                event = self.store.event(data, run, "response.completed", "正文已完成校验", message=text,
                                        message_id=response["response_id"], payload={"response": dict(response)})
            else:
                event = self.store.event(data, run, stage or "response", "已回应", message=text)
            task = self._task(data, run)
            if task and stage:
                step = current_step(task)
                if step:
                    if event["message"]["message_id"] not in step["message_ids"]:
                        step["message_ids"].append(event["message"]["message_id"])
                    if step["state"] == "pending":
                        step["state"] = "explained"
                task.update(stage=stage, status=task_status, user_summary=("本次学习目标已完成" if stage == "mastered" else "已交付整理结果") if task_status == "completed" else "等你继续",
                            required_action=required)
                if task_status == "completed":
                    if stage == "lesson_complete":
                        task["user_summary"] = "本次学习安排已讲解完毕"
                    task["context"]["learning_outcome"] = outcome(task)
                    task["context"]["learning_outcome"]["message_id"] = event["message"]["message_id"]
                self._project_event(data, run, task, event["message"])
            if draft:
                previous = (task["context"].get("draft") if task else data.get("draft")) or {}
                value = dict(id=task["task_id"] if task else rid, version=previous.get("version", 0) + 1,
                             content=draft_content or text, understanding=(task["context"].get("understanding", "unknown") if task else "unknown"),
                             source_type=source_type or "user_material")
                value["memory_references"] = run.get("memory_references", [])
                value["public_search_query"] = (run.get("intent") or {}).get("public_search_query", "")
                if task:
                    task["context"]["draft"] = value
                data["draft"] = value
                data["pending"] = dict(kind="save", target_id=value["id"], version=value["version"])
                self.store.event(data, run, "draft", "整理结果尚未入库", payload={"draft": value, "pending": data["pending"]})
            if complete:
                # Publishing the final answer and marking its generation complete
                # share one commit. A crash before the worker's final status/summary
                # must not replay an answer the Mac may already have consumed.
                run["execution_complete"] = True
                if run.get("active_response", {}).get("status") == "complete":
                    run.pop("active_response", None)

    def _context(self, data, run):
        selected = [m for m in data["messages"] if m.get("message_id") in run["input_ids"]]
        last = dict(selected[-1])
        if run.get("resolved_input"):
            last["content"] = run["resolved_input"]
            last["operation"] = None
        task = self._task(data, run)
        task_context = None
        if task:
            task_context = {k: task[k] for k in ("task_id", "mode", "stage", "status", "content", "required_action", "context")}
            if task["context"].get("memory_invalidated"):
                task_context = dict(task_id=task["task_id"], mode=task["mode"], content=task["content"],
                                    status=task["status"], stage="memory_updated", context={"memory_invalidated": True})
        # Explicit structured state is never compressed into model prose. Limit only
        # the narrative window; local Mac retains the complete original transcript.
        eligible = [m for m in data["messages"] if m not in selected and data["runs"].get(m.get("run_id"), {}).get("status") != "queued"
                    and self._memory_run_valid(data["runs"].get(m.get("run_id"), {}))]
        recent = [dict(message_id=m["message_id"], role=m["role"], content=m["content"][:3000]) for m in eligible[-16:]]
        external = last.get("context", {})
        return dict(mode=data["mode"], session_goal=data.get("focus_goal", ""),
                    current_inputs=[run["resolved_input"]] if run.get("resolved_input") else [m["content"] for m in selected], task=task_context,
                    pending=data["pending"], draft=None if data.get("draft", {}) and data["draft"].get("invalidated") else data["draft"],
                    summary=data["summary"] if data.get("summary_invalidated") else data["summary"] or external.get("summary", ""),
                    recent_messages=recent if data.get("summary_invalidated") else recent or external.get("recent_messages", [])[-10:],
                    related_knowledge=external.get("knowledge_summaries", [])[:5],
                    memory_candidates=[c for c in external.get("memory_candidates", [])[:12] if self.store.memory_valid([c])] if not run.get("intent") else [],
                    related_learning=run.get("memory_references", []), handoff=external.get("handoff")), last

    @staticmethod
    def _light_reply(decision, last, *, has_active_task=False, has_pending=False, has_draft=False):
        intents = set(decision.intents)
        basic = bool(intents) and intents <= {"greeting", "thanks", "capabilities"}
        defer = intents == {"defer"}
        # Runs created before `defer` existed may already have a validated
        # self_report checkpoint. It is only side-effect free without learning
        # state; an active-task self report must still update understanding.
        legacy_defer = (intents == {"self_report"} and
                        not has_active_task and not has_pending and not has_draft)
        allowed = ((basic and bool(decision.light_reply.strip())) or defer or legacy_defer)
        if not (allowed and decision.scope == "conversation" and not decision.workflow and not decision.target_task_id
                and not decision.proposed_actions and not decision.clarification and not decision.needs_verification
                and not decision.requested_mode and decision.understanding == "unknown"
                and not decision.direct_teaching and not decision.is_jd and not last.get("operation")):
            return ""
        if decision.light_reply.strip():
            return decision.light_reply.strip()
        if defer:
            return "好的，你慢慢想。准备好后继续。"
        return "收到。准备好后可以继续告诉我。"

    @classmethod
    def _light_reply_allowed(cls, decision, last, **state):
        return bool(cls._light_reply(decision, last, **state))

    @staticmethod
    def _activity_kind(data: dict, run: dict) -> str | None:
        """Project only completed learning value, never UI chatter, into Today."""
        candidate = run.get("activity_candidate")
        return candidate if candidate in {"knowledge_answer", "lesson_step"} else None

    def _execute(self, sid, rid, rev):
        data, run = self._snapshot(sid, rid, rev)
        context, last = self._context(data, run)
        # Context reuse inherits the source versions even when Luna chooses no
        # additional cross-Session example on this turn.
        contextual = [r.get("memory_references", []) for r in data["runs"].values()
                      if self._memory_run_valid(r) and any(m.get("run_id") == r["run_id"] and m["message_id"] in
                         {v.get("message_id") for v in context["recent_messages"]} for m in data["messages"])]
        task = self._task(data, run)
        if task and not task["context"].get("memory_invalidated"):
            contextual.append(task["context"].get("memory_references", []))
        if data.get("summary") and self.store.memory_valid(data.get("summary_memory_references", [])):
            contextual.append(data.get("summary_memory_references", []))
        with self.store.transaction(sid, rid, rev) as current:
            current["runs"][rid]["memory_references"] = merge_references(*contextual)
        if last.get("operation"):
            kind = last["operation"]["kind"]
            task = self._task(data, run)
            decision = IntentDecision(intents=["reject" if kind == "reject_save" else "confirm"],
                                      target_task_id=task["task_id"] if task else "", relation="continuation",
                                      workflow=task["mode"] if task and task["mode"] != "auto" else None,
                                      scope="continue_goal", rationale="用户点击了绑定对象与内容版本的操作；由程序检查执行条件。")
        elif run.get("intent") and run.get("decision_input_ids") == run["input_ids"] and run.get("decision_mode") == data["mode"]:
            decision = IntentDecision.model_validate(run["intent"])
        else:
            decision = self._call(sid, rid, rev, "intent", INTENT_SYSTEM,
                                  json.dumps(context, ensure_ascii=False), IntentDecision, ROUTER_MODEL)
        light_reply = self._light_reply(
            decision,
            last,
            has_active_task=bool(self._task(data, run)),
            has_pending=bool(data.get("pending")),
            has_draft=bool(data.get("draft")),
        )
        if light_reply:
            with self.store.transaction(sid, rid, rev) as current:
                active = current["runs"][rid]
                active.update(intent=decision.model_dump(), decision_input_ids=list(active["input_ids"]), decision_mode=current["mode"], task_id=None)
                self.store.event(current, active, "intent_decided", "已识别为轻量对话", model=ROUTER_MODEL,
                                 detail=decision.rationale, payload={"intent": decision.model_dump(), "memory_references": active.get("memory_references", [])})
            self._publish(sid, rid, rev, light_reply)
            return
        if "queue" in decision.intents and len(run["input_ids"]) > 1:
            with self.store.transaction(sid, rid, rev) as data:
                current = data["runs"][rid]
                later_id = current["input_ids"].pop()
                later = _new_run(sid, later_id, "queued")
                data["runs"][later["run_id"]] = later
                next(m for m in data["messages"] if m["message_id"] == later_id)["run_id"] = later["run_id"]
                data["message_receipts"][later_id]["run_id"] = later["run_id"]
                current["revision"] += 1
                current["status"] = "accepted"
                self.store.event(data, later, "queued", "已排队，当前回复结束后处理")
            raise Superseded()
        with self.store.transaction(sid, rid, rev) as data:
            run = data["runs"][rid]
            if decision.target_task_id and decision.target_task_id not in data["tasks"]:
                raise ValueError("RT.INTENT.INVALID_TARGET")
            run["intent"] = decision.model_dump()
            run["decision_input_ids"] = list(run["input_ids"])
            run["decision_mode"] = data["mode"]
            run["task_id"] = decision.target_task_id or data["active_task_id"]
            selected_memory = select_references([c for c in last.get("context", {}).get("memory_candidates", []) if self.store.memory_valid([c])],
                                                [s.model_dump() for s in decision.memory_selections])
            run["memory_references"] = merge_references(run.get("memory_references", []), selected_memory)
            task = self._task(data, run)
            if task and "hint" in decision.intents:
                task["context"]["hint_used"] = True
            if "correction" in decision.intents:
                self.store.event(data, run, "memory_corrected", "已收到纠正，正在调整相关内容", payload={"invalidate_memory": True})
            self.store.event(data, run, "intent_decided", "已理解本轮要求", detail=decision.rationale,
                             model="" if last.get("operation") else ROUTER_MODEL,
                             payload={"intent": decision.model_dump(), "memory_references": run["memory_references"]})
            if data.get("draft") and decision.understanding == "self_reported":
                if data["draft"]["understanding"] != "verified":
                    data["draft"]["understanding"] = "self_reported"
            if "correction" in decision.intents and data.get("draft"):
                data["draft"].update(version=data["draft"]["version"] + 1, invalidated=True, understanding="unknown")
                owner = data["tasks"].get(data["draft"]["id"])
                if owner:
                    owner["context"]["draft"] = dict(data["draft"])
                    owner["context"].update(understanding="unknown", independent_passed=False, transfer_passed=False)
                data["pending"] = None
            if set(decision.intents) & {"stop", "pause", "cancel"}:
                if len(run["input_ids"]) > 1:
                    run["input_ids"].pop()  # consumed control, not a prompt to replay on resume
                else:
                    run["control_only"] = True
                self._stop(data, run, cancel="cancel" in decision.intents)
                return
            if run.get("paused_entry") and "continue" in decision.intents:
                data["paused"] = False
                previous = next((r for r in reversed(list(data["runs"].values())) if r["run_id"] != rid and r["status"] == "interrupted" and not r.get("control_only")), None)
                if previous:
                    previous["revision"] += 1
                    previous["status"] = "accepted"
                    self.store.event(data, run, "resuming", "已收到继续指令，将续接停止的步骤", message="好的，继续刚才未完成的步骤。")
                    return
        operation_key = hashlib.sha256(json.dumps([run["input_ids"], decision.model_dump(), last.get("operation")], sort_keys=True).encode()).hexdigest()
        # An action and an explanatory follow-up may share a turn. Checkpoint the
        # action separately, so retrying its answer never repeats the confirmed write.
        completed_operations = run.get("completed_operations", {})
        if operation_key in completed_operations:
            handled = completed_operations[operation_key]
        else:
            handled = self._handle_operations(sid, rid, rev, decision, last)
            with self.store.transaction(sid, rid, rev) as data:
                data["runs"][rid].setdefault("completed_operations", {})[operation_key] = handled
        if handled:
            if set(decision.intents) & {"followup", "hint", "example"} and not last.get("operation"):
                self._respond(sid, rid, rev, decision, "受控操作已处理；回答同一输入附带的追问、提示或举例，不重复操作，也不把解释视为检查通过。", node="answer")
            return
        data, run = self._snapshot(sid, rid, rev)
        if data.get("pending", {}) and data["pending"].get("consent_received") and decision.understanding == "self_reported" and not set(decision.intents) & {"reject", "correction"}:
            self._save_memory(sid, rid, rev, decision)
            return
        if decision.clarification:
            self._publish(sid, rid, rev, decision.clarification)
            return
        # A pending Session boundary is resolved before touching the old learning goal.
        if decision.relation == "new_topic" and (data["active_task_id"] or data.get("focus_goal")):
            with self.store.transaction(sid, rid, rev) as data:
                data["pending"] = dict(kind="new_session", target_id=rid, version=rev, content=last["content"],
                                       decision=decision.model_dump())
                self.store.event(data, data["runs"][rid], "session_choice", "等你确认新目标放在哪里",
                                 message="这个目标与当前学习内容不同。要新建学习会话，还是继续放在这里？原目标和进度都会保留。",
                                 payload={"pending": data["pending"]})
            return
        if not data.get("focus_goal") and set(decision.intents) & {"goal", "question", "material"}:
            with self.store.transaction(sid, rid, rev) as data:
                data["focus_goal"] = last["content"][:2000]
        task = self._task(data, run)
        intents = set(decision.intents)
        if task and task["context"].get("memory_invalidated") and intents & {"question", "material", "goal"} and not intents & {"followup", "answer", "continue", "hint", "example"}:
            # Explicit fresh input can re-ground this topic. Keep the old task and
            # all its evidence in history; do not reinterpret its excluded material.
            with self.store.transaction(sid, rid, rev) as current:
                current["active_task_id"] = None
                current["draft"] = None
                current["pending"] = None
                current["runs"][rid]["task_id"] = None
            data, run = self._snapshot(sid, rid, rev)
            task = None
        if intents <= {"greeting", "thanks", "capabilities"}:
            self._respond(sid, rid, rev, decision, "自然回应；不要展开学习流程。", node="answer")
            return
        if task and task["status"] not in {"cancelled", "terminal_failed"}:
            if task["context"].get("memory_invalidated"):
                self._publish(sid, rid, rev, "关联的旧学习内容已更新或不再用于关联；历史和学习进度仍保留。请提供接下来要使用的资料或明确的新问题，我不会沿用失效内容评价或入库。")
                return
            if intents & {"followup", "hint", "example", "correction"}:
                if "correction" in intents:
                    with self.store.transaction(sid, rid, rev) as data:
                        task = self._task(data, data["runs"][rid])
                        task["context"]["understanding"] = "unknown"
                        task["context"]["independent_passed"] = False
                        task["context"]["transfer_passed"] = False
                        task["context"]["corrections"] = task["context"].get("corrections", []) + [last["content"]]
                        data["pending"] = None
                if "correction" in intents and data.get("draft"):
                    self._respond(sid, rid, rev, decision, "根据用户纠正更新并完整展示整理稿；标明修改处，不默认用户理解或入库。", node="organize", draft=True)
                else:
                    self._respond(sid, rid, rev, decision, "优先解释用户指定内容、给提示或例子/纠正，不评价为作答，不改变现有待办。", node="answer")
                return
            if intents & {"skip_check", "self_report"}:
                with self.store.transaction(sid, rid, rev) as data:
                    task = self._task(data, data["runs"][rid])
                    if "self_report" in intents and task["context"].get("understanding") != "verified":
                        task["context"]["understanding"] = "self_reported"
                    record_understanding(task, task["context"].get("understanding", "unknown"), skipped="skip_check" in intents)
                    if task["context"].get("draft"):
                        task["context"]["draft"]["understanding"] = task["context"].get("understanding", "unknown")
                        data["draft"] = task["context"]["draft"]
                if task["context"].get("requires_mastery"):
                    self._publish(sid, rid, rev, "可以先跳过或继续学习；这不会标记为已攻克。准备好后，请独立作答并完成追问。")
                elif "self_report" in intents and "continue" not in intents and "skip_check" not in intents:
                    self._publish(sid, rid, rev, "已记录为自述理解，尚未通过独立检查。你可以继续学习、尝试检查，或明确要求保存刚才这段内容。")
                else:
                    self._respond(sid, rid, rev, decision, "尊重跳过检查，继续下一段教学；说明尚未验证掌握。", node="lesson", teaching=True)
                return
            if "answer" in intents and task["stage"] not in {"clarify_goal", "choose_source_path", "awaiting_material"}:
                if task["context"].get("check_question") or task["stage"] in {"practice", "transfer"}:
                    self._evaluate(sid, rid, rev, decision, last)
                else:
                    self._respond(sid, rid, rev, decision, "回应用户补充的背景，并邀请进行独立作答。", node="lesson", teaching=True)
                return
            if data["mode"] == "auto" and decision.workflow and decision.workflow != task["mode"] and decision.scope != "conversation":
                transition = (decision.workflow == "source_learning" and decision.direct_teaching or
                              decision.workflow == "problem_solving" and bool(intents & {"goal", "question"}) and not decision.answer_only or
                              decision.workflow == "memory_organization" and decision.scope == "organize")
                if transition:
                    with self.store.transaction(sid, rid, rev) as data:
                        task = self._task(data, data["runs"][rid])
                        task["mode"] = decision.workflow
                        self.store.event(data, data["runs"][rid], "workflow_transition", f"围绕当前目标，接下来使用{LABELS[decision.workflow]}能力")
                if decision.workflow == "source_learning" and decision.direct_teaching:
                    self._respond(sid, rid, rev, decision, "围绕现有目标直接分段教学，保留已有学习进度。", node="lesson", teaching=True, generated=True)
                    return
                if decision.workflow == "problem_solving" and intents & {"goal", "question"} and not decision.answer_only:
                    self._problem(sid, rid, rev, decision)
                    return
                if decision.workflow == "memory_organization" and decision.scope == "organize":
                    self._respond(sid, rid, rev, decision, "整理当前目标已学习的知识关系，不自动入库。", node="organize", draft=True)
                    return
            if task["context"].get("mode_changed"):
                selected = data["mode"] if data["mode"] != "auto" else decision.workflow or task["mode"]
                with self.store.transaction(sid, rid, rev) as data:
                    task = self._task(data, data["runs"][rid])
                    task["context"]["mode_changed"] = False
                    task["mode"] = selected
                if selected == "memory_organization":
                    self._respond(sid, rid, rev, decision, "整理当前目标的已有资料和知识关系，保留进度；只交付整理，不默认入库。", node="organize", draft=True)
                elif selected == "problem_solving":
                    self._problem(sid, rid, rev, decision)
                elif selected == "source_learning":
                    self._respond(sid, rid, rev, decision, "沿用当前目标已有材料和进度，继续教学。", node="lesson", teaching=True,
                                  generated=not task["context"].get("selected_sources"))
                else:
                    self._sources(sid, rid, rev, task["content"])
                return
            if task["stage"] == "jd_analysis" and "confirm" in intents:
                self._publish(sid, rid, rev, "请指定要先攻克的题目，或点击题目按钮。")
                return
            if task["stage"] in {"clarify_goal", "choose_source_path", "awaiting_material"}:
                if decision.direct_teaching:
                    self._respond(sid, rid, rev, decision, "按已明确的目标建立小型学习地图并直接教第一段，标注来源：Agent 生成讲义。", node="lesson", teaching=True, generated=True)
                elif "material" in intents:
                    self._respond(sid, rid, rev, decision, "讲解本轮提供的资料，第一段即可。", node="lesson", teaching=True)
                else:
                    self._sources(sid, rid, rev, last["content"])
                return
            if "continue" in intents and task["mode"] in {"source_learning", "problem_solving"}:
                self._respond(sid, rid, rev, decision, "基于已有进度继续补教/练习，避免重复已讲内容；不要把继续视为已理解或通过。", node="lesson", teaching=True)
                return
        # Only an actual goal creates a LearningTask. Answer-only, greeting and bare
        # material organization remain lightweight runs even in a non-Auto Session.
        workflow = decision.workflow or "topic_exploration"
        if data["mode"] != "auto" and not decision.answer_only:
            workflow = data["mode"]
        full_goal = (decision.scope in {"learning", "continue_goal"} or "goal" in intents or
                     (data["mode"] == "problem_solving" and "question" in intents)) and not decision.answer_only
        if "material" in intents and not task and data["mode"] == "auto":
            workflow = "memory_organization"
        if "correction" in intents and data.get("draft") and not task:
            self._respond(sid, rid, rev, decision, "按用户纠正更新并展示完整的整理稿，不默认理解或入库。", node="organize", draft=True)
            return
        if full_goal and (not task or task["status"] in FINISHED):
            with self.store.transaction(sid, rid, rev) as data:
                run = data["runs"][rid]
                task = asdict(HarnessTaskRecord(task_id=str(uuid.uuid4()), session_id=sid,
                              client_message_id=last["message_id"], content=last["content"], content_type=last.get("content_type", "text"),
                              primary_language="zh", mode_preset=data["mode"], mode=workflow,
                              context={"conversation_managed": True, "understanding": "unknown",
                                       "requires_mastery": workflow == "problem_solving", "origin_run_id": rid}))
                data["tasks"][task["task_id"]] = task
                data["active_task_id"] = task["task_id"]
                run["task_id"] = task["task_id"]
                self._project_event(data, run, task)
        elif not full_goal and not task:
            with self.store.transaction(sid, rid, rev) as data:
                data["runs"][rid]["task_id"] = None
        if workflow == "memory_organization" and (decision.scope == "organize" or "material" in intents or full_goal):
            self._respond(sid, rid, rev, decision, "先交付知识整理：主题、知识点与关系。不声称已理解或已入库。", node="organize", draft=True)
        elif full_goal and workflow == "problem_solving":
            self._problem(sid, rid, rev, decision)
        elif full_goal and workflow == "topic_exploration" and not decision.direct_teaching:
            self._publish(sid, rid, rev, "你最希望学完后能够做什么？例如理解基本原理、在项目中使用，或回答面试题。",
                          stage="clarify_goal", required={"type": "respond", "prompt": "明确一个学习目标", "options": []})
        elif full_goal and workflow in {"source_learning", "topic_exploration"}:
            self._respond(sid, rid, rev, decision, "按目标分段教学，先给学习地图和第一段讲解；检查可选。", node="lesson", teaching=True,
                          generated=decision.direct_teaching or "material" not in intents)
        else:
            self._respond(sid, rid, rev, decision, "直接回答本轮问题，深入学习可选；不要强制进入完整训练。", node="answer")

    @staticmethod
    def _explicit(operation, text):
        evidence = operation.get("evidence", "")
        if not evidence.strip() or evidence not in text:
            return False
        # Conservative authorization firewall, not a content classifier. Conditional
        # and quoted assent is never sufficient even if the semantic model says yes.
        if re.search(r"不要|别保存|不保存|不切换|不新建|不能|不行|不同意|但是|但|不过|如果|除非|先别|not |don't|unless|but ", text, re.I):
            return False
        return not any(evidence in span for span in re.findall(r"https?://\S+|```[\s\S]*?```|“[^”]*”|‘[^’]*’|「[^」]*」|\"[^\"]*\"|^>.*$", text, re.M))

    def _handle_operations(self, sid, rid, rev, decision, last):
        data, run = self._snapshot(sid, rid, rev)
        pending = data["pending"]
        operations = [item.model_dump() for item in decision.proposed_actions]
        bound = last.get("operation")
        if bound:
            operations = [dict(bound, disposition="reject" if bound["kind"] == "reject_save" else "confirm", evidence="", trusted_button=True)]
        for op in operations:
            if op["kind"] == "change_goal" and op["disposition"] == "request" and not pending:
                # Proposing the first goal is not confirming an existing operation.
                # Existing/unrelated goals still pass the Session-boundary check.
                continue
            if op["kind"] == "set_mode":
                if op["disposition"] in {"confirm", "request"} and self._explicit(op, last["content"]) and decision.requested_mode:
                    with self.store.transaction(sid, rid, rev) as data:
                        data["mode"] = decision.requested_mode
                        task = self._task(data, data["runs"][rid])
                        if task:
                            task["mode_preset"] = decision.requested_mode
                            task["context"]["mode_changed"] = True
                            if decision.requested_mode != "auto":
                                task["mode"] = decision.requested_mode
                    self._publish(sid, rid, rev, f"已选择{LABELS[decision.requested_mode]}，从下一步生效；已有资料和进度保留。", complete=False)
                    return True
                continue
            if op["kind"] == "save" and op["disposition"] == "request" and not pending and self._explicit(op, last["content"]):
                task = self._task(data, run)
                previous = next((m for m in reversed(data["messages"]) if m["role"] == "coach"), None)
                known_ids = {"", task["task_id"] if task else "", previous["message_id"] if previous else ""}
                if op.get("target_id") not in known_ids:
                    self._publish(sid, rid, rev, "你希望保存哪一份具体内容？这次不会自动提交。", complete=False)
                    return True
                if data.get("draft", {}) and data["draft"].get("invalidated"):
                    self._publish(sid, rid, rev, "整理稿的修订尚未完成，请先完成修订，旧版不会入库。", complete=False)
                    return True
                content = task["context"].get("last_lesson") if task else None
                if content or previous:
                    with self.store.transaction(sid, rid, rev) as data:
                        value = dict(id=task["task_id"] if task else previous["message_id"],
                                     version=task["context"].get("lesson_index", 1) if task else 1,
                                     content=content or previous["content"],
                                     understanding=task["context"].get("understanding", "unknown") if task else "unknown",
                                     source_type=task["context"].get("source_type", "agent_generated") if task else "agent_generated")
                        data["draft"] = value
                        data["pending"] = dict(kind="save", target_id=value["id"], version=value["version"], consent_received=True)
                    self._save_memory(sid, rid, rev, decision)
                    return True
            if not pending or op.get("target_id") != pending["target_id"] or op.get("version") != pending["version"]:
                if op["disposition"] in {"request", "confirm"}:
                    self._publish(sid, rid, rev, "当前没有与这次确认对应的待办版本。请先确认具体内容；我不会据此保存、切换目标或新建会话。", complete=False)
                    return True
                continue
            if op["disposition"] == "reject" or op["kind"] == "reject_save":
                with self.store.transaction(sid, rid, rev) as data:
                    data["pending"] = None
                    current_task = self._task(data, data["runs"][rid])
                    if current_task and (current_task.get("required_action") or {}).get("type") == "confirm_memory":
                        current_task["required_action"] = None
                        self._project_event(data, data["runs"][rid], current_task)
                if set(decision.intents) & {"followup", "hint", "example", "correction"}:
                    continue
                self._publish(sid, rid, rev, "好的，不执行这项操作；已有内容和学习进度保留。", complete=False)
                return True
            if op["disposition"] not in {"confirm", "request"} or (not op.get("trusted_button") and not self._explicit(op, last["content"])):
                continue
            if op["kind"] == "save" and pending["kind"] == "save":
                self._save_memory(sid, rid, rev, decision)
                return True
            if op["kind"] in {"new_session", "continue_session"} and pending["kind"] == "new_session":
                with self.store.transaction(sid, rid, rev) as data:
                    data["pending"] = None
                    if op["kind"] == "new_session":
                        # The Mac creates the local Session and persists this explicit
                        # handoff before submitting its first message. No history dump.
                        origin = self._task(data, data["runs"][rid]) or {}
                        ctx = origin.get("context", {})
                        selected = pending.get("decision", {})
                        sources = [s for s in ctx.get("sources", []) if s.get("source_id") in selected.get("handoff_source_ids", [])]
                        steps = [s for s in (ctx.get("learning_plan") or {}).get("steps", []) if s.get("id") in selected.get("handoff_step_ids", [])]
                        knowledge = [dict(knowledge_id=k["id"], version=k.get("version", 1))
                                     for t in data["tasks"].values() if steps and t["status"] == "completed" and t["context"].get("draft_id") == origin.get("task_id")
                                     for k in (t.get("memory_package") or {}).get("knowledge", [])]
                        package = dict(handoff_id=f"{pending['target_id']}:{pending['version']}", goal=pending["content"],
                                       mode=data["mode"], source_session_id=sid,
                                       summary="用户确认的新目标：" + pending["content"][:2000],
                                       source_refs=sources, knowledge_refs=knowledge, progress=steps,
                                       open_questions=[ctx["check_question"]] if steps and ctx.get("check_question") else [])
                        self.store.event(data, data["runs"][rid], "handoff", "已准备新会话交接", payload={"handoff": package})
                        return True
                    data["active_task_id"] = None
                    data["runs"][rid]["task_id"] = None
                    data["focus_goal"] = pending["content"][:2000]
                    data["runs"][rid]["resolved_input"] = pending["content"]
                    data["runs"][rid]["intent"] = dict(pending["decision"], relation="continuation", target_task_id="")
                self._execute(sid, rid, rev)
                return True
            if op["kind"] == "select_question" and pending["kind"] == "select_question":
                selected = op.get("selection") or [last["content"]]
                if len(selected) != 1 or selected[0] not in pending["options"]:
                    self._publish(sid, rid, rev, "请选择清单中的一道题。", complete=False)
                    return True
                with self.store.transaction(sid, rid, rev) as data:
                    task = self._task(data, data["runs"][rid])
                    task["content"] = selected[0]
                    data["pending"] = None
                decision.is_jd = False
                self._problem(sid, rid, rev, decision)
                return True
            if op["kind"] == "select_sources" and pending["kind"] == "select_sources":
                selected = op.get("selection") or pending["options"]
                if not selected or not set(selected).issubset(set(pending["options"])):
                    raise ValueError("RT.SOURCE.INVALID_SELECTION")
                with self.store.transaction(sid, rid, rev) as data:
                    task = self._task(data, data["runs"][rid])
                    task["context"]["selected_sources"] = selected
                    if data["mode"] == "auto":
                        task["mode"] = "source_learning"
                    data["pending"] = None
                self._respond(sid, rid, rev, decision, "根据用户已确认的资料包分段教学，标明出处。", node="lesson", teaching=True)
                return True
        return False

    def _evidence(self, sid, rid, rev, decision, text):
        if not decision.needs_verification and not RISK_RULE.search(text):
            return {"state": "unverified", "summary": "稳定基础知识直接回答，未作实时查证", "sources": []}
        with self.store.transaction(sid, rid, rev) as data:
            self.store.event(data, data["runs"][rid], "evidence_check", "正在查证风险或时效信息", model=RISK_MODEL)
        query = self._public_query(decision.public_search_query)
        if not query:
            return {"state": "insufficient", "summary": "尚未形成不含私人资料的公开核验主题，当前内容未核验", "sources": []}
        evidence = self._search(sid, rid, rev, "核验并附可定位来源：" + query, RISK_MODEL)
        self._snapshot(sid, rid, rev)
        if not evidence:
            return {"state": "insufficient", "summary": "未取得可核验证据，不能认定已核验", "sources": []}
        result = self._call(sid, rid, rev, "evidence_assessment",
                            "核对检索证据是否支持用户问题；证据冲突/不足必须诚实标记。不能把生成讲义视为外部证据。",
                            json.dumps({"question": text, "evidence": evidence}, ensure_ascii=False), EvidenceAssessmentV2, RISK_MODEL)
        result.sources = [source for source in result.sources if source in evidence and looks_like_url(source)]
        if result.state == "supported" and not result.sources:
            result.state = "insufficient"
            result.summary = "检索未提供可定位的支持来源，尚不能认定核验通过"
        return result.model_dump()

    def _respond(self, sid, rid, rev, decision, instruction, *, node, teaching=False, draft=False, generated=False):
        data, run = self._snapshot(sid, rid, rev)
        context, last = self._context(data, run)
        task = self._task(data, run)
        if teaching and task and not task["context"].get("requires_mastery"):
            with self.store.transaction(sid, rid, rev) as current:
                live_task = self._task(current, current["runs"][rid])
                finished = advance(live_task) if set(decision.intents) & {"continue", "skip_check"} else False
            if finished:
                self._publish(sid, rid, rev, "这份学习安排已讲解完毕。未检查或跳过的部分仍需练习；你可以继续追问或调整学习安排。",
                              stage="lesson_complete", task_status="completed")
                return
            data, run = self._snapshot(sid, rid, rev)
            context, last = self._context(data, run)
            task = self._task(data, run)
        prior = task["context"] if task else {}
        sources = list(prior.get("sources", []))
        source_cache = run.get("source_cache", {})
        urls = (task["context"].get("selected_sources", []) if task else [])
        if "material" in decision.intents and looks_like_url(last["content"]):
            urls = [looks_like_url(last["content"])]
        for url in urls[:4]:
            previous = next((s for s in sources if s.get("url") == url and s.get("content")), None)
            if previous and not decision.refresh_sources:
                continue
            saved = source_cache.get(url)
            if saved is None:
                title, body = fetch_public_url(url)
                saved = dict(source_id=str(uuid.uuid5(uuid.UUID(sid), url)), version=(previous or {}).get("version", 0) + 1,
                             fetched_at=now_iso(), type="public_source", url=url, title=title, content=body[:10000])
                with self.store.transaction(sid, rid, rev) as current:
                    current["runs"][rid].setdefault("source_cache", {})[url] = saved
                    if previous and task:
                        self._task(current, current["runs"][rid])["context"].setdefault("source_history", []).append(previous)
            sources = [s for s in sources if s.get("url") != url] + [saved]
            self._snapshot(sid, rid, rev)
        evidence = self._evidence(sid, rid, rev, decision, last["content"])
        source_type = "agent_generated" if generated else prior.get("source_type") or ("public_source" if sources else "user_material")
        new_user_material = "material" in decision.intents and not looks_like_url(last["content"])
        if new_user_material:
            material_id = str(uuid.uuid5(uuid.UUID(sid), f"material:{last['message_id']}"))
            if not any(s.get("source_id") == material_id for s in sources):
                sources.append(dict(source_id=material_id, version=1, type="user_material", url="",
                                    title="用户提供的资料", fetched_at=last.get("created_at", now_iso()), locator=last["message_id"], content=last["content"]))
        if (not sources and (generated or new_user_material or draft) and source_type in {"agent_generated", "user_material"}) or (generated and not any(s.get("type") == "agent_generated" for s in sources)):
            owner = task["task_id"] if task else run["run_id"]
            sources.append(dict(source_id=str(uuid.uuid5(uuid.UUID(sid), f"{owner}:{source_type}")), version=1,
                                type=source_type, url="", title="Agent 生成讲义" if source_type == "agent_generated" else "用户提供的资料",
                                fetched_at=now_iso(), locator=last["message_id"], content="" if source_type == "agent_generated" else last["content"]))
        types = {s.get("type", "public_source") for s in sources}
        if len(types) > 1:
            source_type = "mixed"
        output = self._call(sid, rid, rev, node, COACH_SYSTEM,
                            json.dumps(dict(instruction=instruction, context=context, sources=sources,
                                            source_type=source_type, evidence=evidence), ensure_ascii=False), ConversationOutput)
        with self.store.transaction(sid, rid, rev) as current:
            current["runs"][rid]["learning_concepts"] = output.learning_concepts
        if output.evidence_state in {"insufficient", "conflicting", "outdated"} and not decision.needs_verification:
            evidence = self._evidence(sid, rid, rev, decision.model_copy(update={"needs_verification": True}), last["content"])
        text = output.message
        for source in sources:
            if source.get("type") == "agent_generated" and not source.get("content"):
                source["content"] = text
                source["locator"] = f"task:{task['task_id']}" if task else f"run:{rid}"
        if "agent_generated" in types and "Agent 生成讲义" not in text:
            text = "来源：Agent 生成讲义（不作为独立外部证据）\n\n" + text
        if decision.needs_verification or evidence["state"] != "unverified":
            text += "\n\n证据状态：" + evidence["state"] + "；" + evidence["summary"]
        with self.store.transaction(sid, rid, rev) as data:
            task = self._task(data, data["runs"][rid])
            if teaching:
                data["runs"][rid]["activity_candidate"] = "lesson_step"
            elif node == "answer" and "question" in decision.intents:
                data["runs"][rid]["activity_candidate"] = "knowledge_answer"
            if task:
                task["context"]["evidence"] = evidence
                if teaching:
                    if output.learning_plan and (not task["context"].get("learning_plan") or "correction" in decision.intents):
                        set_plan(task, output.learning_plan.steps, output.learning_plan.success_check, output.learning_plan.step_ids)
                    elif not task["context"].get("learning_plan"):
                        set_plan(task, ["当前资料讲解"], output.check_question)
                    task["context"].setdefault("understanding_by_lesson", {})[str(task["context"].get("lesson_index", 0))] = task["context"].get("understanding", "unknown")
                    task["context"]["understanding"] = "unknown"
                    task["context"]["check_question"] = output.check_question
                    task["context"]["last_lesson"] = text
                    task["context"]["source_type"] = source_type
                    task["context"]["lesson_index"] = task["context"].get("lesson_index", 0) + 1
                if sources:
                    task["context"]["sources"] = sources
            self.store.event(data, data["runs"][rid], "sources", "来源类型已记录", payload={"sources": sources, "source_type": source_type})
        required = {"type": "submit_answer", "prompt": output.check_question, "options": []} if output.check_question else None
        if teaching:
            text += "\n\n你可以继续追问、尝试回答，或说“先跳过检查”；跳过不会标记为已掌握。"
        self._publish(sid, rid, rev, text, stage="teaching" if teaching else "organized" if draft and task else None,
                      task_status="completed" if draft and task and task["mode"] == "memory_organization" and not task["context"].get("requires_mastery") else "awaiting_user",
                      required=required, draft=draft, source_type=source_type)

    def _problem(self, sid, rid, rev, decision):
        data, run = self._snapshot(sid, rid, rev)
        task = self._task(data, run)
        if not task:
            raise ValueError("RT.TASK.UNKNOWN")
        if decision.is_jd:
            output = self._call(sid, rid, rev, "jd_analysis", JD_SYSTEM, task["content"], JDAnalysis)
            text = f"岗位目标\n{output.role_goal}\n\n能力地图\n" + "\n".join("- " + x for x in output.competency_map)
            text += "\n\n风险点\n" + "\n".join("- " + x for x in output.risk_points)
            text += "\n\n优先问题\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(output.prioritized_questions, 1))
            with self.store.transaction(sid, rid, rev) as data:
                data["pending"] = dict(kind="select_question", target_id=task["task_id"], version=1, options=output.prioritized_questions)
                self.store.event(data, data["runs"][rid], "question_choice", "请选择一道题", payload={"pending": data["pending"]})
            self._publish(sid, rid, rev, text, stage="jd_analysis", required={"type": "choose_question", "prompt": "先攻克哪一道？", "options": output.prioritized_questions})
            return
        evidence = self._evidence(sid, rid, rev, decision, task["content"])
        output = self._call(sid, rid, rev, "problem_answer", PROBLEM_SYSTEM,
                            json.dumps(dict(question=task["content"], evidence=evidence, context=task["context"]), ensure_ascii=False), ProblemCoachBundle)
        if output.answer.confidence == "low" and not decision.needs_verification:
            evidence = self._evidence(sid, rid, rev, decision.model_copy(update={"needs_verification": True}), task["content"])
        with self.store.transaction(sid, rid, rev) as data:
            task = self._task(data, data["runs"][rid])
            data["runs"][rid]["activity_candidate"] = "knowledge_answer"
            task["context"].update(reference_answer=output.answer.direct_answer, requires_mastery=True,
                                    evidence=evidence, calibration_question=output.analysis.calibration_question)
            set_plan(task, output.learning_plan.steps + ["独立作答", "迁移追问"], output.learning_plan.success_check,
                     (output.learning_plan.step_ids or [""] * len(output.learning_plan.steps)) + ["", ""])
        text = _render_problem(output)
        if evidence["state"] != "unverified":
            text += "\n\n证据状态：" + evidence["state"] + "；" + evidence["summary"]
        self._publish(sid, rid, rev, text, stage="calibration",
                      required={"type": "respond", "prompt": output.analysis.calibration_question, "options": []})

    def _evaluate(self, sid, rid, rev, decision, last):
        data, run = self._snapshot(sid, rid, rev)
        task = self._task(data, run)
        result = self._call(sid, rid, rev, "evaluate", EVALUATION_SYSTEM,
                            json.dumps(dict(question=task["context"].get("check_question") or task["content"],
                                            reference=task["context"].get("reference_answer", ""), answer=last["content"]), ensure_ascii=False), MasteryEvaluation)
        with self.store.transaction(sid, rid, rev) as data:
            task = self._task(data, data["runs"][rid])
            ctx = task["context"]
            data["runs"][rid]["evaluated_step_id"] = (ctx.get("learning_plan") or {}).get("current_step_id")
            previous_pass = ctx.get("independent_passed", False)
            hint_used = ctx.get("hint_used", False)
            if hint_used and result.passed:
                result.passed = False
                result.feedback += "\n这次使用过提示，不计为独立验证。请尝试下一道不带提示的追问。"
            if result.passed and ctx.get("requires_mastery"):
                if previous_pass and task["stage"] == "transfer":
                    ctx["transfer_passed"] = True
                    ctx["understanding"] = "verified"
                else:
                    ctx["independent_passed"] = True
            elif result.passed:
                record_understanding(task, "verified")
                steps = (ctx.get("learning_plan") or {}).get("steps", [])
                ctx["understanding"] = "verified" if all(s["understanding"] == "verified" for s in steps) else "unknown"
            ctx.setdefault("practice", []).append(dict(message_id=last["message_id"], hint_used=hint_used, evaluation=result.model_dump()))
            ctx["hint_used"] = False  # the next distinct check starts without a hint
            mastered = ctx.get("understanding") == "verified"
            plan = ctx.get("learning_plan")
            if plan and ctx.get("requires_mastery"):
                for step in plan["steps"]:
                    if mastered or step["title"] == "独立作答" and ctx.get("independent_passed"):
                        step.update(state="verified", understanding="verified")
                target = "迁移追问" if ctx.get("independent_passed") else "独立作答"
                selected = next((s for s in plan["steps"] if s["title"] == target), None)
                if selected:
                    plan["current_step_id"] = selected["id"]
            if ctx.get("requires_mastery"):
                record_understanding(task, ctx.get("understanding", "unknown"))
            ctx["check_question"] = result.followup_question or "请换一个应用场景，解释你的判断与局限。"
        if mastered:
            self._publish(sid, rid, rev, result.feedback + "\n\n这次理解检查已通过。是否要将确认过的内容加入知识库与复习？",
                          stage="mastered", task_status="completed", required={"type": "confirm_memory", "prompt": "是否加入知识库？", "options": []}, draft=True,
                          draft_content=ctx.get("reference_answer") or ctx.get("last_lesson") or task["content"], source_type=ctx.get("source_type"))
        elif result.passed and not ctx.get("requires_mastery"):
            self._publish(sid, rid, rev, result.feedback + "\n\n这一节的理解检查已通过。你可以继续下一节，也可以继续追问。",
                          stage="lesson_checked", required={"type": "respond", "prompt": "继续下一节或追问", "options": []})
        else:
            self._publish(sid, rid, rev, result.feedback + "\n\n请独立回答追问：" + ctx["check_question"], stage="transfer" if result.passed else "practice",
                          required={"type": "submit_answer", "prompt": ctx["check_question"], "options": []})

    def _sources(self, sid, rid, rev, goal):
        with self.store.transaction(sid, rid, rev) as data:
            self.store.event(data, data["runs"][rid], "source_search", "正在建立学习地图和互补资料包", model=COACH_MODEL)
        _, run = self._snapshot(sid, rid, rev)
        query = self._public_query((run.get("intent") or {}).get("public_search_query", ""))
        candidates = find_source_candidates(query, model=COACH_MODEL,
            model_runner=lambda system, prompt, schema, model=None: self._call(sid, rid, rev, "source_pack", system, prompt, schema, model or COACH_MODEL),
            search_runner=lambda text, model=None: self._search(sid, rid, rev, text, model or COACH_MODEL)) if query else []
        self._snapshot(sid, rid, rev)
        candidates = [c for c in candidates if looks_like_url(c.url)][:4]
        if len(candidates) < 2:
            self._publish(sid, rid, rev, "目前没有取得至少两个可定位的互补来源。你可以提供资料，或明确说“直接教我”，我会用标注来源的生成讲义。",
                          stage="awaiting_material", required={"type": "respond", "prompt": "提供资料或直接教学", "options": []})
            return
        with self.store.transaction(sid, rid, rev) as data:
            task = self._task(data, data["runs"][rid])
            task["context"]["learning_goal"] = goal
            task["context"]["source_pack"] = [c.model_dump() for c in candidates]
            data["pending"] = dict(kind="select_sources", target_id=task["task_id"], version=len(task["events"]) + 1, options=[c.url for c in candidates])
            self.store.event(data, data["runs"][rid], "source_choice", "资料包等你确认", payload={"pending": data["pending"],
                             "sources": [dict(type="public_source_candidate", url=c.url, title=c.title, content=c.snippet) for c in candidates]})
        text = "建议先建立基础概念，再看应用与局限。以下资料供确认后学习：\n\n" + "\n\n".join(f"{c.title}\n{c.url}\n{c.snippet}\n证据状态：待阅读核验；日期未知" for c in candidates)
        self._publish(sid, rid, rev, text, stage="source_confirmation", required={"type": "choose_sources", "prompt": "是否使用这些资料？", "options": []})

    @staticmethod
    def _public_query(value):
        value = value.strip()
        if not 2 <= len(value) <= 180 or re.search(r"(?:https?://|\bsk-|\bBearer\b|[^\s]+@[^\s]+|\d{7,}|-----BEGIN|(?:密钥|密码)\s*[:：])", value, re.I):
            return ""
        return value

    def _search(self, sid, rid, rev, query, model):
        data, run = self._snapshot(sid, rid, rev)
        strength = run.get("thinking_strength", data.get("thinking_strength", "smart"))
        key = hashlib.sha256((query + model + strength).encode()).hexdigest()
        if key in run.get("search_results", {}):
            return run["search_results"][key]
        handle_key = (sid, rid, rev)
        def register(handle):
            with self._worker_lock:
                self._cancel_handles[handle_key] = handle
            try:
                self._snapshot(sid, rid, rev)
            except Superseded:
                handle()
                raise
        started = time.monotonic()
        try:
            require_model(model)
            result = web_search_text(query, model=model, reasoning_effort="high" if strength == "deep" else None,
                                     on_cancel_handle=register)
            with self.store.transaction(sid, rid, rev) as current:
                current["runs"][rid].setdefault("search_results", {})[key] = result
                self.store.event(current, current["runs"][rid], "public_search", "公开资料检索已返回", model=model,
                                 duration_ms=int((time.monotonic() - started) * 1000))
            return result
        finally:
            with self._worker_lock:
                self._cancel_handles.pop(handle_key, None)

    def _save_memory(self, sid, rid, rev, decision):
        data, run = self._snapshot(sid, rid, rev)
        draft = data["draft"]
        task = self._task(data, run)
        if not draft or draft.get("invalidated"):
            self._publish(sid, rid, rev, "整理内容已变化，请先重新确认修订版，旧版本不会入库。", complete=False)
            return
        understood = draft["understanding"]
        if decision.understanding == "self_reported":
            understood = "self_reported"
        if understood == "unknown" or (task and task["context"].get("requires_mastery") and not task["context"].get("transfer_passed")):
            with self.store.transaction(sid, rid, rev) as data:
                if data.get("pending"):
                    data["pending"]["consent_received"] = True
            self._publish(sid, rid, rev, "已收到保存意愿，但理解条件还未满足。请先确认是否理解；问题攻克还需要独立作答和追问通过。", complete=False)
            return
        with self.store.transaction(sid, rid, rev) as data:
            run = data["runs"][rid]
            # Separate controlled commit task; do not regenerate the delivered draft.
            run["memory_references"] = draft.get("memory_references", [])
            commit_id = str(uuid.uuid5(uuid.UUID(sid), f"memory:{draft['id']}:{draft['version']}"))
            existing = data["tasks"].get(commit_id)
            if existing and existing["status"] in {"completed", "committing"}:
                self.store.event(data, run, "already_saved", "这个整理版本已提交，不会重复生成")
                return
            if not existing:
                record = HarnessTaskRecord(task_id=commit_id, session_id=sid, client_message_id=run["input_ids"][-1],
                                           content=draft["content"], content_type="text", primary_language="zh", mode_preset=data["mode"],
                                           mode="memory_organization", context=dict(conversation_managed=True, draft_id=draft["id"], draft_version=draft["version"],
                                                                                    source_type=draft["source_type"], origin_run_id=rid,
                                                                                    sources=(task or {}).get("context", {}).get("sources", []),
                                                                                    lifecycle_revision=data.get("lifecycle_revision", 0)))
                data["tasks"][commit_id] = asdict(record)
            run["task_id"] = commit_id
            data["active_task_id"] = commit_id
            self.store.event(data, run, "memory_generation", "正在提交已确认的整理版本", model=COACH_MODEL)
        def memory_model(system, prompt, schema, *, model=None):
            return self._call(sid, rid, rev, "memory_" + schema.__name__, system, prompt, schema, model or COACH_MODEL)

        def memory_search(_private_query, *, model=None):
            query = self._public_query(draft.get("public_search_query", ""))
            if not query:
                return ""
            _, current_run = self._snapshot(sid, rid, rev)
            if "memory_search" in current_run:
                return current_run["memory_search"]
            result = self._search(sid, rid, rev, query, model or RISK_MODEL)
            with self.store.transaction(sid, rid, rev) as current:
                current["runs"][rid]["memory_search"] = result
            return result

        result = run_capture(commit_id, draft["content"], "zh", force_source_view=draft["source_type"] in {"agent_generated", "mixed"},
                             model=COACH_MODEL, risk_model=RISK_MODEL, confirmed_content=True,
                             model_runner=memory_model, search_runner=memory_search)
        if result.get("outcome") == "retryable_failed":
            raise RuntimeError(result.get("error_code") or "RT.MEMORY.GENERATION_FAILED")
        with self.store.transaction(sid, rid, rev) as data:
            run = data["runs"][rid]
            task = data["tasks"][commit_id]
            if result.get("outcome") != "committing" or not result.get("extracted"):
                task.update(status="needs_attention", stage="knowledge_conflict", user_summary="证据不足或冲突，已暂停入库")
                self._project_event(data, run, task)
                self.store.event(data, run, "knowledge_conflict", "知识尚未入库", message="核验发现冲突或证据不足，已暂停写入；请补充资料或修订内容。")
                return
            task.update(memory_package=result["extracted"], memory_source_text=draft["content"], status="committing", stage="committing",
                        user_summary="已确认的知识等待本机保存", required_action=None)
            task["context"]["commit_revision"] = rev
            self._project_event(data, run, task)
            data["pending"] = None

    def _validate_commit(self, data, task):
        if data.get("status", "active") != "active" or task["context"].get("lifecycle_revision", 0) != data.get("lifecycle_revision", 0):
            raise ValueError("RT.TASK.COMMIT_REVOKED")
        if task["status"] not in {"committing", "completed"}:
            raise ValueError("RT.TASK.COMMIT_REVOKED")
        origin = data["runs"].get(task["context"].get("origin_run_id"))
        if origin and not self.store.memory_valid(origin.get("memory_references", [])):
            raise ValueError("RT.TASK.COMMIT_REVOKED")
        if origin and (origin["revision"] != task["context"].get("commit_revision") or origin["status"] in {"interrupted", "cancelled"}):
            raise ValueError("RT.TASK.COMMIT_REVOKED")

    def acknowledge_task(self, task_id, last_event_seq, knowledge_ids):
        record = self.store.tasks.get(task_id)
        if not record:
            raise ValueError("RT.TASK.UNKNOWN")
        # Permission, receipt and completion share the archive transaction lock.
        with self.store.transaction(record.session_id) as data:
            task = data["tasks"][task_id]
            if last_event_seq > len(task["events"]):
                raise ValueError("RT.TASK.ACK_AHEAD")
            if task["status"] == "committing":
                expected = {item.get("id") for item in (task.get("memory_package") or {}).get("knowledge", [])}
                if expected and set(knowledge_ids) != expected:
                    raise ValueError("RT.TASK.ACK_MISMATCH")
                # A claimed local atomic write may have finished before archive;
                # acknowledging it is not permission to restart generation.
                if not task["context"].get("commit_claimed"):
                    self._validate_commit(data, task)
                task.update(status="completed", stage="completed", user_summary="记忆已保存，学习任务完成",
                            required_action=None, error_code=None)
                task["events"].append(TaskEvent(
                    event_id=str(uuid.uuid4()), session_id=record.session_id, task_id=task_id,
                    seq=len(task["events"]) + 1, occurred_at=now_iso(), stage="completed", state="completed",
                    node="mac_ack", user_summary=task["user_summary"], detail_summary="Mac 已确认知识数据持久化。",
                    attempt=max(task.get("retry_count", 0) + 1, 1),
                ).model_dump())
            task["last_acked_seq"] = max(task["last_acked_seq"], last_event_seq)
        return self.store.tasks.get(task_id).view().model_dump()

    def claim_commit(self, task_id: str):
        record = self.store.tasks.get(task_id)
        if not record:
            raise ValueError("RT.TASK.UNKNOWN")
        with self.store.transaction(record.session_id) as data:
            task = data["tasks"][task_id]
            self._validate_commit(data, task)
            task["context"]["commit_claimed"] = True
            return HarnessTaskRecord(**task).view().model_dump()

    @staticmethod
    def public_run(run: dict) -> dict:
        return {key: value for key, value in run.items() if key not in {"steps", "action_ids"}}


conversation_harness = ConversationHarness()
