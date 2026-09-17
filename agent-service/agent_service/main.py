"""Review Today local service.

Harness V2:
POST /v2/sessions/{session_id}/turns
GET /v2/tasks/{task_id}
GET /v2/tasks/{task_id}/events?after_seq=
POST /v2/tasks/{task_id}/actions
POST /v2/tasks/{task_id}/ack
POST /v2/capabilities/probe

V1 compatibility:
POST /v1/capture/tasks
  body: {task_id, source_id, input_type, raw_text, url, primary_language, audio_base64, audio_format}
  200: CaptureTaskView
  Idempotent on task_id.

GET /v1/capture/tasks/{task_id}
POST /v1/capture/tasks/{task_id}/ack
POST /v1/capture/tasks/{task_id}/actions
  actions: reprocess, paste, attach_url, find_sources, confirm_sources,
           adopt_limited, as_source_view, keep_paused, delete, confirm_transcript

POST /v1/review/grade
POST /v1/review/attempts/{attempt_id}/ack

Statuses: processing → committing → completed
          retryable_failed | needs_attention | cancelled
"""

from __future__ import annotations

import base64
import asyncio
import json
import threading
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError, BaseModel, Field
from typing import Literal

from agent_service.capture import find_source_candidates, run_capture, source_fidelity_issues
from agent_service.capture.fetch import looks_like_url
from agent_service.config import CA_BUNDLE, HOST, PORT, PROVIDER, openai_key
from agent_service.harness import process_task, resume_incomplete_tasks
from agent_service.harness_store import HarnessTaskRecord, harness_store, now_iso
from agent_service.model_capabilities import snapshot as model_capability_snapshot, start_probe
from agent_service.openai_client import transcribe_audio
from agent_service.review import grade_answer
from agent_service.schemas import (
    CaptureAckRequest,
    CaptureActionRequest,
    CaptureSubmitRequest,
    ExtractPayload,
    GradeAckRequest,
    GradeRequest,
    GradeResult,
    LearningTaskView,
    Receipt,
    SessionTurnAccepted,
    SessionTurnRequest,
    TaskAckRequest,
    TaskActionRequest,
    TaskEventPage,
)
from agent_service.store import TaskRecord, store
from agent_service.conversation import conversation_harness
from agent_service.checkpoint_delta import recovery_page
from agent_service.topic_capture import public as public_capture_offer
from agent_service.schemas import SessionMessageRequest, RunActionRequest, SessionAckRequest, MessageAccepted

from agent_service.dictation import router as dictation_router

app = FastAPI(title="Review Today Agent", docs_url=None, redoc_url=None)
app.include_router(dictation_router)
_grade_results: dict[str, GradeResult] = {}
_grade_acks: set[str] = set()
_grade_lock = threading.Lock()


@app.on_event("startup")
def check_model_capabilities() -> None:
    start_probe()
    threading.Thread(target=resume_incomplete_tasks, name="review-today-task-recovery", daemon=True).start()
    threading.Thread(target=conversation_harness.recover, name="review-today-run-recovery", daemon=True).start()


@app.get("/healthz")
def healthz() -> dict[str, object]:
    from agent_service.web_tools import web_search_capability, web_read_capability
    return {
        "status": "ok",
        "key_configured": bool(openai_key()),
        "provider": PROVIDER,
        "ca_bundle": bool(CA_BUNDLE),
        "harness": "v2",
        "conversation_protocol": 1,
        "response_stream_protocol": 1,
        "model_roles": model_capability_snapshot(),
        "web_search": web_search_capability(),
        "web_read": web_read_capability(),
    }


@app.post("/v2/capabilities/probe")
def reprobe_model_capabilities() -> dict[str, object]:
    start_probe()
    return {"status": "checking", "model_roles": model_capability_snapshot()}


def _http_error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": message})


