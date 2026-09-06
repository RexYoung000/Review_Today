from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_service.config import HARNESS_DB
from agent_service.schemas import LearningTaskView, TaskEvent

execution_epoch = ContextVar("legacy_execution_epoch", default=None)


class StaleExecution(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HarnessTaskRecord:
    task_id: str
    session_id: str
    client_message_id: str
    content: str
    content_type: str
    primary_language: str
    mode_preset: str
    context: dict[str, Any] = field(default_factory=dict)
    mode: str = "auto"
    status: str = "accepted"
    stage: str = "accepted"
    user_summary: str = "已接收，准备处理"
    retry_count: int = 0
    error_code: str | None = None
    required_action: dict[str, Any] | None = None
    result_summary: str = ""
    memory_package: dict[str, Any] | None = None
    memory_source_text: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    processed_action_ids: list[str] = field(default_factory=list)
    completed_action_ids: list[str] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    last_acked_seq: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def view(self) -> LearningTaskView:
        return LearningTaskView(
            lifecycle_revision=self.context.get("lifecycle_revision", 0),
            learning_plan_json=json.dumps(self.context["learning_plan"], ensure_ascii=False) if self.context.get("learning_plan") else None,
            learning_outcome_json=json.dumps(self.context["learning_outcome"], ensure_ascii=False) if self.context.get("learning_outcome") else None,
            sources_json=json.dumps(self.context["sources"], ensure_ascii=False) if self.context.get("sources") else None,
            memory_references_json=json.dumps(self.context.get("memory_references", []), ensure_ascii=False),
            draft_target_id=self.context.get("draft_id"),
            run_id=self.context.get("latest_run_id"),
            understanding=self.context.get("understanding", "unknown"),
            task_id=self.task_id,
            session_id=self.session_id,
            client_message_id=self.client_message_id,
            mode=self.mode,
            status=self.status,
            stage=self.stage,
            user_summary=self.user_summary,
            retry_count=self.retry_count,
            error_code=self.error_code,
            required_action=self.required_action,
            result_summary=self.result_summary,
            last_event_seq=len(self.events),
            last_acked_seq=self.last_acked_seq,
            memory_package=self.memory_package,
            memory_source_text=self.memory_source_text,
        )


class HarnessStore:
    def __init__(self, path: str = HARNESS_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS agent_session_deletions (session_id TEXT PRIMARY KEY, action_id TEXT NOT NULL, lifecycle_revision INTEGER NOT NULL, deleted_at TEXT NOT NULL)")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS harness_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    client_message_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(session_id, client_message_id)
                )
                """
            )

    def _save_unlocked(self, record: HarnessTaskRecord) -> None:
        epoch = execution_epoch.get()
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM agent_session_deletions WHERE session_id=?", (record.session_id,)).fetchone():
                raise ValueError("RT.SESSION.DELETED")
            table = connection.execute("SELECT name FROM sqlite_master WHERE name='agent_sessions_v2'").fetchone()
            row = connection.execute("SELECT payload FROM agent_sessions_v2 WHERE session_id=?", (record.session_id,)).fetchone() if table else None
        if epoch and row:
            session = json.loads(row[0])
            if session.get("status", "active") != "active" or epoch != (record.session_id, session.get("lifecycle_revision", 0)):
                raise StaleExecution()
        record.updated_at = now_iso()
        payload = json.dumps(asdict(record), ensure_ascii=False)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO harness_tasks(task_id, session_id, client_message_id, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (record.task_id, record.session_id, record.client_message_id, record.updated_at, payload),
            )

    @staticmethod
    def _decode(payload: str) -> HarnessTaskRecord:
        return HarnessTaskRecord(**json.loads(payload))

    def get(self, task_id: str) -> HarnessTaskRecord | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM harness_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return self._decode(row[0]) if row else None

    def get_by_message(self, session_id: str, client_message_id: str) -> HarnessTaskRecord | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM harness_tasks WHERE session_id = ? AND client_message_id = ?",
                (session_id, client_message_id),
            ).fetchone()
            return self._decode(row[0]) if row else None

    def create(self, record: HarnessTaskRecord) -> tuple[HarnessTaskRecord, bool]:
        with self._lock:
            existing = self.get_by_message(record.session_id, record.client_message_id)
            if existing:
                return existing, False
            self._save_unlocked(record)
            return record, True

    def save(self, record: HarnessTaskRecord) -> None:
        with self._lock:
            self._save_unlocked(record)

    def mutate(self, task_id: str, operation) -> HarnessTaskRecord | None:
        with self._lock:
            record = self.get(task_id)
            if record is None:
                return None
            operation(record)
            self._save_unlocked(record)
            return record

    def append_event(
        self,
        task_id: str,
        *,
        stage: str,
        state: str,
        node: str,
        user_summary: str,
        detail_summary: str = "",
        duration_ms: int | None = None,
        error_code: str | None = None,
        recovery_action: str | None = None,
        required_action: dict[str, Any] | None = None,
        message: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> TaskEvent | None:
        result: TaskEvent | None = None

        def apply(record: HarnessTaskRecord) -> None:
            nonlocal result
            event = TaskEvent(
                event_id=str(uuid.uuid4()),
                session_id=record.session_id,
                task_id=record.task_id,
                seq=len(record.events) + 1,
                occurred_at=now_iso(),
                stage=stage,
                state=state,
                node=node,
                user_summary=user_summary,
                detail_summary=detail_summary,
                attempt=max(record.retry_count + 1, 1),
                duration_ms=duration_ms,
                error_code=error_code,
                recovery_action=recovery_action,
                required_action=required_action,
                message=message,
                payload=payload or {},
            )
            record.events.append(event.model_dump())
            record.stage = stage
            record.status = state
            record.user_summary = user_summary
            record.error_code = error_code
            record.required_action = required_action
            result = event

        self.mutate(task_id, apply)
        return result

    def events_after(self, task_id: str, after_seq: int) -> list[TaskEvent] | None:
        record = self.get(task_id)
        if record is None:
            return None
        return [TaskEvent.model_validate(item) for item in record.events if item["seq"] > after_seq]

    def acknowledge(self, task_id: str, seq: int) -> HarnessTaskRecord | None:
        def apply(record: HarnessTaskRecord) -> None:
            if seq > len(record.events):
                raise ValueError("RT.TASK.ACK_AHEAD")
            record.last_acked_seq = max(record.last_acked_seq, seq)

        return self.mutate(task_id, apply)

    def cleanup(self, terminal_ttl_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=terminal_ttl_days)).isoformat()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT task_id, payload FROM harness_tasks WHERE updated_at < ?", (cutoff,)
            ).fetchall()
            terminal = []
            for task_id, payload in rows:
                record = json.loads(payload)
                session_table = connection.execute("SELECT name FROM sqlite_master WHERE name='agent_sessions_v2'").fetchone()
                session = connection.execute("SELECT payload FROM agent_sessions_v2 WHERE session_id=?", (record["session_id"],)).fetchone() if session_table else None
                # Session-owned tasks are needed for snapshots, plan/source refs and
                # resumable context. Only orphaned, fully ACKed terminal projections
                # may be aged out. Age alone is never a deletion condition.
                if (not session and record.get("status") in {"completed", "cancelled", "terminal_failed"}
                        and record.get("last_acked_seq", 0) >= len(record.get("events", []))):
                    terminal.append((task_id,))
            connection.executemany("DELETE FROM harness_tasks WHERE task_id = ?", terminal)
            return len(terminal)

    def all_records(self) -> list[HarnessTaskRecord]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT payload FROM harness_tasks ORDER BY updated_at").fetchall()
            return [self._decode(row[0]) for row in rows]


harness_store = HarnessStore()
