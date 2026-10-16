"""Replay the real invalid preview, then a controlled repair through the Harness."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
SOURCE = EVIDENCE.parent / "2026-10-16-preview-real-recheck"


def main():
    directory = Path(tempfile.mkdtemp(prefix="review-today-preview-repair-replay-", dir="/tmp"))
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[name] = ""
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"),
        REVIEW_TODAY_JEV_TEST="0", REVIEW_TODAY_LLM_PROVIDER="openai_compatible",
        REVIEW_TODAY_SEARCH_PROVIDER="none", REVIEW_TODAY_CONTEXT_PROVIDER="none", REVIEW_TODAY_BROWSER_FALLBACK="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    with patch.object(socket.socket, "connect", side_effect=AssertionError("No network in retained KT-04 replay")), \
            patch.object(socket.socket, "connect_ex", side_effect=AssertionError("No network in retained KT-04 replay")):
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.openai_client import ModelCallError
        from agent_service.schemas import ConversationOutput, IntentDecision, SessionMessageRequest, TeachingPreparation
        from agent_service.topic_capture import public
        from agent_service import main as api

        original = json.loads((SOURCE / "before-input.json").read_text())
        real_after = json.loads((SOURCE / "backend-after.json").read_text())
        rows = [json.loads(line) for line in (SOURCE / "live-events.jsonl").read_text().splitlines()]
        outputs = [row for row in rows if row["type"] == "semantic_output"]
        frozen = {name: next(row["output"] for row in reversed(outputs) if row["schema"] == name)
                  for name in ("IntentDecision", "TeachingPreparation", "ConversationOutput")}
        raw = ConversationOutput.model_validate(frozen["ConversationOutput"])
        actual_payload = next(row["input"] for row in rows if row["type"] == "semantic_start" and row.get("schema") == "ConversationOutput")
        try:
            raw.validate_request(actual_payload)
        except ModelCallError as error:
            original_errors = json.loads(error.diagnostic)
        else:
            raise AssertionError("The retained invalid update preview must now fail before publication")
        assert original_errors == [dict(field=["capture_update", "preview", "points", 1, "evidence_quotes", index],
                                       type="capture_update_preview_grounding") for index in (0, 1)]
        store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
        harness = ConversationHarness(store)
        sid = original["session_id"]
        with store.transaction(sid) as data:
            data.update(copy.deepcopy(original))
        before = store.get(sid)
        cursor = store.last_seq(before)
        old_offer = next(iter(before["capture_offers"].values()))
        calls = []
        answer_payloads = []

        def response(system, user, schema, **kwargs):
            payload = json.loads(user)
            calls.append(dict(schema=schema.__name__))
            if schema in (IntentDecision, TeachingPreparation):
                return schema.model_validate(copy.deepcopy(frozen[schema.__name__]))
            assert schema is ConversationOutput, "Unexpected controlled model step"
            answer_payloads.append(copy.deepcopy(payload["capture_candidates"]))
            assert len(answer_payloads[-1]) == 1 and answer_payloads[-1][0]["version"] == 2
            output = copy.deepcopy(frozen["ConversationOutput"])
            if len(answer_payloads) == 1:
                kwargs.get("on_partial", lambda _: None)(output)
                calls[-1]["fixture"] = "unmodified actual invalid preview"
            else:
                assert len(answer_payloads) == 2 and answer_payloads[0] == answer_payloads[1]
                for detail in original_errors:
                    assert json.dumps(detail, ensure_ascii=False) in system
                selected = answer_payloads[-1][0]
                generated = output["capture_update"]["evidence_quotes"]
                prior = next(f["text"] for f in selected["fragments"] if "生成模型仍可能误解资料" in f["text"])
                # This fixture represents a model reorganizing the complete
                # preview from the same valid sources, not server-side pruning.
                output["capture_update"]["preview"] = dict(points=[
                    dict(text="相似度只说明内容与问题相关，来源可信度需要单独核对。", evidence_quotes=[generated[0]]),
                    dict(text="生成模型可能误解资料、遗漏限制或添加无依据内容，答案仍需对照依据。", evidence_quotes=[prior]),
                    dict(text="旧版本说明可能不再适用，应核对来源、发布时间、产品版本和适用场景。", evidence_quotes=[generated[3], generated[4]])],
                    summary=dict(text="高相似度不能保证答案可靠，应核对来源、资料适用条件和生成是否忠实。",
                        evidence_quotes=[generated[0], prior, generated[4]]))
                calls[-1].update(fixture="controlled grounded complete preview", concrete_original_errors_received=True)
            return ConversationOutput.model_validate(output)

        content = real_after["messages"][-2]["content"]
        with patch("agent_service.conversation.parse_model", side_effect=response), \
                patch("agent_service.openai_client._client", side_effect=AssertionError("No real model client")), \
                patch("agent_service.conversation.run_capture", side_effect=AssertionError("Preview must not save")), \
                patch.object(api, "conversation_harness", harness):
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                content=content, mode_preset=before["mode"]))
            harness.drain(sid)
            page = api.session_events(sid, after_seq=cursor, recovery_version=before["recovery_version"])
        actual = store.get(sid)
        run = actual["runs"][accepted.run_id]
        offer = actual["capture_offers"][old_offer["id"]]
        assert [row["schema"] for row in calls] == ["IntentDecision", "TeachingPreparation", "ConversationOutput", "ConversationOutput"]
        assert run["status"] == "completed" and offer["version"] == 3 and offer["preview_version"] == 3
        assert offer["status"] == "offered" and not offer["knowledge_ids"] and not offer.get("correction_pending")
        assert len(public(offer)["preview_points"]) == 3 and public(offer)["preview_summary"]
        assert original["messages"] == actual["messages"][:len(original["messages"])]
        assert before["runs"] == {key: actual["runs"][key] for key in before["runs"]}
        assert actual["draft"] is None and actual["pending"] is None
        assert actual["active_task_id"] == before["active_task_id"]
        old_plan = before["tasks"][before["active_task_id"]]["context"]["learning_plan"]
        plan = actual["tasks"][actual["active_task_id"]]["context"]["learning_plan"]
        assert plan["current_step_id"] == old_plan["current_step_id"]
        assert [s["understanding"] for s in plan["steps"]] == [s["understanding"] for s in old_plan["steps"]]
        failures = [e for e in page["events"] if e["stage"] == "model_attempt_failed"]
        assert len(failures) == 1 and json.loads(failures[0]["detail_summary"]) == original_errors
        offer_events = [e for e in page["events"] if e["stage"] == "capture_offer"]
        assert len(offer_events) == 1 and offer_events[0]["payload"]["capture_offer"] == public(offer)
        replies = [m for m in actual["messages"] if m["run_id"] == accepted.run_id and m["role"] == "coach"]
        assert len(replies) == 1 and replies[0]["content"] == frozen["ConversationOutput"]["message"]
        started = [e["payload"]["response"]["response_id"] for e in page["events"] if e["stage"] == "response.started"]
        assert started == [replies[0]["message_id"]]
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    trial = Path(setup["protected"]["directory"])
    assert hashlib.sha256((trial / "request-count.json").read_bytes()).hexdigest() == setup["trial_counter_sha256"]
    assert hashlib.sha256((trial / "STOP").read_bytes()).hexdigest() == setup["trial_stop_sha256"]
    result = dict(outcome="PASS_CONTROLLED_REAL_DATA_REPAIR", decision=239, real_model_requests=0,
        original_total_requests=23, original_limit=30, unused_allowance=7,
        directory=str(directory), source_checkpoint="../2026-10-16-preview-real-recheck/before-input.json",
        session_id=sid, run_id=accepted.run_id, calls=calls, original_errors=original_errors,
        original_output_rejected_before_publication=True, existing_single_repair_used=True,
        candidate_version=2, published_version=3, preview=public(offer), published_once=True,
        one_stable_response_identity=True, original_history_preserved=True, learning_progress_preserved=True,
        knowledge_saved=0, original_trial_counter_and_stop_preserved=True,
        fixture="Real first output, route/preparation/message; second preview is a controlled complete reorganization from selected sources, not a new real model result.",
        native_ui_revalidated=False, new_real_model_repair_verified=False)
    (EVIDENCE / "replay-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (EVIDENCE / "public-page.json").write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "preview"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
