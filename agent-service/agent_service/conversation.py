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

    def accept(self, session_id: str, body: SessionMessageRequest) -> MessageAccepted:
        with self.store.transaction(session_id) as data:
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
            run = data["runs"][run_id]
            if body.action_id in run["action_ids"]:
                return dict(run)
            run["action_ids"].append(body.action_id)
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
                    run["status"] = "accepted"
                    data["foreground"] = run_id
                self.store.event(data, run, "resuming", "已恢复，将从未完成的步骤继续")
            result = dict(run)
        self._cancel_older(found["session_id"], target["run_id"], target["revision"])
        return result

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

    def recover(self):
        for session_id in self.store.sessions():
            with self.store.transaction(session_id) as data:
                for run in data["runs"].values():
                    if run["status"] == "running":
                        if run.get("active_response") and not run.get("execution_complete"):
                            self._stop(data, run)
                            self.store.event(data, run, "interrupted", "服务中断，已保留未完成内容；继续后重试未完成步骤")
                            continue
                        run["revision"] += 1
                        run["status"] = "accepted"
                        self.store.event(data, run, "recovering", "服务已恢复，将续接未完成步骤")
            self.start(session_id)

    def drain(self, session_id: str):
        """Synchronous worker entry for deterministic tests; one worker per Session."""
        while True:
            with self.store.transaction(session_id) as data:
                run = data["runs"].get(data["foreground"])
                if data["paused"] and not (run and run.get("paused_entry") and run["status"] == "accepted"):
                    return
                if not run or run["status"] not in {"accepted", "queued"}:
                    run = next((r for r in data["runs"].values() if r["status"] in {"accepted", "queued"}), None)
                if not run:
                    return
                data["foreground"] = run["run_id"]
                run["status"] = "running"
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
                self._compress(session_id, run_id, revision)
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
                            data["pending"] = None
                        self._project_event(data, run, task)
                    self._freeze_clock(run)
                    run["status"] = "completed"
                    run["activity_kind"] = self._activity_kind(data, run)
                    run["completed_at"] = now_iso() if run["activity_kind"] else None
                    self.store.event(data, run, "completed", "本轮已回应")
                    data["foreground"] = None
            except Superseded:
                continue
            except Exception as exc:  # each failure is persisted, not swallowed as a blank UI
                try:
                    with self.store.transaction(session_id, run_id, revision) as data:
                        run = data["runs"][run_id]
                        code = exc.code if isinstance(exc, ModelCallError) else (
                            str(exc) if str(exc).startswith("RT.") else "RT.RUN.EXECUTION_FAILED")
                        self._end_response(data, run, "failed")
                        self._freeze_clock(run)
                        run["status"] = "retryable_failed"
                        task = self._task(data, run)
                        if task and task["status"] not in FINISHED | {"committing"}:
                            task.update(status="retryable_failed", user_summary="当前步骤未完成，可重试；学习进度保留", error_code=code)
                            self._project_event(data, run, task)
                        self.store.event(data, run, "failed", "这一步暂时无法完成，可重试；输入和进度已保留",
                                         error=code, detail=getattr(exc, "diagnostic", type(exc).__name__))
                        data["foreground"] = None
                        data["paused"] = True
                except Superseded:
                    pass

    def _snapshot(self, session_id, run_id, revision):
        data = self.store.get(session_id)
        run = data["runs"][run_id]
        if run["revision"] != revision or run["status"] != "running":
            raise Superseded()
        return data, run

    def _compress(self, sid, rid, rev):
        data, run = self._snapshot(sid, rid, rev)
        end = len(data["messages"]) - 12
        if end - data.get("summarized_count", 0) < 12:
            return
        older = [dict(role=m["role"], content=m["content"][:3000]) for m in data["messages"][data.get("summarized_count", 0):end]]
        output = self._call(sid, rid, rev, "session_summary",
                            "压缩本 Session 已发生的对话为交接摘要。保留目标、用户明确决定、未解决问题；不要把生成内容或条件句当作用户确认。不推断理解或保存授权。",
                            json.dumps(dict(previous=data["summary"], messages=older), ensure_ascii=False), ConversationSummary, ROUTER_MODEL)
        with self.store.transaction(sid, rid, rev) as data:
            data["summary"] = output.summary[:10000]
            data["summary_version"] += 1
            data["summarized_count"] = end
            self.store.event(data, data["runs"][rid], "session_summary", "上下文摘要已更新，原文仍保留",
                             payload={"session_summary": dict(output.model_dump(), version=data["summary_version"])})

    def _call(self, session_id, run_id, revision, node, system, prompt, schema, model=COACH_MODEL):
        data, run = self._snapshot(session_id, run_id, revision)
        key = hashlib.sha256((node + system + prompt + model).encode()).hexdigest()
        if key in run["steps"]:
            return schema.model_validate(run["steps"][key])
        with self.store.transaction(session_id, run_id, revision) as data:
            self.store.event(data, data["runs"][run_id], node,
                             {"intent": "正在理解本轮意图", "evaluate": "正在评价这次独立作答",
                              "answer": "正在准备回答", "lesson": "正在准备讲解", "organize": "正在整理知识关系",
                              "problem_answer": "正在组织基础答案与学习路径", "jd_analysis": "正在拆解岗位要求",
                              "evidence_assessment": "正在核验回答依据", "session_summary": "正在整理会话摘要"}.get(node, "正在处理当前步骤"), model=model)
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
            parsed = parse_model(system, prompt, schema, model=model, on_cancel_handle=register_cancel,
                                 **({"on_partial": emit, "on_transport": transport} if streamable else {}))
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
        task["context"]["latest_run_id"] = run["run_id"]
        event = TaskEvent(event_id=str(uuid.uuid4()), session_id=data["session_id"], task_id=task["task_id"],
                          seq=len(task["events"]) + 1, occurred_at=now_iso(), stage=task["stage"], state=task["status"],
                          node=task["stage"], user_summary=task["user_summary"], attempt=max(run["attempt"], 1),
                          required_action=task["required_action"], message=message)
        task["events"].append(event.model_dump())
        self.store.event(data, run, "task_updated", task["user_summary"],
                         payload={"task": HarnessTaskRecord(**task).view().model_dump()})

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
                task.update(stage=stage, status=task_status, user_summary="已交付整理结果" if task_status == "completed" else "等你继续",
                            required_action=required)
                self._project_event(data, run, task, event["message"])
            if draft:
                previous = (task["context"].get("draft") if task else data.get("draft")) or {}
                value = dict(id=task["task_id"] if task else rid, version=previous.get("version", 0) + 1,
                             content=draft_content or text, understanding=(task["context"].get("understanding", "unknown") if task else "unknown"),
                             source_type=source_type or "user_material")
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
        # Explicit structured state is never compressed into model prose. Limit only
        # the narrative window; local Mac retains the complete original transcript.
        eligible = [m for m in data["messages"] if m not in selected and data["runs"].get(m.get("run_id"), {}).get("status") != "queued"]
        recent = [dict(message_id=m["message_id"], role=m["role"], content=m["content"][:3000]) for m in eligible[-16:]]
        external = last.get("context", {})
        return dict(mode=data["mode"], session_goal=data.get("focus_goal", ""),
                    current_inputs=[run["resolved_input"]] if run.get("resolved_input") else [m["content"] for m in selected], task=task_context,
                    pending=data["pending"], draft=data["draft"], summary=data["summary"] or external.get("summary", ""),
                    recent_messages=recent or external.get("recent_messages", [])[-10:],
                    related_knowledge=external.get("knowledge_summaries", [])[:5]), last

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
                                 detail=decision.rationale, payload={"intent": decision.model_dump()})
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
            self.store.event(data, run, "intent_decided", "已理解本轮要求", detail=decision.rationale,
                             model="" if last.get("operation") else ROUTER_MODEL, payload={"intent": decision.model_dump()})
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
        if intents <= {"greeting", "thanks", "capabilities"}:
            self._respond(sid, rid, rev, decision, "自然回应；不要展开学习流程。", node="answer")
            return
        if task and task["status"] not in {"cancelled", "terminal_failed"}:
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
                        package = dict(handoff_id=f"{pending['target_id']}:{pending['version']}", goal=pending["content"],
                                       mode=data["mode"], source_session_id=sid,
                                       summary="用户确认的新目标：" + pending["content"][:2000],
                                       source_refs=[], knowledge_refs=[], open_questions=[])
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
        evidence = web_search_text("核验并附可定位来源：" + text[:3000], model=RISK_MODEL)
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
        sources = []
        urls = (task["context"].get("selected_sources", []) if task else [])
        if "material" in decision.intents and looks_like_url(last["content"]):
            urls = [looks_like_url(last["content"])]
        for url in urls[:4]:
            title, body = fetch_public_url(url)
            sources.append(dict(type="public_source", url=url, title=title, content=body[:10000]))
            self._snapshot(sid, rid, rev)
        evidence = self._evidence(sid, rid, rev, decision, last["content"])
        source_type = "agent_generated" if generated else "public_source" if sources else "user_material"
        output = self._call(sid, rid, rev, node, COACH_SYSTEM,
                            json.dumps(dict(instruction=instruction, context=context, sources=sources,
                                            source_type=source_type, evidence=evidence), ensure_ascii=False), ConversationOutput)
        if output.evidence_state in {"insufficient", "conflicting", "outdated"} and not decision.needs_verification:
            evidence = self._evidence(sid, rid, rev, decision.model_copy(update={"needs_verification": True}), last["content"])
        text = output.message
        if generated and "Agent 生成讲义" not in text:
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
            previous_pass = ctx.get("independent_passed", False)
            if result.passed and ctx.get("requires_mastery"):
                if previous_pass and task["stage"] == "transfer":
                    ctx["transfer_passed"] = True
                    ctx["understanding"] = "verified"
                else:
                    ctx["independent_passed"] = True
            elif result.passed:
                ctx["understanding"] = "verified"
            ctx.setdefault("practice", []).append(dict(message_id=last["message_id"], evaluation=result.model_dump()))
            mastered = ctx.get("understanding") == "verified"
            ctx["check_question"] = result.followup_question or "请换一个应用场景，解释你的判断与局限。"
        if mastered:
            self._publish(sid, rid, rev, result.feedback + "\n\n这次理解检查已通过。是否要将确认过的内容加入知识库与复习？",
                          stage="mastered", required={"type": "confirm_memory", "prompt": "是否加入知识库？", "options": []}, draft=True,
                          draft_content=ctx.get("reference_answer") or ctx.get("last_lesson") or task["content"], source_type=ctx.get("source_type"))
        else:
            self._publish(sid, rid, rev, result.feedback + "\n\n请独立回答追问：" + ctx["check_question"], stage="transfer" if result.passed else "practice",
                          required={"type": "submit_answer", "prompt": ctx["check_question"], "options": []})

    def _sources(self, sid, rid, rev, goal):
        with self.store.transaction(sid, rid, rev) as data:
            self.store.event(data, data["runs"][rid], "source_search", "正在建立学习地图和互补资料包", model=COACH_MODEL)
        candidates = find_source_candidates(goal[:1000])
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
            commit_id = str(uuid.uuid5(uuid.UUID(sid), f"memory:{draft['id']}:{draft['version']}"))
            existing = data["tasks"].get(commit_id)
            if existing and existing["status"] in {"completed", "committing"}:
                self.store.event(data, run, "already_saved", "这个整理版本已提交，不会重复生成")
                return
            if not existing:
                record = HarnessTaskRecord(task_id=commit_id, session_id=sid, client_message_id=run["input_ids"][-1],
                                           content=draft["content"], content_type="text", primary_language="zh", mode_preset=data["mode"],
                                           mode="memory_organization", context=dict(conversation_managed=True, draft_id=draft["id"], draft_version=draft["version"],
                                                                                    source_type=draft["source_type"], origin_run_id=rid))
                data["tasks"][commit_id] = asdict(record)
            run["task_id"] = commit_id
            data["active_task_id"] = commit_id
            self.store.event(data, run, "memory_generation", "正在提交已确认的整理版本", model=COACH_MODEL)
        result = run_capture(commit_id, draft["content"], "zh", force_source_view=draft["source_type"] == "agent_generated",
                             model=COACH_MODEL, risk_model=RISK_MODEL)
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

    def claim_commit(self, task_id: str):
        record = self.store.tasks.get(task_id)
        if not record:
            raise ValueError("RT.TASK.UNKNOWN")
        with self.store.transaction(record.session_id) as data:
            task = data["tasks"][task_id]
            if task["status"] not in {"committing", "completed"}:
                raise ValueError("RT.TASK.COMMIT_REVOKED")
            task["context"]["commit_claimed"] = True
            return HarnessTaskRecord(**task).view().model_dump()

    @staticmethod
    def public_run(run: dict) -> dict:
        return {key: value for key, value in run.items() if key not in {"steps", "action_ids"}}


conversation_harness = ConversationHarness()
