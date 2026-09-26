import base64
import json
import struct
import uuid
import zlib
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, ValidationError

from agent_service import image_inputs, openai_client
from agent_service.conversation import ConversationHarness
from agent_service.conversation_store import ConversationStore, Superseded
from agent_service.harness_store import HarnessStore
from agent_service.schemas import SessionMessageRequest, IntentDecision


def picture(color=0):
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress(bytes([0, color, 0, 0, 0, 0, 0]))) + chunk(b"IEND", b"")
    return dict(name="中文截图.png", mime_type="image/png", data_base64=base64.b64encode(raw).decode())


def message(**values):
    return SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="解释图片中的流程", content_type="image", image=picture(), **values)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_service.conversation.require_model", lambda *a, **kw: None)
    monkeypatch.setattr("agent_service.conversation.alternatives", lambda *a: [])
    h = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "image.sqlite3"))))
    sid = str(uuid.uuid4())
    request = message()
    accepted = h.accept(sid, request)
    with h.store.transaction(sid) as state:
        state["runs"][accepted.run_id]["status"] = "running"
    return h, sid, accepted.run_id, request


def test_transport_sends_real_image_parts_and_keeps_text_separate(monkeypatch):
    class Reply(BaseModel):
        text: str
    client = Mock()
    client.responses.create.return_value = NS(output=[NS(content=[NS(type="output_text", text='{"text":"识图完成"}')])])
    monkeypatch.setattr(openai_client, "PROVIDER", "deepseek")
    monkeypatch.setattr(openai_client, "_client", lambda **kw: client)
    openai_client.parse_model("规则", "用户问题", Reply, model="deepseek-flash", images=[picture()])
    request = client.responses.create.call_args.kwargs
    assert request["input"][1]["content"][0] == {"type": "input_text", "text": "用户问题"}
    assert request["input"][1]["content"][1]["type"] == "input_image"
    assert request["input"][1]["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert request["reasoning"] == {"effort": "none"}
    with pytest.raises(openai_client.ModelCallError, match="UNSUPPORTED"):
        openai_client.parse_model("规则", "问题", Reply, model="deepseek-v4-pro", images=[picture()])
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize("change", [
    dict(data_base64="not base64"), dict(mime_type="image/jpeg"), dict(sha256="incorrect"),
    dict(name="/private/image.png"), dict(data_base64=""),
])
def test_bad_attachments_are_rejected_before_model(change):
    with pytest.raises(ValidationError):
        image_inputs.ImageAttachment.model_validate({**picture(), **change})


def test_image_is_not_an_operation_or_a_silent_text_message():
    with pytest.raises(ValidationError):
        message(operation=dict(kind="save", target_id="draft", version=1))
    with pytest.raises(ValidationError):
        SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="x", image=picture())
    with pytest.raises(ValidationError):
        SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="x", content_type="image")


def test_idempotency_includes_actual_pixels(harness):
    h, sid, rid, request = harness
    assert h.accept(sid, request).run_id == rid
    changed = request.model_copy(update={"image": image_inputs.ImageAttachment.model_validate(picture(255))})
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        h.accept(sid, changed)
    assert len(h.store.get(sid)["messages"]) == 1


def install_reader(monkeypatch, request, *, before_return=None, wrong_id=False):
    calls = []
    def parse(system, user, schema, **kwargs):
        payload = json.loads(user)
        assert request.image.data_base64 not in user
        assert kwargs["model"] == "deepseek-flash"
        assert kwargs["images"][0]["sha256"] == request.image.sha256
        calls.append(payload)
        kwargs["on_request"]()
        kwargs["on_usage"](dict(input_tokens=1200, output_tokens=140, reported_model="deepseek-flash"))
        if before_return:
            before_return()
        return schema.model_validate(dict(
            decision=IntentDecision(intents=["question", "material"], relation="continuation", scope="conversation", rationale="读懂图片").model_dump(),
            readings=[dict(message_id="wrong" if wrong_id else request.client_message_id,
                           transcription="第一步：检索。第二步：生成。", visual_description="箭头从检索指向生成。", uncertainties=["右下角被裁掉"])],
        ))
    monkeypatch.setattr("agent_service.conversation.parse_model", parse)
    return calls


