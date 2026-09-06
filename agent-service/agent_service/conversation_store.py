"""Durable turn outbox and revision-fenced Session transactions.

The Session checkpoint and its legacy Task projections share one SQLite commit.
The Mac owns long-lived history; server checkpoints are never deleted before ACK.
No model/network operation is allowed inside a transaction.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

from agent_service.harness_store import HarnessStore, harness_store, now_iso
from agent_service.checkpoint_delta import update_journal


class Superseded(Exception):
    """A stopped/revised run must not publish its late result."""


class ConversationStore:
    def __init__(self, tasks: HarnessStore = harness_store):
        self.tasks = tasks
        self._lock = tasks._lock
        with tasks._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS agent_sessions_v2 (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS agent_memory_policy_v2 (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def memory_policy(self, sid):
        with self._lock, self.tasks._connection() as db:
            row = db.execute("SELECT payload FROM agent_memory_policy_v2 WHERE session_id=?", (sid,)).fetchone()
            return json.loads(row[0]) if row else None

    def set_memory_policy(self, sid, value):
        with self._lock, self.tasks._connection() as db:
            row = db.execute("SELECT payload FROM agent_memory_policy_v2 WHERE session_id=?", (sid,)).fetchone()
            old = json.loads(row[0]) if row else None
            if old:
                if any(value[key] < old[key] for key in ("policy_version", "content_version")):
                    raise ValueError("RT.MEMORY.VERSION_CONFLICT")
                if value["policy_version"] == old["policy_version"] and value["allowed"] != old["allowed"]:
                    raise ValueError("RT.MEMORY.VERSION_CONFLICT")
            db.execute("INSERT INTO agent_memory_policy_v2 VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload", (sid, json.dumps(value)))

    def memory_valid(self, refs, depth=0):
        if depth > 6:
            return False
        for ref in refs:
            if ref.get("knowledge_id"):
                continue  # Mac owns the final formal-card version check.
            policy = self.memory_policy(ref.get("session_id"))
            if not policy or not policy["allowed"] or any(policy[key] != ref.get(key) for key in ("policy_version", "content_version")):
                return False
            if not self.memory_valid(ref.get("dependencies", []), depth + 1):
                return False
        return True

    @staticmethod
    def empty(session_id: str) -> dict:
        return dict(session_id=session_id, mode="auto", paused=False, foreground=None,
                    active_task_id=None, messages=[], runs={}, events=[], last_acked_seq=0,
                    tasks={}, pending=None, draft=None, summary="", summary_version=0, event_base_seq=0,
                    status="active", lifecycle_revision=0, lifecycle_actions={})

    def get(self, session_id: str) -> dict | None:
        with self._lock, self.tasks._connection() as db:
            row = db.execute("SELECT payload FROM agent_sessions_v2 WHERE session_id=?", (session_id,)).fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            task_rows = db.execute("SELECT task_id, payload FROM harness_tasks WHERE session_id=?", (session_id,)).fetchall()
            data["tasks"] = {task_id: json.loads(payload) for task_id, payload in task_rows}
            return data

    @contextmanager
    def transaction(self, session_id: str, run_id: str | None = None, revision: int | None = None):
        with self._lock:
            data = self.get(session_id)
            if data is None:
                data = self.empty(session_id)
                # A legacy Session can already own Tasks before its first Run.
                # Import those projections without pretending an unknown Session
                # exists in GET/ACK or copying another Session's task context.
                with self.tasks._connection() as db:
                    rows = db.execute("SELECT task_id, payload FROM harness_tasks WHERE session_id=?", (session_id,)).fetchall()
                    data["tasks"] = {key: json.loads(value) for key, value in rows}
            prior_tasks = {key: json.dumps(value, ensure_ascii=False) for key, value in data["tasks"].items()}
            prior_payload = json.dumps({k: v for k, v in data.items() if k != "tasks"}, ensure_ascii=False)
            if run_id is not None:
                run = data["runs"].get(run_id)
                if (data.get("status", "active") != "active" or not run or run["revision"] != revision
                        or run["status"] != "running"
                        or run.get("lifecycle_revision", 0) != data.get("lifecycle_revision", 0)):
                    raise Superseded()
            yield data
            if run_id is not None and (data["runs"][run_id].get("memory_invalidated") or not self.memory_valid(data["runs"][run_id].get("memory_references", []))):
                raise Superseded()
            # Both projections are committed together; an exception above writes neither.
            with self.tasks._connection() as db:
                for task in data["tasks"].values():
                    if prior_tasks.get(task["task_id"]) == json.dumps(task, ensure_ascii=False):
                        continue
                    task["updated_at"] = now_iso()
                    db.execute(
                        "INSERT INTO harness_tasks VALUES (?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET updated_at=excluded.updated_at, payload=excluded.payload",
                        (task["task_id"], session_id, task["client_message_id"], task["updated_at"], json.dumps(task, ensure_ascii=False)),
                    )
                # Journal the committed state, including mutations after the last
                # visible event. ACK may trim transport copies, never the Mac's
                # recoverable state. Appends avoid resending whole streamed text.
                update_journal(data)
                payload = {k: v for k, v in data.items() if k != "tasks"}
                encoded = json.dumps(payload, ensure_ascii=False)
                if encoded != prior_payload or not self.get(session_id):
                    db.execute("INSERT INTO agent_sessions_v2 VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload", (session_id, encoded))

    @staticmethod
    def last_seq(data: dict) -> int:
        return data.get("event_base_seq", 0) + len(data["events"])

    def compact_acknowledged(self, data: dict):
        # The Mac stores the visible snapshot atomically before ACK. Keep event
        # metadata without retaining O(n²) answer copies in Python checkpoints.
        for event in data["events"]:
            if event["seq"] <= data["last_acked_seq"] and event["stage"] == "response.delta":
                response = event.get("payload", {}).get("response")
                if response:
                    response["text"] = ""
                    response["delta"] = ""
        removable = [e for e in data["events"][:-64] if e["seq"] <= data["last_acked_seq"]]
        if removable:
            data["event_base_seq"] = removable[-1]["seq"]
            data["events"] = data["events"][len(removable):]
        required = {mid for run in data["runs"].values() if run["status"] != "completed" for mid in run["input_ids"]}
        first_required = next((i for i, message in enumerate(data["messages"]) if message["message_id"] in required), len(data["messages"]))
        # A slow/failed background summary must never discard unsummarized context.
        count = min(max(0, len(data["messages"]) - 32), first_required, data.get("summarized_count", 0))
        if count:
            data["messages"] = data["messages"][count:]
            data["summarized_count"] = max(0, data.get("summarized_count", 0) - count)
            retained = {m["message_id"] for m in data["messages"]}
            data["summarized_message_ids"] = [mid for mid in data.get("summarized_message_ids", []) if mid in retained]
        for run in data["runs"].values():
            task = data["tasks"].get(run.get("task_id"))
            referenced = task and (task["status"] not in {"completed", "cancelled", "terminal_failed"} or
                                   task["task_id"] == data.get("active_task_id"))
            referenced = referenced or bool(data.get("draft") and not data["draft"].get("invalidated"))
            if run["status"] == "completed" and not referenced and not any(e["run_id"] == run["run_id"] and e["seq"] > data["last_acked_seq"] for e in data["events"]):
                run["steps"] = {}

    def sessions(self) -> list[str]:
        with self._lock, self.tasks._connection() as db:
            return [row[0] for row in db.execute("SELECT session_id FROM agent_sessions_v2")]

    def locate_run(self, run_id: str) -> dict | None:
        for session_id in self.sessions():
            data = self.get(session_id)
            if run_id in data["runs"]:
                return data
        return None

    @staticmethod
    def event(data: dict, run: dict, stage: str, summary: str, *, message: str = "",
              detail: str = "", model: str = "", duration_ms: int | None = None,
              error: str | None = None, payload: dict | None = None,
              message_id: str | None = None) -> dict:
        event = dict(event_id=str(uuid.uuid4()), session_id=data["session_id"], run_id=run["run_id"],
                     task_id=run.get("task_id"), seq=ConversationStore.last_seq(data) + 1, occurred_at=now_iso(),
                     revision=run["revision"], lifecycle_revision=data.get("lifecycle_revision", 0), stage=stage, state=run["status"], node=stage,
                     user_summary=summary, detail_summary=detail, model=model,
                     attempt=run["attempt"], duration_ms=duration_ms, error_code=error,
                     payload=payload or {}, message=None)
        if message:
            event["message"] = dict(message_id=message_id or str(uuid.uuid4()), role="coach", content=message, created_at=event["occurred_at"])
            data["messages"].append(dict(event["message"], run_id=run["run_id"], task_id=run.get("task_id")))
        data["events"].append(event)
        if not stage.startswith("response."):
            run.update(stage=stage, user_summary=summary, error_code=error, updated_at=event["occurred_at"])
        return event


conversation_store = ConversationStore()
