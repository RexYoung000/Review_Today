"""Durable run/session controls, idempotency and cancellation fences."""
from __future__ import annotations
import hashlib
import json
import threading
from agent_service.schemas import RunActionRequest

LABELS = {"auto": "Auto", "memory_organization": "知识整理", "source_learning": "资料学习",
          "topic_exploration": "主题探索", "problem_solving": "问题攻克"}
FINISHED = {"completed", "cancelled", "terminal_failed"}


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
    if action == "delete":
        result = self.store.delete(sid, action_id, lifecycle_revision)
        with self._worker_lock:
            handles = [h for key, h in self._cancel_handles.items() if key[0] == sid]
        for handle in handles:
            handle()
        # Remove dependent recall/checkpoints in surviving Sessions too.
        for owner in self.store.sessions():
            with self.store.transaction(owner) as data:
                self._invalidate_memory(data)
                for run in data["runs"].values():
                    if run.get("memory_invalidated"):
                        run["steps"] = {}
                        run.pop("memory_lookup", None)
                        if run["status"] in {"running", "accepted", "queued"}:
                            self._stop(data, run)
        return result
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


def cancel_older(self, sid, rid, revision):
    with self._worker_lock:
        handles = [handle for key, handle in self._cancel_handles.items() if key[:2] == (sid, rid) and key[2] != revision]
    for handle in handles:
        # Closing a transport can block; never delay the durable control ACK.
        def close(callback=handle):
            try: callback()
            except Exception: pass
        threading.Thread(target=close, daemon=True).start()


def stop(self, data: dict, run: dict, *, cancel: bool = False):
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