def test_reading_is_source_data_cached_and_usage_is_recorded(harness, monkeypatch):
    h, sid, rid, request = harness
    calls = install_reader(monkeypatch, request)
    data, run = h._snapshot(sid, rid, 1)
    context, _ = h._context(data, run)
    result = image_inputs.resolve(h, sid, rid, 1, context, "规则")
    assert result.intents == ["question", "material"]
    # A crash between successful model checkpointing and reading publication
    # reuses the completed step instead of sending the pixels again.
    with h.store.transaction(sid) as data:
        data["messages"][0].pop("image_reading")
    image_inputs.resolve(h, sid, rid, 1, context, "规则")
    assert len(calls) == 1, "same successful step must not incur another request"
    state = h.store.get(sid)
    projected, last = h._context(state, state["runs"][rid])
    assert projected["current_inputs"] == [request.content]
    assert projected["image_materials"][0]["uncertainties"] == ["右下角被裁掉"]
    assert request.image.data_base64 not in json.dumps(projected)
    assert "data_base64" not in last["image"]
    assert state["runs"][rid]["context_capacity"]["image_tokens"] == 1024
    call = state["runs"][rid]["model_calls"][0]
    assert call["transport_requests"] == 1 and call["usage"][0]["input_tokens"] == 1200
    assert request.image.data_base64 not in json.dumps(state["events"])


def test_cancelled_image_result_cannot_publish(harness, monkeypatch):
    h, sid, rid, request = harness
    def stop():
        with h.store.transaction(sid) as data:
            data["runs"][rid]["revision"] += 1
            data["runs"][rid]["status"] = "interrupted"
    install_reader(monkeypatch, request, before_return=stop)
    with pytest.raises(Superseded):
        image_inputs.resolve(h, sid, rid, 1, {}, "规则")
    assert "image_reading" not in h.store.get(sid)["messages"][0]


def test_wrong_image_identity_is_repaired_once_then_rejected(harness, monkeypatch):
    h, sid, rid, request = harness
    calls = install_reader(monkeypatch, request, wrong_id=True)
    with pytest.raises(openai_client.ModelCallError, match="SCHEMA"):
        image_inputs.resolve(h, sid, rid, 1, {}, "规则")
    assert len(calls) == 2
    assert "image_reading" not in h.store.get(sid)["messages"][0]


def test_recovery_excludes_binary_and_requires_original_for_unread_image(harness, tmp_path):
    h, sid, rid, request = harness
    snapshot = h.export_snapshot(sid)
    assert request.image.data_base64 not in json.dumps(snapshot)
    other = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "restore.sqlite3"))))
    with pytest.raises(ValueError, match="ORIGINAL_REQUIRED"):
        other.restore_snapshot(sid, snapshot)
    snapshot["checkpoint"]["messages"][0]["image"] = request.image.model_dump()
    restored = other.restore_snapshot(sid, snapshot)
    assert request.image.data_base64 not in json.dumps(restored)
    assert other.store.get(sid)["messages"][0]["image"]["sha256"] == request.image.sha256
    assert other.store.get(sid)["paused"]


def test_image_tokens_cannot_overrun_input_budget():
    with pytest.raises(ValueError, match="INPUT_TOO_LARGE"):
        image_inputs.reserve_capacity(dict(input_tokens=9500, input_budget=10000), [picture()])


def test_snapshot_limit_does_not_expand_text_budget():
    assert image_inputs.snapshot_within_limit({"checkpoint": {"messages": [{"image": picture()}]}})
    assert not image_inputs.snapshot_within_limit({"checkpoint": {"messages": [{"content": "x" * 16_000_001}]}})
    assert not image_inputs.snapshot_within_limit({"checkpoint": []})


