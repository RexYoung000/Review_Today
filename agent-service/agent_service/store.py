from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_service.schemas import (
    CaptureTaskView,
    ExtractPayload,
    Receipt,
    SourceCandidate,
    TaskStatus,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    source_id: str
    raw_text: str
    primary_language: str
    input_type: str = "text"
    url: str | None = None
    status: TaskStatus = "processing"
    user_status: str = "正在整理"
    error_code: str | None = None
    receipt: Receipt | None = None
    result: ExtractPayload | None = None
    intent: str | None = None
    source_candidates: list[SourceCandidate] = field(default_factory=list)
    verify_reason: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=_now)
    acked: bool = False
    force_source_view: bool = False

    def view(self) -> CaptureTaskView:
        show_result = self.status in {"committing", "completed"} or self.error_code in {
            "RT.CAPTURE.CONFLICT",
            "RT.CAPTURE.VERIFY_INSUFFICIENT",
        }
        return CaptureTaskView(
            task_id=self.task_id,
            status=self.status,
            user_status=self.user_status,
            error_code=self.error_code,
            receipt=self.receipt,
            result=self.result if show_result else None,
            source_id=self.source_id,
            intent=self.intent,
            source_candidates=list(self.source_candidates),
            verify_reason=self.verify_reason,
            events=list(self.events),
        )


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._erased: set[str] = set()

    def erase(self, task_ids: list[str]) -> None:
        with self._lock:
            for task_id in task_ids:
                self._erased.add(task_id)
                self._tasks.pop(task_id, None)

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def put(self, record: TaskRecord) -> None:
        with self._lock:
            if record.task_id in self._erased:
                return
            record.updated_at = _now()
            self._tasks[record.task_id] = record

    def upsert_new(self, record: TaskRecord) -> tuple[TaskRecord, bool]:
        with self._lock:
            if record.task_id in self._erased:
                raise ValueError("RT.CAPTURE.DELETED_TASK")
            existing = self._tasks.get(record.task_id)
            if existing is not None:
                return existing, False
            self._tasks[record.task_id] = record
            return record, True


store = TaskStore()
