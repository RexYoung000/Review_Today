"""Replay the recorded status route through production code, with zero remote calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def main():
    directory = Path(tempfile.mkdtemp(prefix="review-today-status-scope-", dir="/tmp"))
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[name] = ""
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"), REVIEW_TODAY_JEV_TEST="0",
                      REVIEW_TODAY_LLM_PROVIDER="openai_compatible", REVIEW_TODAY_SEARCH_PROVIDER="none",
                      REVIEW_TODAY_CONTEXT_PROVIDER="none", REVIEW_TODAY_BROWSER_FALLBACK="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service.conversation import ConversationHarness
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    from agent_service import main as api
    from agent_service.schemas import IntentDecision, SessionMessageRequest

    setup = json.loads((EVIDENCE / "setup.json").read_text())
    original = json.loads((ROOT / setup["source_checkpoint"]).read_text())
    frozen = copy.deepcopy(list(original["runs"].values())[-1]["intent"])
    sid = original["session_id"]
    store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
    harness = ConversationHarness(store)
    with store.transaction(sid) as data:
        data.update(copy.deepcopy(original))
    before = store.get(sid)
    # Restoring Tasks into a fresh test database stamps updated_at. Assert this
    # is the only restoration change, then measure query mutations from there.
    for task_id, task in original["tasks"].items():
        assert {k:v for k,v in task.items() if k != "updated_at"} == {
            k:v for k,v in before["tasks"][task_id].items() if k != "updated_at"}
    cursor = store.last_seq(before)
    calls = []

    def response(system, user, schema, **kwargs):
        assert schema is IntentDecision, "Only the already recorded status route may be replayed"
        payload = json.loads(user)
        calls.append(dict(schema=schema.__name__, knowledge_status_input=payload["knowledge_capture_status"],
                          frozen_output_sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()))
        return IntentDecision.model_validate(copy.deepcopy(frozen))

    with patch("agent_service.conversation.parse_model", side_effect=response), \
            patch("agent_service.openai_client._client", side_effect=AssertionError("Remote model client forbidden")), \
            patch("agent_service.conversation.run_capture", side_effect=AssertionError("Status must not save")), \
            patch("socket.create_connection", side_effect=AssertionError("Remote connection forbidden")), \
            patch.object(api, "conversation_harness", harness):
        accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
            content="刚才保存的 RAG 知识卡存好了吗？实际保存了几张？", mode_preset=original["mode"]))
        harness.drain(sid)
        page = api.session_events(sid, after_seq=cursor, recovery_version=original["recovery_version"])

    actual = store.get(sid)
    run = actual["runs"][accepted.run_id]
    reply = actual["messages"][-1]["content"]
    assert len(calls) == 1 and run["status"] == "completed" and run["knowledge_status_reply"]
    assert "已成功写入 4 张知识卡" in reply and "还没有整理成知识卡" not in reply
    assert before["tasks"] == actual["tasks"]
    assert original["capture_offers"] == actual["capture_offers"]
    assert original["draft"] == actual["draft"] and original["pending"] == actual["pending"]
    assert original["messages"] == actual["messages"][:len(original["messages"])]
    old_runtime = Path(setup["old_runtime"])
    assert (old_runtime / "STOP").exists()
    assert json.loads((old_runtime / "request-count.json").read_text())["actual_requests"] == 29
    (EVIDENCE / "public-page.json").write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n")
    (EVIDENCE / "after.json").write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n")
    result = dict(layer="controlled_production_harness_and_public_event_page", baseline_commit=setup["baseline_commit"],
                  source_checkpoint_sha256=setup["source_sha256"], directory=str(directory), session_id=sid,
                  source_cursor=cursor, source_recovery_version=original["recovery_version"],
                  run_id=accepted.run_id, controlled_model_invocations=calls, real_model_requests=0,
                  actual_original_requests=29, original_stop_preserved=True, reply=reply,
                  tasks_unchanged=True, invitations_unchanged=True, prior_messages_unchanged=True,
                  event_count=len(page["events"]), outcome="PASS")
    (EVIDENCE / "replay-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:v for k,v in result.items() if k!='controlled_model_invocations'}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