def test_full_turn_and_restored_followup_reuse_reading(harness, monkeypatch, tmp_path):
    from tests.test_conversation_v2 import ConversationTests, intent
    h, sid, rid, request = harness
    baseline = ConversationTests()
    baseline.calls = []
    baseline.decision = intent("question", answer_only=True)
    vision_calls = install_reader(monkeypatch, request)
    from agent_service import conversation
    read = conversation.parse_model

    def parse(system, user, schema, **kwargs):
        if kwargs.get("images"):
            return read(system, user, schema, **kwargs)
        assert request.image.data_base64 not in user
        if schema.__name__ == "ConversationOutput":
            assert "第一步：检索" in user and "右下角被裁掉" in user
        return baseline.model(system, user, schema, **kwargs)

    monkeypatch.setattr(conversation, "parse_model", parse)
    monkeypatch.setattr(conversation, "web_search_capability", lambda: {"status": "unverified", "provider": "none"})
    monkeypatch.setattr(h, "_schedule_summary", lambda *_: None)
    with h.store.transaction(sid) as state:
        state["runs"][rid]["status"] = "accepted"
    h.drain(sid)
    state = h.store.get(sid)
    assert state["runs"][rid]["status"] == "completed", state["events"][-1]
    assert len(vision_calls) == 1
    assert any(m["role"] == "coach" for m in state["messages"])
    assert not (state.get("pending") or {}).get("consent_received"), "a picture never grants save permission"
    assert all(not task.get("context", {}).get("commit_claimed") for task in state["tasks"].values())
    snapshot = h.export_snapshot(sid)
    restored = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "completed.sqlite3"))))
    restored.restore_snapshot(sid, snapshot)
    monkeypatch.setattr(restored, "_schedule_summary", lambda *_: None)
    accepted = restored.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="图里的两步有什么区别？"))
    restored.drain(sid)
    state = restored.store.get(sid)
    assert state["runs"][accepted.run_id]["status"] == "completed", state["events"][-1]
    assert len(vision_calls) == 1, "a text followup must not send or re-read the original image"


def test_reading_survives_restart_before_intent_checkpoint(harness, monkeypatch, tmp_path):
    from tests.test_conversation_v2 import ConversationTests, intent
    from agent_service.schemas import RunActionRequest
    h, sid, rid, request = harness
    install_reader(monkeypatch, request)
    state = h.store.get(sid)
    context, _ = h._context(state, state["runs"][rid])
    image_inputs.resolve(h, sid, rid, 1, context, "规则")
    restored = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "between-steps.sqlite3"))))
    restored.restore_snapshot(sid, h.export_snapshot(sid))
    baseline = ConversationTests(); baseline.calls = []; baseline.decision = intent("question", answer_only=True)
    def text_only(system, user, schema, **kwargs):
        assert not kwargs.get("images")
        assert "第一步：检索" in user
        return baseline.model(system, user, schema, **kwargs)
    monkeypatch.setattr("agent_service.conversation.parse_model", text_only)
    monkeypatch.setattr("agent_service.conversation.web_search_capability", lambda: {"status": "unverified", "provider": "none"})
    monkeypatch.setattr(restored, "_schedule_summary", lambda *_: None)
    restored.action(rid, RunActionRequest(action_id=str(uuid.uuid4()), action="resume"))
    restored.drain(sid)
    state = restored.store.get(sid)
    assert state["runs"][rid]["status"] == "completed", state["events"][-1]


def test_private_image_text_cannot_become_a_public_search(harness):
    from agent_service.request_scope import check_web
    from agent_service.call_errors import WebToolError
    h, sid, rid, _ = harness
    with h.store.transaction(sid) as state:
        state["messages"][0]["image_reading"] = dict(transcription="这是内部未发布项目 Orion 的资料", visual_description="表格", uncertainties=[])
        state["runs"][rid]["intent"] = {"relation": "new_topic"}
    with pytest.raises(WebToolError, match="PRIVATE_INPUT"):
        check_web(h, sid, rid, 1, "Orion 项目介绍", operation="search")


def accept_multiple(h, count=2):
    sid = str(uuid.uuid4())
    request = SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="比较这些图片中的流程", content_type="image",
                                    images=[{**picture(i * 20), "name": f"图{i + 1}.png"} for i in range(count)])
    accepted = h.accept(sid, request)
    with h.store.transaction(sid) as state:
        state["runs"][accepted.run_id]["status"] = "running"
    return sid, accepted.run_id, request


