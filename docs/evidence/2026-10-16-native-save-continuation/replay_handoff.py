"""Offline replay of the real save outputs through the unchanged owner.

Both cases keep the real positive semantic verdict and risk=true. The controlled
comparison supplies a public query but zero search results; it must still refuse
to commit. No provider call, real search, native ACK or daily write is allowed.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    live = Path(setup["directory"])
    directory = Path(tempfile.mkdtemp(prefix="review-today-save-replay-", dir="/tmp"))
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(directory / "default.sqlite3")
    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[key] = ""
    os.environ["REVIEW_TODAY_JEV_TEST"] = "0"
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service.conversation import ConversationHarness
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    from agent_service.schemas import SessionMessageRequest

    records = [json.loads(row) for row in (live / "live-events.jsonl").read_text().splitlines()]
    frozen = {row["schema"]: row["output"] for row in records if row["type"] == "semantic_output"}
    assert set(frozen) == {"ExtractPayload", "SemanticVerdict", "RiskVerdict"}
    assert frozen["SemanticVerdict"]["ok"] and frozen["RiskVerdict"]["risk"]
    seed = json.loads((ROOT / "docs/evidence/2026-10-16-ordinary-check-recheck/complete-after.json").read_text())
    report = []
    for case, query in (("original_missing_query", ""), ("controlled_public_query_empty_results", "RAG 检索相似度与答案可靠性")):
        state = copy.deepcopy(seed)
        offer = state["capture_offers"][setup["offer_id"]]
        offer["public_search_query"] = query
        offer["draft"]["public_search_query"] = query
        sid = state["session_id"]
        store = ConversationStore(HarnessStore(str(directory / (case + ".sqlite3"))))
        harness = ConversationHarness(store)
        with store.transaction(sid) as data:
            data.update(state)
        calls = []
        def response(system, user, schema, **kwargs):
            calls.append(schema.__name__)
            assert schema.__name__ in frozen, "Unexpected extra model call"
            return schema.model_validate(copy.deepcopy(frozen[schema.__name__]))
        with patch("agent_service.conversation.parse_model", side_effect=response), \
                patch.object(harness, "_search", return_value=json.dumps(dict(results=[]))) as search, \
                patch("agent_service.capture.fetch_public_url", side_effect=AssertionError("No live read allowed")) as read:
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content="保存为知识卡",
                mode_preset=state["mode"], operation=dict(kind="capture_save", target_id=offer["id"], version=offer["version"])))
            harness.drain(sid)
        actual = store.get(sid)
        saved_offer = actual["capture_offers"][offer["id"]]
        commit = actual["tasks"][saved_offer["save_task_id"]]
        assert calls == ["ExtractPayload", "SemanticVerdict", "RiskVerdict"], calls
        assert search.call_count == bool(query), search.call_count
        assert not read.called
        assert commit["status"] == "needs_attention" and commit.get("memory_package") is None
        assert saved_offer["status"] == "failed" and not saved_offer["knowledge_ids"]
        row = dict(case=case, public_query=query, frozen_model_calls=calls, search_calls=search.call_count,
                   search_query=search.call_args.args[3] if search.called else None, page_read_calls=read.call_count,
                   save_status=commit["status"], offer_status=saved_offer["status"], actual_saved_ids=saved_offer["knowledge_ids"],
                   remote_model_requests=0, real_searches=0, outcome="PASS")
        report.append(row)
    result = dict(layer="offline_frozen_real_output_handoff", cases=report, production_changed=False,
                  preserves_risk_guard=True, native_ack_simulated=False, actual_request_counter=json.loads((live / "request-count.json").read_text()))
    (EVIDENCE / "handoff-replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
