"""Controlled live orchestration: inspect actual replacement/queue/stop model input."""
import json
import threading
import time
from unittest.mock import patch

from tests import test_conversation_v2 as fixtures
from agent_service.schemas import ConversationOutput
from agent_service.interruptible_call import pool


def inspect(action):
    f = fixtures.ConversationTests()
    f.setUp()
    f.decision = fixtures.intent("question", answer_only=True)
    entered, release, exited = [threading.Event() for _ in range(3)]
    calls = []

    def model(system, user, schema, **kwargs):
        if not issubclass(schema, ConversationOutput):
            return f.model(system, user, schema, **kwargs)
        payload = json.loads(user)
        inputs = payload["context"]["current_inputs"]
        calls.append(list(inputs))
        if len(calls) == 1:
            entered.set()
            try:
                assert release.wait(5)
                return ConversationOutput(message="原请求的完成回答")
            finally:
                exited.set()
        return ConversationOutput(message="已消费：" + "；".join(inputs))

    try:
        with patch("agent_service.conversation.parse_model", side_effect=model), patch.object(f.harness, "start"), \
             patch.object(f.harness, "_schedule_summary"):
            original = f.send("解释原主题", drain=False)
            worker = threading.Thread(target=f.harness.drain, args=(f.sid,))
            worker.start()
            assert entered.wait(2)
            later = None
            if action == "steer":
                # One serialized burst, before the replacement can read state.
                with f.store._lock:
                    first = f.send("用初学者的说法", drain=False)
                    later = f.send("限制在两句话内", drain=False)
                assert first.run_id == later.run_id == original.run_id
                worker.join(2)
                assert not worker.is_alive(), "replacement must not wait for obsolete transport"
            else:
                later = f.send("随后解释另一个主题", delivery="queue", drain=False)
                assert f.state()["runs"][later.run_id]["status"] == "queued"
                assert len(calls) == 1, "queue must not enter the current request"
                if action == "stop":
                    f.control(original.run_id, "stop")
                    worker.join(2)
                    assert not worker.is_alive()
            release.set()
            worker.join(3)
            assert not worker.is_alive() and exited.wait(2)
            data = f.state()
            replies = [m["content"] for m in data["messages"] if m["role"] == "coach"]
            if action == "steer":
                assert calls[-1] == ["解释原主题", "用初学者的说法", "限制在两句话内"]
                assert replies == ["已消费：解释原主题；用初学者的说法；限制在两句话内"]
            elif action == "queue":
                assert calls == [["解释原主题"], ["随后解释另一个主题"]]
                assert len(replies) == 2 and data["runs"][later.run_id]["status"] == "completed"
            else:
                assert data["paused"] and not replies and len(calls) == 1
                assert data["runs"][later.run_id]["status"] == "queued"
            return {"case": action, "answer_inputs": calls, "replies": replies,
                    "paused": data["paused"], "run_statuses": [r["status"] for r in data["runs"].values()],
                    "user_message_count": sum(m["role"] == "user" for m in data["messages"]),
                    "knowledge_generation_calls": f.capture.call_count,
                    "real_model_calls": 0, "passed": True}
    finally:
        release.set()
        deadline = time.monotonic() + 3
        while True:
            with pool.lock:
                pending = any(key[0] == f.sid for key in pool.active)
            if not pending:
                break
            assert time.monotonic() < deadline, "fixture must wait for transport bookkeeping before cleanup"
            threading.Event().wait(.01)
        f.tearDown()


print(json.dumps({"kind": "controlled_service_input_consumption",
                  "samples": [inspect(action) for action in ["steer", "queue", "stop"]]},
                 ensure_ascii=False, indent=2))
