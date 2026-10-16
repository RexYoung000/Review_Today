"""Replay the actual pre-failure lesson with a controlled, grounded update.

The original model message and route are frozen; only the invalid update
metadata is replaced in this isolated fixture. This is not a new real answer.
"""
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
SOURCE = EVIDENCE.parent / "2026-10-16-continuous-acceptance/resumed"


def main():
    directory = Path(tempfile.mkdtemp(prefix="review-today-preview-deferral-replay-", dir="/tmp"))
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[name] = ""
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"),
        REVIEW_TODAY_JEV_TEST="0", REVIEW_TODAY_LLM_PROVIDER="openai_compatible",
        REVIEW_TODAY_SEARCH_PROVIDER="none", REVIEW_TODAY_CONTEXT_PROVIDER="none", REVIEW_TODAY_BROWSER_FALLBACK="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    with patch.object(socket.socket, "connect", side_effect=AssertionError("No network in retained KT-03 replay")), \
            patch.object(socket.socket, "connect_ex", side_effect=AssertionError("No network in retained KT-03 replay")):
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.knowledge_invitation import UPDATE_INSTRUCTION, candidates
        from agent_service.openai_client import ModelCallError
        from agent_service.schemas import ConversationOutput, IntentDecision, SessionMessageRequest, TeachingPreparation
        from agent_service import main as api

        original = json.loads((SOURCE / "phase-03-complete-result.json").read_text())
        failure = json.loads((SOURCE / "backend-after.json").read_text())
        rows = [json.loads(line) for line in (SOURCE / "live-events.jsonl").read_text().splitlines()]
        outputs = [row for row in rows if row["type"] == "semantic_output"]
        frozen = {name: next(row["output"] for row in reversed(outputs) if row["schema"] == name)
                  for name in ("IntentDecision", "TeachingPreparation", "ConversationOutput")}
        decision = IntentDecision.model_validate(frozen["IntentDecision"])
        raw_output = ConversationOutput.model_validate(frozen["ConversationOutput"])
        store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
        harness = ConversationHarness(store)
        sid = original["session_id"]
        with store.transaction(sid) as data:
            data.update(copy.deepcopy(original))
        before = store.get(sid)
        cursor = store.last_seq(before)
        old_offer = next(iter(before["capture_offers"].values()))
        failed_run = list(failure["runs"].values())[-1]
        restored_candidates = candidates(harness, failure, failed_run, decision)
        assert len(restored_candidates) == 1 and restored_candidates[0]["version"] == 2
        try:
            raw_output.validate_request(dict(capture_candidates=restored_candidates))
        except ModelCallError as exc:
            retained_output_rejection = dict(code=exc.code, diagnostic=exc.diagnostic)
        else:
            raise AssertionError("Original invalid new-source quotations must remain rejected")
        assert retained_output_rejection["code"] == "RT.MODEL.SCHEMA"

        calls = []

        def response(system, user, schema, **kwargs):
            payload = json.loads(user)
            calls.append(dict(schema=schema.__name__))
            if schema in (IntentDecision, TeachingPreparation):
                return schema.model_validate(copy.deepcopy(frozen[schema.__name__]))
            assert schema is ConversationOutput, "Unexpected controlled model step"
            offered = payload["capture_candidates"]
            assert len(offered) == 1 and UPDATE_INSTRUCTION in system
            selected = offered[0]
            assert selected["id"] == old_offer["id"] and selected["version"] == 2
            calls[-1].update(candidate_count=1, candidate_version=2, update_instruction=True)
            answer = copy.deepcopy(frozen["ConversationOutput"])
            quote = "相似度衡量的是内容与问题的相关程度，它不衡量来源是否可信"
            conditions = answer["message"].split("- **发布时间**", 1)[1].split("\n\n", 1)[0]
            conditions = "- **发布时间**" + conditions
            previous = old_offer["preview"]["points"][2]
            summary = "高相似度只说明相关；答案仍需对照资料，核对来源和发布时间、产品版本、适用场景。"
            answer["capture_update"] = dict(offer_id=selected["id"], version=selected["version"],
                retained_fragment_ids=[f["id"] for f in selected["fragments"]], evidence_quotes=[quote, conditions],
                scope_summary=summary, preview=dict(points=[
                    dict(text="相似度反映相关程度，不能判断来源是否可信。", evidence_quotes=[quote]),
                    copy.deepcopy(previous),
                    dict(text="核对资料的发布时间、产品版本和适用场景。", evidence_quotes=[conditions])],
                    summary=dict(text=summary, evidence_quotes=[quote, conditions] + previous["evidence_quotes"])))
            return ConversationOutput.model_validate(answer)

        content = [m["content"] for m in failure["messages"] if m["role"] == "user"][-1]
        with patch("agent_service.conversation.parse_model", side_effect=response), \
                patch("agent_service.openai_client._client", side_effect=AssertionError("No real model client")), \
                patch("agent_service.conversation.run_capture", side_effect=AssertionError("Update must not save")), \
                patch.object(api, "conversation_harness", harness):
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                content=content, mode_preset=before["mode"]))
            harness.drain(sid)
            page = api.session_events(sid, after_seq=cursor, recovery_version=before["recovery_version"])

        actual = store.get(sid)
        run = actual["runs"][accepted.run_id]
        updated = actual["capture_offers"][old_offer["id"]]
        assert [call["schema"] for call in calls] == ["IntentDecision", "TeachingPreparation", "ConversationOutput"]
        assert run["status"] == "completed" and run["capture_scope_update"]["version"] == 2
        assert updated["id"] == old_offer["id"] and updated["version"] == 3 and updated["status"] == "offered"
        assert len(updated["preview"]["points"]) == 3 and "产品版本" in updated["preview"]["summary"]["text"]
        assert not updated.get("correction_pending") and not updated["knowledge_ids"]
        assert actual["draft"] is None and actual["pending"] is None
        assert original["messages"] == actual["messages"][:len(original["messages"])]
        assert before["runs"] == {key: actual["runs"][key] for key in before["runs"]}
        assert list(actual["capture_offers"]) == [old_offer["id"]]
        assert actual["active_task_id"] == before["active_task_id"]
        old_plan = before["tasks"][before["active_task_id"]]["context"]["learning_plan"]
        plan = actual["tasks"][actual["active_task_id"]]["context"]["learning_plan"]
        assert plan["current_step_id"] == old_plan["current_step_id"]
        assert [s["understanding"] for s in plan["steps"]] == [s["understanding"] for s in old_plan["steps"]]
        offer_events = [e for e in page["events"] if e["stage"] == "capture_offer"]
        public_offer = offer_events[-1]["payload"]["capture_offer"]
        assert public_offer["preview_points"] == [point["text"] for point in updated["preview"]["points"]]
        assert public_offer["preview_summary"] == updated["preview"]["summary"]["text"]

    setup = json.loads((EVIDENCE / "setup.json").read_text())
    runtime = Path(setup["runtime"])
    for name, sha in setup["runtime_sha256"].items():
        assert hashlib.sha256((runtime / name).read_bytes()).hexdigest() == sha, name
    result = dict(outcome="PASS_CONTROLLED_RETAINED_DATA", decision=238, real_model_requests=0,
        actual_batch_requests=20, limit=30, unused_allowance=10, directory=str(directory), session_id=sid,
        source_checkpoint="../2026-10-16-continuous-acceptance/resumed/phase-03-complete-result.json",
        input=content, run_id=accepted.run_id, calls=calls,
        original_invalid_update_still_rejected=retained_output_rejection,
        fixture="Actual route, preparation and answer message; update metadata/preview deliberately grounded in the controlled fixture, not a new real model result.",
        original_offer_version=old_offer["version"], corrected_candidate_version=2, published_version=updated["version"],
        updated_preview=updated["preview"], knowledge_saved=0, original_history_preserved=True,
        learning_step_and_understanding_preserved=True, original_runtime_files_unchanged=True,
        native_ui_revalidated=False, new_real_model_behavior_verified=False)
    (EVIDENCE / "replay-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (EVIDENCE / "public-page.json").write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "updated_preview"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