def install_multiple_reader(monkeypatch, request, *, wrong_index=False, before_return=None):
    calls = []
    def parse(system, user, schema, **kwargs):
        payload = json.loads(user)
        assert [i["image_index"] for i in payload["image_inputs"]] == [0, 1]
        assert [i["sha256"] for i in kwargs["images"]] == [i.sha256 for i in request.images]
        assert all(i.data_base64 not in user for i in request.images)
        calls.append(payload)
        if before_return: before_return()
        # Deliberately reverse response order: image_index owns identity.
        return schema.model_validate(dict(decision=IntentDecision(intents=["question", "material"], relation="continuation",
            scope="conversation", rationale="比较两张图", answer_only=True).model_dump(), readings=[
                dict(message_id=request.client_message_id, image_index=0 if wrong_index else 1,
                     transcription="第二张预算：18.75 元", visual_description="生成指向校验", uncertainties=[]),
                dict(message_id=request.client_message_id, image_index=0,
                     transcription="第一张预算：12.50 元", visual_description="检索指向生成", uncertainties=[])]))
    monkeypatch.setattr("agent_service.conversation.parse_model", parse)
    return calls


def test_multi_image_limits_and_legacy_single_transport_identity(harness):
    with pytest.raises(ValidationError):
        SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="x", content_type="image", images=[picture()] * 9)
    with pytest.raises(ValidationError):
        message(images=[picture()])
    h, sid, rid, request = harness
    equivalent = request.model_copy(update={"image": None, "images": [request.image]})
    assert h.accept(sid, equivalent).run_id == rid
    other_sid, other_rid, multi = accept_multiple(h)
    assert h.accept(other_sid, multi).run_id == other_rid
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        h.accept(other_sid, multi.model_copy(update={"images": list(reversed(multi.images))}))
    assert len(h.store.get(other_sid)["messages"]) == 1


def test_multi_image_reading_order_context_and_checkpoint(harness, monkeypatch, tmp_path):
    h = harness[0]
    sid, rid, request = accept_multiple(h)
    calls = install_multiple_reader(monkeypatch, request)
    state = h.store.get(sid)
    context, _ = h._context(state, state["runs"][rid])
    image_inputs.resolve(h, sid, rid, 1, context, "规则")
    state = h.store.get(sid)
    context, last = h._context(state, state["runs"][rid])
    assert [m["transcription"] for m in context["image_materials"]] == ["第一张预算：12.50 元", "第二张预算：18.75 元"]
    assert [m["image_index"] for m in context["image_materials"]] == [0, 1]
    assert len(calls) == 1
    assert state["runs"][rid]["context_capacity"]["image_tokens"] == 2048
    assert all("data_base64" not in i for i in last["images"])
    snapshot = h.export_snapshot(sid)
    assert "data_base64" not in json.dumps(snapshot)
    restored = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "multiple.sqlite3"))))
    restored.restore_snapshot(sid, snapshot)
    assert image_inputs.has_reading(restored.store.get(sid)["messages"][0])
    assert len(image_inputs.materials(restored.store.get(sid)["messages"][0])) == 2


def test_missing_or_duplicate_image_index_is_repaired_once(harness, monkeypatch):
    h = harness[0]
    sid, rid, request = accept_multiple(h)
    calls = install_multiple_reader(monkeypatch, request, wrong_index=True)
    with pytest.raises(openai_client.ModelCallError, match="SCHEMA"):
        image_inputs.resolve(h, sid, rid, 1, {}, "规则")
    assert len(calls) == 2
    assert not image_inputs.has_reading(h.store.get(sid)["messages"][0])


def test_multi_unread_recovery_needs_every_original(harness, tmp_path):
    h = harness[0]
    sid, rid, request = accept_multiple(h)
    snapshot = h.export_snapshot(sid)
    restored = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "multi-unread.sqlite3"))))
    snapshot["checkpoint"]["messages"][0]["images"][0] = request.images[0].model_dump()
    with pytest.raises(ValueError, match="ORIGINAL_REQUIRED"):
        restored.restore_snapshot(sid, snapshot)
    snapshot["checkpoint"]["messages"][0]["images"] = [i.model_dump() for i in request.images]
    assert image_inputs.snapshot_within_limit(snapshot)
    restored.restore_snapshot(sid, snapshot)
    assert [i["sha256"] for i in restored.store.get(sid)["messages"][0]["images"]] == [i.sha256 for i in request.images]
    snapshot["checkpoint"]["messages"][0]["images"] *= 5
    assert not image_inputs.snapshot_within_limit(snapshot)


