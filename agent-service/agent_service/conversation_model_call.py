"""Budgeted, streamed model execution and checkpoint publication."""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from pydantic import ValidationError
from agent_service.config import COACH_MODEL
from agent_service.conversation_store import Superseded
from agent_service.openai_client import ModelCallError
from agent_service.execution_policy import budget_scope
from agent_service.service_diagnostics import diagnose
from agent_service.structured_output import schema_repair_instruction
from agent_service.context_budget import OUTPUT_RESERVE, count_request, policy, prepare as prepare_context
from agent_service.response_projection import public_preview
from agent_service.schemas import IntentDecision
from agent_service.source_links import bound_source_links

def call(self, session_id, run_id, revision, node, system, prompt, schema, model=COACH_MODEL, *, parse_model, configured_window, alternatives, require_model):
    data, run = self._snapshot(session_id, run_id, revision)
    strength = run.get("thinking_strength", data.get("thinking_strength", "smart"))
    try:
        payload = json.loads(prompt)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        narrative = payload.get("context", payload)
        if (isinstance(narrative, dict) and narrative.get("recent_messages")
                and count_request(system, prompt, schema.model_json_schema()) >= policy(configured_window(model))[1]):
            with self.store.transaction(session_id, run_id, revision) as current:
                self.store.event(current, current["runs"][run_id], "context_compaction", "正在整理较早上下文，原文保留")
        payload = self._compact_history(session_id, run, system, payload, schema.model_json_schema(), model)
        prompt = json.dumps(payload, ensure_ascii=False)
    self._snapshot(session_id, run_id, revision)
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
    intent_context = json.loads(prompt) if schema is IntentDecision else None
    started = time.monotonic()
    last_emit = 0.0
    latest = ""

    def emit(partial, *, force=False):
        nonlocal last_emit, latest
        # Check even non-public chunks: a stopped generation closes promptly.
        _, current_run = self._snapshot(session_id, run_id, revision)
        text = public_preview(node, partial)
        if "allowed_source_urls" in current_run:
            text = bound_source_links(text, current_run["allowed_source_urls"])
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
            choices = ([model] + (alternatives(model, strength, streamable) or [model]))[:2]
            repaired = False
            for index, selected_model in enumerate(choices):
                attempt_event = None
                try:
                    model = selected_model
                    require_model(selected_model, thinking_strength=strength)
                    if index > 0 and selected_model != choices[0]:
                        try:
                            retry_payload = json.loads(prompt)
                        except ValueError:
                            retry_payload = None
                        if isinstance(retry_payload, dict):
                            retry_payload = self._compact_history(session_id, run, system, retry_payload,
                                                                  schema.model_json_schema(), selected_model)
                            prompt = json.dumps(retry_payload, ensure_ascii=False)
                    prompt, actual_capacity = prepare_context(system, prompt, window=configured_window(selected_model), schema=schema.model_json_schema())
                    with self.store.transaction(session_id, run_id, revision) as current:
                        current["runs"][run_id]["context_capacity"] = actual_capacity
                        if actual_capacity != capacity:
                            self.store.event(current, current["runs"][run_id], "context_capacity", "上下文容量已更新",
                                             payload={"context_capacity": actual_capacity})
                    capacity = actual_capacity
                    with self.store.transaction(session_id, run_id, revision) as current:
                        attempt_event = self.store.event(current, current["runs"][run_id], "model_attempt", "正在处理当前步骤", model=selected_model, payload={"step": node, "step_attempt": index + 1})
                        attempt_event["attempt"] = index + 1
                    attempt_started = time.monotonic()
                    parsed = parse_model(system, prompt, schema, model=selected_model, on_cancel_handle=register_cancel,
                                         timeout=budget.remaining(), max_output_tokens=OUTPUT_RESERVE, reasoning_effort="high" if strength == "deep" else None,
                                         **({"on_partial": emit, "on_transport": transport} if streamable else {}))
                    if schema is IntentDecision and "answer" in parsed.intents:
                        checked_context = intent_context
                        user_inputs = checked_context.get("current_inputs", [])
                        task_context = (checked_context.get("task") or {}).get("context", {})
                        if task_context.get("check_question") and (not parsed.answer_evidence.strip() or not user_inputs or parsed.answer_evidence not in user_inputs[-1]):
                            raise ModelCallError("SCHEMA", "field=answer_evidence; must quote the current user answer, not an option or previous message")
                    model = selected_model
                    break
                except ModelCallError as error:
                    if attempt_event is not None:
                        with self.store.transaction(session_id, run_id, revision) as current:
                            event = self.store.event(current, current["runs"][run_id], "model_attempt_failed",
                                "本次模型输出格式未通过" if error.code == "RT.MODEL.SCHEMA" else "本次模型调用未完成",
                                model=selected_model, duration_ms=int((time.monotonic() - attempt_started) * 1000),
                                error=error.code, detail=error.diagnostic,
                                payload={"step": node, "step_attempt": index + 1, "diagnostic": diagnose(error)})
                            event["attempt"] = index + 1
                    # Never splice a second generation into already shown text,
                    # retry refusals/access restrictions or exceed shared budget.
                    if error.code == "RT.MODEL.SCHEMA" and not latest and not repaired and budget.attempts < budget.limit:
                        repaired = True
                        choices[index + 1:] = [selected_model]
                        system += "\n" + schema_repair_instruction(error)
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