def _require_uuid(value: str, *, code: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise _http_error(422, code, "identifier must be a valid UUID") from None


class SessionLifecycleAction(BaseModel):
    action_id: uuid.UUID
    action: Literal["archive", "restore", "delete", "memory_policy"]
    lifecycle_revision: int = Field(default=0, ge=0)
    allowed: bool = True
    policy_version: int = Field(default=0, ge=0)
    content_version: int = Field(default=0, ge=0)


@app.post("/v2/sessions/{session_id}/actions")
def session_lifecycle_action(session_id: str, body: SessionLifecycleAction) -> dict:
    sid = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    try:
        if body.action == "memory_policy":
            return conversation_harness.memory_policy(sid, allowed=body.allowed, policy_version=body.policy_version, content_version=body.content_version)
        return conversation_harness.session_action(sid, str(body.action_id), body.action, body.lifecycle_revision)
    except ValueError as exc:
        raise _http_error(409, str(exc), "Session lifecycle version conflicts") from None


from agent_service.schemas import MemoryResultsRequest


@app.post("/v2/runs/{run_id}/memory-results")
def memory_results(run_id: str, body: MemoryResultsRequest) -> dict:
    rid = _require_uuid(run_id, code="RT.RUN.INVALID_ID")
    try:
        return conversation_harness.memory_results(rid, body)
    except ValueError as exc:
        raise _http_error(409, str(exc), "Learning lookup result conflicts with current run") from None


@app.get("/v2/sessions/{session_id}/snapshot")
def session_snapshot(session_id: str) -> dict:
    sid = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    try:
        return conversation_harness.export_snapshot(sid)
    except ValueError as exc:
        raise _http_error(404, str(exc), "Session checkpoint is unavailable") from None


@app.post("/v2/sessions/{session_id}/snapshot/restore")
def restore_session_snapshot(session_id: str, body: dict) -> dict:
    sid = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    if len(json.dumps(body)) > 16_000_000:
        raise _http_error(413, "RT.SESSION.SNAPSHOT_TOO_LARGE", "Snapshot exceeds restore limit")
    try:
        return conversation_harness.restore_snapshot(sid, body)
    except (ValueError, TypeError, KeyError) as exc:
        code = str(exc) if str(exc).startswith("RT.") else "RT.SESSION.INVALID_SNAPSHOT"
        raise _http_error(409, code, "Snapshot conflicts with existing state or schema") from None


@app.post("/v2/sessions/{session_id}/messages", response_model=MessageAccepted)
def submit_message(session_id: str, body: SessionMessageRequest) -> dict:
    session_id = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    try:
        result = conversation_harness.accept(session_id, body)
    except ValueError as exc:
        raise _http_error(409, str(exc), "message conflicts with current Session state") from None
    conversation_harness.start(session_id)
    return result.model_dump()


class ContinuationSourcesRequest(BaseModel):
    session_ids: list[str] = Field(max_length=1000)


@app.post("/v2/continuation/sources")
def continuation_sources(body: ContinuationSourcesRequest):
    missing, owners = [], []
    for sid in set(body.session_ids):
        sid = _require_uuid(sid, code="RT.SESSION.INVALID_ID")
        if conversation_harness.store.deleted(sid):
            continue
        data = conversation_harness.store.get(sid)
        if data is None:
            missing.append(sid)
        else:
            owners.extend(t['context']['goal_ownership'] for t in data['tasks'].values() if t['context'].get('goal_ownership'))
    return dict(missing_session_ids=missing, goal_ownership=owners)


@app.get("/v2/sessions/{session_id}/events")
def session_events(session_id: str, after_seq: int = 0, recovery_version: int = 0) -> dict:
    session_id = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    if after_seq < 0 or recovery_version < 0:
        raise _http_error(422, "RT.SESSION.INVALID_SEQ", "after_seq must be non-negative")
    data = conversation_harness.store.get(session_id)
    if data is None:
        raise _http_error(404, "RT.SESSION.UNKNOWN", "unknown Session")
    if after_seq < data.get("event_base_seq", 0):
        raise _http_error(409, "RT.SESSION.CURSOR_EXPIRED", "older acknowledged events are in the Mac history")
    return dict(session_id=session_id, events=[e for e in data["events"] if e["seq"] > after_seq],
                status=data.get("status", "active"), lifecycle_revision=data.get("lifecycle_revision", 0),
                last_seq=conversation_harness.store.last_seq(data), paused=data["paused"], mode=data["mode"],
                goal_ownership=[t["context"]["goal_ownership"] for t in data["tasks"].values() if t["context"].get("goal_ownership")],
                recovery=recovery_page(data, recovery_version),
                thinking_strength=data.get("thinking_strength", "smart"),
                capture_offers_revision=data.get("recovery_version", 0),
                capture_offers=[public_capture_offer(o) for o in data.get("capture_offers", {}).values()],
                pending=data["pending"], runs=[conversation_harness.public_run(r) for r in data["runs"].values()])


@app.get("/v2/sessions/{session_id}/events/stream")
async def stream_session_events(session_id: str, request: Request, after_seq: int = 0, recovery_version: int = 0):
    # Validate before headers; callers receive the same cursor errors as polling.
    first = await asyncio.to_thread(session_events, session_id, after_seq, recovery_version)

    async def generate():
        page, cursor, ticks, recovered = first, after_seq, 0, recovery_version
        while not await request.is_disconnected():
            if page["events"] or page["recovery"]["version"] != recovered:
                cursor = page["last_seq"]
                recovered = page["recovery"]["version"]
                yield f"id: {cursor}\nevent: session\ndata: {json.dumps(page, ensure_ascii=False)}\n\n"
            active = any(run["status"] in {"running", "accepted"} for run in page["runs"])
            queued = not page["paused"] and any(run["status"] == "queued" for run in page["runs"])
            if not active and not queued:
                return  # an idle Session needs no keepalive or polling connection
            await asyncio.sleep(0.05)
            ticks += 1
            if ticks % 300 == 0:
                yield ": keepalive\n\n"
            page = await asyncio.to_thread(session_events, session_id, cursor, recovered)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/v2/sessions/{session_id}/ack")
def session_ack(session_id: str, body: SessionAckRequest) -> dict:
    session_id = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    if conversation_harness.store.get(session_id) is None:
        raise _http_error(404, "RT.SESSION.UNKNOWN", "unknown Session")
    with conversation_harness.store.transaction(session_id) as data:
        if body.last_event_seq > conversation_harness.store.last_seq(data):
            raise _http_error(409, "RT.SESSION.ACK_AHEAD", "cannot ACK unseen events")
        data["last_acked_seq"] = max(data["last_acked_seq"], body.last_event_seq)
        conversation_harness.store.compact_acknowledged(data)
    return {"last_acked_seq": data["last_acked_seq"]}


@app.get("/v2/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run_id = _require_uuid(run_id, code="RT.RUN.INVALID_ID")
    data = conversation_harness.store.locate_run(run_id)
    if not data:
        raise _http_error(404, "RT.RUN.UNKNOWN", "unknown Run")
    return conversation_harness.public_run(data["runs"][run_id])


@app.post("/v2/runs/{run_id}/actions")
def run_action(run_id: str, body: RunActionRequest) -> dict:
    run_id = _require_uuid(run_id, code="RT.RUN.INVALID_ID")
    try:
        result = conversation_harness.action(run_id, body)
    except ValueError as exc:
        raise _http_error(409, str(exc), "action does not match current Run state") from None
    conversation_harness.start(result["session_id"])
    return conversation_harness.public_run(result)


@app.post("/v2/tasks/{task_id}/commit-claim")
def claim_task_commit(task_id: str) -> dict:
    task_id = _require_uuid(task_id, code="RT.TASK.INVALID_ID")
    try:
        return conversation_harness.claim_commit(task_id)
    except ValueError as exc:
        raise _http_error(409, str(exc), "this knowledge submission is no longer current") from None


@app.post("/v2/sessions/{session_id}/turns", response_model=SessionTurnAccepted)
def submit_session_turn(session_id: str, body: SessionTurnRequest, background: BackgroundTasks) -> dict:
    normalized_session = _require_uuid(session_id, code="RT.SESSION.INVALID_ID")
    if not openai_key():
        raise _http_error(409, "RT.HARNESS.NO_KEY", "model credential is not configured")
    # A legacy caller still enters the same Session owner. This also serializes
    # it against a concurrently accepted archive/restore operation.
    with conversation_harness.store.transaction(normalized_session) as state:
        if state.get("status", "active") != "active":
            raise _http_error(409, "RT.SESSION.ARCHIVED", "Session is read-only")
        lifecycle = state.get("lifecycle_revision", 0)
    record = HarnessTaskRecord(
        task_id=str(uuid.uuid4()),
        session_id=normalized_session,
        client_message_id=body.client_message_id,
        content=body.content.strip(),
        content_type=body.content_type,
        primary_language=body.primary_language,
        mode_preset=body.mode_preset,
        context={**body.context.model_dump(), "lifecycle_revision": lifecycle},
    )
    stored, created = harness_store.create(record)
    if created:
        harness_store.cleanup()
        background.add_task(process_task, stored.task_id)
    return SessionTurnAccepted(
        message_id=stored.client_message_id,
        task_id=stored.task_id,
        status="accepted" if created else "queued",
        next_event_seq=len(stored.events) + 1,
    ).model_dump()


@app.get("/v2/tasks/{task_id}", response_model=LearningTaskView)
def get_learning_task(task_id: str) -> dict:
    normalized = _require_uuid(task_id, code="RT.TASK.INVALID_ID")
    record = harness_store.get(normalized)
    if record is None:
        raise _http_error(404, "RT.TASK.UNKNOWN", "unknown task_id")
    return record.view().model_dump()


@app.get("/v2/tasks/{task_id}/events", response_model=TaskEventPage)
def get_task_events(task_id: str, after_seq: int = 0) -> dict:
    normalized = _require_uuid(task_id, code="RT.TASK.INVALID_ID")
    if after_seq < 0:
        raise _http_error(422, "RT.TASK.INVALID_SEQ", "after_seq must be non-negative")
    events = harness_store.events_after(normalized, after_seq)
    if events is None:
        raise _http_error(404, "RT.TASK.UNKNOWN", "unknown task_id")
    record = harness_store.get(normalized)
    return TaskEventPage(task_id=normalized, events=events, last_seq=len(record.events) if record else 0).model_dump()


@app.post("/v2/tasks/{task_id}/actions", response_model=LearningTaskView)
def submit_task_action(task_id: str, body: TaskActionRequest, background: BackgroundTasks) -> dict:
    normalized = _require_uuid(task_id, code="RT.TASK.INVALID_ID")
    current = harness_store.get(normalized)
    if current is None:
        raise _http_error(404, "RT.TASK.UNKNOWN", "unknown task_id")
    state = conversation_harness.store.get(current.session_id)
    if state and state.get("status", "active") != "active":
        raise _http_error(409, "RT.SESSION.ARCHIVED", "Session is read-only")
    operation = body.payload.get("operation")
    if body.action_type in {"form_memory", "switch_mode", "create_handoff", "select_sources", "select_question"} and not operation:
        raise _http_error(409, "RT.ACTION.CONFIRMATION_REQUIRED", "action requires an explicit object and version")
    previous = next((item for item in current.action_history if item.get("action_id") == body.action_id), None)
    if previous and any(previous.get(key) != value for key, value in body.model_dump().items()):
        raise _http_error(409, "RT.ACTION.IDEMPOTENCY_CONFLICT", "action id already refers to different input")
    if body.action_id in current.completed_action_ids:
        return current.view().model_dump()
    data = conversation_harness.store.get(current.session_id)
    run = next((r for r in reversed(list(data["runs"].values())) if r.get("task_id") == normalized), None) if data else None
    try:
        if body.action_type in {"retry", "cancel"} and run:
            conversation_harness.action(run["run_id"], RunActionRequest(action_id=body.action_id, action="retry" if body.action_type == "retry" else "cancel_task"))
        elif body.action_type == "cancel" and current.status != "cancelled":
            harness_store.append_event(normalized, stage="cancelled", state="cancelled", node="user_cancel", user_summary="此学习目标已取消，历史保留")
        elif body.action_type == "cancel":
            pass
        else:
            message = SessionMessageRequest(client_message_id=body.action_id,
                                            content=body.content or body.selection or (current.content if body.action_type == "retry" else "继续"),
                                            task_id=normalized, mode_preset=current.mode_preset, operation=operation)
            conversation_harness.accept(current.session_id, message)
    except ValueError as exc:
        raise _http_error(409, str(exc), "action does not match current state") from None
    # Record completion only AFTER the idempotent message/control acceptance.
    # A rejected action must remain retryable with the same ID, not become a
    # successful no-op just because its audit receipt was written first.
    def accepted(record):
        if body.action_id not in record.processed_action_ids:
            record.processed_action_ids.append(body.action_id)
            record.action_history.append({**body.model_dump(), "created_at": now_iso()})
        if body.action_id not in record.completed_action_ids:
            record.completed_action_ids.append(body.action_id)
    harness_store.mutate(normalized, accepted)
    conversation_harness.start(current.session_id)
    return (harness_store.get(normalized) or current).view().model_dump()


@app.post("/v2/tasks/{task_id}/ack", response_model=LearningTaskView)
def ack_learning_task(task_id: str, body: TaskAckRequest) -> dict:
    normalized = _require_uuid(task_id, code="RT.TASK.INVALID_ID")
    try:
        return conversation_harness.acknowledge_task(normalized, body.last_event_seq, body.knowledge_ids)
    except ValueError as exc:
        raise _http_error(404 if str(exc) == "RT.TASK.UNKNOWN" else 409, str(exc), "task receipt does not match current state") from None


def _apply_graph_result(record: TaskRecord, result: dict) -> None:
    record.events = list(result.get("events") or [])
    record.intent = result.get("intent") or record.intent
    record.verify_reason = result.get("verify_reason") or record.verify_reason
    if result.get("url"):
        record.url = result.get("url")
    if result.get("page_text"):
        record.raw_text = result["page_text"]
        record.input_type = "url"
    outcome = result.get("outcome") or "retryable_failed"
    record.error_code = result.get("error_code")
    record.user_status = result.get("user_status") or "正在整理"
    extracted = result.get("extracted")
    if extracted:
        try:
            payload = ExtractPayload.model_validate(extracted)
        except ValidationError:
            record.result = None
            record.receipt = None
            record.status = "retryable_failed"
            record.error_code = "RT.CAPTURE.STRUCTURE_INVALID"
            record.user_status = "需要重试"
            return
        if source_fidelity_issues(payload, record.raw_text):
            record.result = None
            record.receipt = None
            record.status = "needs_attention"
            record.error_code = "RT.CAPTURE.SEMANTIC_INVALID"
            record.user_status = "需要处理"
            return
        record.result = payload
        if record.force_source_view:
            record.result.attribution = "source_view"
    if outcome == "committing" and record.result:
        payload = record.result
        record.receipt = Receipt(
            understood_as=payload.understood_as,
            theme=payload.theme,
            knowledge_count=len(payload.knowledge),
            attribution=payload.attribution,
        )
        record.status = "committing"
        record.user_status = "整理完成"
        record.error_code = None
    elif outcome == "needs_attention":
        record.status = "needs_attention"
        record.user_status = "需要处理"
    else:
        record.status = "retryable_failed"
        record.user_status = "需要重试"
        record.error_code = record.error_code or "RT.CAPTURE.MODEL_FAILED"


def _process(task_id: str) -> None:
    record = store.get(task_id)
    if record is None or record.status != "processing":
        return
    if not openai_key():
        record.status = "retryable_failed"
        record.error_code = "RT.CAPTURE.NO_KEY"
        record.user_status = "需要重试"
        store.put(record)
        return
    try:
        result = run_capture(
            record.task_id,
            record.raw_text,
            record.primary_language,
            input_type=record.input_type,
            url=record.url,
            force_source_view=record.force_source_view,
        )
        _apply_graph_result(record, result)
        store.put(record)
    except Exception:  # noqa: BLE001
        record.status = "retryable_failed"
        record.error_code = "RT.CAPTURE.MODEL_FAILED"
        record.user_status = "需要重试"
        store.put(record)


def _queue(record: TaskRecord, background: BackgroundTasks) -> None:
    record.status = "processing"
    record.user_status = "正在整理"
    record.error_code = None
    record.receipt = None
    record.result = None
    record.intent = None
    record.source_candidates = []
    record.verify_reason = None
    record.events = []
    record.acked = False
    store.put(record)
    background.add_task(_process, record.task_id)


@app.post("/v1/capture/tasks")
def submit_capture(body: CaptureSubmitRequest, background: BackgroundTasks) -> dict:
    if body.input_type not in {"text", "url", "voice"}:
        raise _http_error(400, "RT.CAPTURE.UNSUPPORTED_INPUT", "unsupported input_type")
    text = body.raw_text.strip()
    url = (body.url or "").strip() or looks_like_url(text)
    if body.input_type == "voice" and body.audio_base64 and not text:
        try:
            audio = base64.b64decode(body.audio_base64)
            text = transcribe_audio(audio, f"note.{body.audio_format or 'm4a'}")
        except Exception:  # noqa: BLE001
            record = TaskRecord(
                task_id=body.task_id,
                source_id=body.source_id,
                raw_text="",
                primary_language=body.primary_language,
                input_type="voice",
                status="needs_attention",
                user_status="需要处理",
                error_code="RT.CAPTURE.TRANSCRIBE_FAILED",
            )
            stored, created = store.upsert_new(record)
            if not created:
                return stored.view().model_dump()
            return record.view().model_dump()
    if not text and not url:
        raise _http_error(400, "RT.CAPTURE.EMPTY_INPUT", "raw_text is empty")

    record = TaskRecord(
        task_id=body.task_id,
        source_id=body.source_id,
        raw_text=text,
        primary_language=body.primary_language,
        input_type="url" if url else body.input_type,
        url=url or None,
    )
    stored, created = store.upsert_new(record)
    if created:
        background.add_task(_process, stored.task_id)
    elif stored.status == "retryable_failed":
        _queue(stored, background)
    return stored.view().model_dump()


@app.get("/v1/capture/tasks/{task_id}")
def get_capture(task_id: str) -> dict:
    record = store.get(task_id)
    if record is None:
        raise _http_error(404, "RT.CAPTURE.UNKNOWN_TASK", "unknown task_id")
    return record.view().model_dump()


@app.post("/v1/capture/tasks/{task_id}/ack")
def ack_capture(task_id: str, body: CaptureAckRequest) -> dict:
    record = store.get(task_id)
    if record is None:
        raise _http_error(404, "RT.CAPTURE.UNKNOWN_TASK", "unknown task_id")
    if record.status == "completed":
        return record.view().model_dump()
    if record.status != "committing":
        raise _http_error(409, "RT.CAPTURE.NOT_COMMITTING", "task is not waiting for ACK")
    expected = {item.id for item in (record.result.knowledge if record.result else [])}
    if expected and set(body.knowledge_ids) != expected:
        raise _http_error(409, "RT.CAPTURE.ACK_MISMATCH", "knowledge_ids do not match result")
    record.status = "completed"
    record.user_status = "整理完成"
    record.acked = True
    store.put(record)
    return record.view().model_dump()


@app.post("/v1/capture/tasks/{task_id}/actions")
def capture_action(task_id: str, body: CaptureActionRequest, background: BackgroundTasks) -> dict:
    record = store.get(task_id)
    if record is None:
        raise _http_error(404, "RT.CAPTURE.UNKNOWN_TASK", "unknown task_id")
    if record.status == "completed":
        return record.view().model_dump()

    if body.action == "delete":
        record.status = "cancelled"
        record.user_status = "已取消"
        store.put(record)
        return record.view().model_dump()

    if body.action == "keep_paused":
        record.status = "needs_attention"
        record.user_status = "需要处理"
        store.put(record)
        return record.view().model_dump()

    if body.action == "paste":
        text = body.raw_text.strip()
        if not text:
            raise _http_error(400, "RT.CAPTURE.EMPTY_INPUT", "raw_text is empty")
        record.raw_text = text
        record.url = None
        record.input_type = "text"
        _queue(record, background)
        return record.view().model_dump()

    if body.action == "attach_url":
        url = body.url.strip() or looks_like_url(body.raw_text)
        if not url:
            raise _http_error(400, "RT.CAPTURE.EMPTY_INPUT", "url is empty")
        record.url = url
        record.input_type = "url"
        _queue(record, background)
        return record.view().model_dump()

    if body.action == "confirm_transcript":
        text = body.transcript.strip() or body.raw_text.strip()
        if not text:
            raise _http_error(400, "RT.CAPTURE.EMPTY_INPUT", "transcript is empty")
        record.raw_text = text
        record.input_type = "voice"
        _queue(record, background)
        return record.view().model_dump()

    if body.action == "find_sources":
        topic = record.intent and record.raw_text or record.raw_text
        record.user_status = "正在查找资料"
        record.source_candidates = find_source_candidates(topic[:120])
        record.status = "needs_attention"
        record.error_code = "RT.CAPTURE.CONFIRM_SOURCES"
        record.user_status = "需要处理"
        store.put(record)
        return record.view().model_dump()

    if body.action == "confirm_sources":
        if not body.urls:
            raise _http_error(400, "RT.CAPTURE.EMPTY_INPUT", "urls is empty")
        record.url = body.urls[0]
        record.input_type = "url"
        _queue(record, background)
        return record.view().model_dump()

    if body.action in {"adopt_limited", "as_source_view"}:
        record.force_source_view = True
        if record.result:
            record.result.attribution = "source_view"
            record.receipt = Receipt(
                understood_as=record.result.understood_as,
                theme=record.result.theme,
                knowledge_count=len(record.result.knowledge),
                attribution="source_view",
            )
            record.status = "committing"
            record.user_status = "整理完成"
            record.error_code = None
            store.put(record)
            return record.view().model_dump()
        _queue(record, background)
        return record.view().model_dump()

    if body.action == "reprocess":
        if record.status in {"retryable_failed", "needs_attention"}:
            _queue(record, background)
        return record.view().model_dump()

    raise _http_error(400, "RT.CAPTURE.UNSUPPORTED_INPUT", "unknown action")


@app.post("/v1/review/grade")
def review_grade(body: GradeRequest) -> dict:
    with _grade_lock:
        cached = _grade_results.get(body.attempt_id)
        if cached is not None:
            return cached.model_dump()
        if not openai_key():
            raise _http_error(409, "RT.CAPTURE.NO_KEY", "key not configured")
        try:
            result = GradeResult.model_validate(grade_answer(body).model_dump())
            result.attempt_id = body.attempt_id
            result.hint_used = body.hint_used
            if result.agent_grade == "good" and body.hint_used:
                result.agent_grade = "hard"
        except Exception:  # noqa: BLE001
            raise _http_error(502, "RT.REVIEW.GRADE_FAILED", "grading failed") from None
        _grade_results[body.attempt_id] = result
        return result.model_dump()


@app.post("/v1/review/attempts/{attempt_id}/ack")
def review_ack(attempt_id: str, body: GradeAckRequest) -> dict:
    if body.attempt_id != attempt_id:
        raise _http_error(409, "RT.REVIEW.ACK_MISMATCH", "attempt_id mismatch")
    with _grade_lock:
        if attempt_id not in _grade_results:
            raise _http_error(409, "RT.REVIEW.UNKNOWN_ATTEMPT", "attempt has no valid grade result")
        _grade_acks.add(attempt_id)
    return {"attempt_id": attempt_id, "status": "acked"}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "agent_service.main:app",
        host=HOST,
        port=PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