def test_multi_cancelled_result_and_total_turn_limit(harness, monkeypatch):
    h = harness[0]
    sid, rid, request = accept_multiple(h)
    def stop():
        with h.store.transaction(sid) as state:
            state["runs"][rid]["revision"] += 1
    install_multiple_reader(monkeypatch, request, before_return=stop)
    with pytest.raises(Superseded):
        image_inputs.resolve(h, sid, rid, 1, {}, "规则")
    assert not image_inputs.has_reading(h.store.get(sid)["messages"][0])
    with h.store.transaction(sid) as state:
        original = state["messages"][0]
        other = {**original, "message_id": str(uuid.uuid4()), "images": original["images"] * 4}
        state["messages"].append(other)
        state["runs"][rid]["input_ids"].append(other["message_id"])
    with pytest.raises(ValueError, match="TURN_LIMIT"):
        image_inputs.resolve(h, sid, rid, 2, {}, "规则")


def test_private_second_image_blocks_public_query(harness, monkeypatch):
    from agent_service.request_scope import check_web
    from agent_service.call_errors import WebToolError
    h = harness[0]
    sid, rid, request = accept_multiple(h)
    install_multiple_reader(monkeypatch, request)
    image_inputs.resolve(h, sid, rid, 1, {}, "规则")
    with h.store.transaction(sid) as state:
        state["runs"][rid]["intent"] = {"relation": "new_topic"}
        state["messages"][0]["image_readings"][1]["transcription"] = "这是内部未发布项目 Orion 的资料"
    with pytest.raises(WebToolError, match="PRIVATE_INPUT"):
        check_web(h, sid, rid, 1, "Orion 介绍", operation="search")


def test_full_multi_turn_followup_keeps_both_images_without_upload(harness, monkeypatch, tmp_path):
    from tests.test_conversation_v2 import ConversationTests, intent
    from agent_service import conversation
    h = harness[0]
    sid, rid, request = accept_multiple(h)
    calls = install_multiple_reader(monkeypatch, request)
    read = conversation.parse_model
    baseline = ConversationTests(); baseline.calls = []; baseline.decision = intent("question", answer_only=True)
    changing_topic = False
    def parse(system, user, schema, **kwargs):
        if kwargs.get("images"): return read(system, user, schema, **kwargs)
        if changing_topic and schema.__name__ == "TeachingPreparation":
            assert "12.50" not in user and "18.75" not in user
        elif not changing_topic and schema.__name__ in {"ConversationOutput", "TeachingPreparation"}:
            assert "12.50" in user and "18.75" in user
        if schema.__name__ == "TeachingPreparation":
            payload = json.loads(user)
            if payload["image_materials"] or changing_topic:
                assert payload["previous_image_materials"] == []
            else:
                assert len(payload["previous_image_materials"]) == 2
        assert all(i.data_base64 not in user for i in request.images)
        return baseline.model(system, user, schema, **kwargs)
    monkeypatch.setattr(conversation, "parse_model", parse)
    monkeypatch.setattr(conversation, "web_search_capability", lambda: {"status": "unverified", "provider": "none"})
    monkeypatch.setattr(h, "_schedule_summary", lambda *_: None)
    with h.store.transaction(sid) as state: state["runs"][rid]["status"] = "accepted"
    h.drain(sid)
    assert h.store.get(sid)["runs"][rid]["status"] == "completed"
    restored = ConversationHarness(ConversationStore(HarnessStore(str(tmp_path / "multi-followup.sqlite3"))))
    restored.restore_snapshot(sid, h.export_snapshot(sid))
    monkeypatch.setattr(restored, "_schedule_summary", lambda *_: None)
    accepted = restored.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="第二张和第一张预算分别是多少？"))
    restored.drain(sid)
    assert restored.store.get(sid)["runs"][accepted.run_id]["status"] == "completed"
    assert len(calls) == 1
    changing_topic = True
    baseline.decision = baseline.decision.model_copy(update={"relation": "new_topic"})
    accepted = restored.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="换个话题，什么是梯度？"))
    restored.drain(sid)
    assert restored.store.get(sid)["runs"][accepted.run_id]["status"] == "completed"
