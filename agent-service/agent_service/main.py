"""Capture + review contract frozen with this code.

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

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import ValidationError

from agent_service.capture import find_source_candidates, run_capture, source_fidelity_issues
from agent_service.capture.fetch import looks_like_url
from agent_service.config import CA_BUNDLE, HOST, PORT, openai_key
from agent_service.openai_client import transcribe_audio
from agent_service.review import grade_answer
from agent_service.schemas import (
    CaptureAckRequest,
    CaptureActionRequest,
    CaptureSubmitRequest,
    ExtractPayload,
    GradeAckRequest,
    GradeRequest,
    Receipt,
)
from agent_service.store import TaskRecord, store

app = FastAPI(title="Review Today Agent", docs_url=None, redoc_url=None)
_grade_acks: set[str] = set()


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "key_configured": bool(openai_key()),
        "ca_bundle": bool(CA_BUNDLE),
    }


def _http_error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": message})


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
        if record.status != "processing":
            _queue(record, background)
        return record.view().model_dump()

    raise _http_error(400, "RT.CAPTURE.UNSUPPORTED_INPUT", "unknown action")


@app.post("/v1/review/grade")
def review_grade(body: GradeRequest) -> dict:
    if not openai_key():
        raise _http_error(409, "RT.CAPTURE.NO_KEY", "key not configured")
    if body.attempt_id in _grade_acks:
        raise _http_error(409, "RT.REVIEW.DUPLICATE_ATTEMPT", "attempt already written")
    try:
        return grade_answer(body).model_dump()
    except Exception:  # noqa: BLE001
        raise _http_error(502, "RT.REVIEW.GRADE_FAILED", "grading failed") from None


@app.post("/v1/review/attempts/{attempt_id}/ack")
def review_ack(attempt_id: str, body: GradeAckRequest) -> dict:
    if body.attempt_id != attempt_id:
        raise _http_error(409, "RT.REVIEW.ACK_MISMATCH", "attempt_id mismatch")
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
