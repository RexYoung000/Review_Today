"""One controlled learning thread; simulated grading, generation and Mac ACK.

Run from agent-service in its venv. No real supplier or daily database is used.
The trace exercises production state transitions, not semantic teaching quality.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


def inspect():
    from tests.test_knowledge_invitation import KnowledgeInvitationTests
    from tests.test_conversation_v2 import intent
    from tests.test_m1_capture_contract import committing_result
    from agent_service.learning_progress import current_step
    from agent_service.schemas import ConversationOutput
    f = KnowledgeInvitationTests(); f.setUp()
    rows = []
    def record(label):
        state = f.state(); offer = next(iter(state.get("capture_offers", {}).values()), None)
        task = state["tasks"].get(state.get("active_task_id"))
        lesson = state["tasks"][learning_task_id]
        lesson_step = current_step(lesson)
        assert lesson_step is not None and lesson_step["understanding"] == "unknown"
        rows.append(dict(label=label, session_id=f.sid, active_task_id=state.get("active_task_id"),
            step_id=(current_step(task) or {}).get("id") if task else None,
            understanding=(task or {}).get("context", {}).get("understanding", "unknown"),
            learning_step_id=lesson_step["id"],
            learning_step_understanding=lesson_step["understanding"],
            offer=({key: copy.deepcopy(offer.get(key)) for key in
                ("id", "version", "status", "anchor_message_id", "scope_summary", "knowledge_ids", "save_task_id")}
                if offer else None),
            selected_source=(offer or {}).get("draft", {}).get("content"),
            knowledge_generation_callbacks=f.capture.call_count,
            runs=len(state["runs"]), messages=len(state["messages"])))
    try:
        with patch.object(f.harness, "start"), patch.object(f.harness, "_schedule_summary"):
            task = f.start_lesson(); learning_task_id = task["task_id"]
            record("learn without a saved card")
            assert not f.state().get("capture_offers") and f.capture.call_count == 0
            step_id = current_step(task)["id"]
            f.answer(); first = copy.deepcopy(f.offer()); record("answer produces an unsaved invitation")
            assert first["status"] == "offered" and f.capture.call_count == 0
            assert current_step(f.state()["tasks"][task["task_id"]])["id"] == step_id

            f.followup("外部资料也可能过时，需要核对版本。")
            second = copy.deepcopy(f.offer()); record("supplement updates the same invitation")
            assert second["id"] == first["id"] and second["version"] > first["version"]
            f.action(second, "capture_later"); record("defer keeps learning available")
            assert f.offer()["status"] == "deferred" and f.capture.call_count == 0

            corrected = "只有可访问且检索到的新资料才可能帮助回答，仍需核对来源与适用条件。"
            f.followup(corrected, correction=True)
            latest = copy.deepcopy(f.offer()); record("correction replaces the unsaved scope candidate")
            assert latest["id"] == first["id"] and latest["version"] > second["version"]
            assert latest["status"] == "deferred" and corrected in latest["draft"]["content"]
            assert "外部资料也可能过时" not in latest["draft"]["content"]
            f.action(second, "capture_save"); record("an old displayed version cannot generate")
            assert f.capture.call_count == 0 and f.offer()["version"] == latest["version"]

            base = f.model
            def other_topic(system, user, schema, **kwargs):
                if issubclass(schema, ConversationOutput):
                    return ConversationOutput(message="切块重叠有助于保留跨边界上下文。",
                                              learning_concepts=["文档切块重叠"])
                return base(system, user, schema, **kwargs)
            f.decision = intent("question", answer_only=True).model_copy(update={"relation": "new_topic"})
            with patch("agent_service.conversation.parse_model", side_effect=other_topic):
                f.send("只解释另一个知识点：文档切块重叠有什么作用？不要合并到原知识。")
            record("another topic does not enter the old invitation")
            assert f.offer()["draft"] == latest["draft"] and f.offer()["version"] == latest["version"]

            f.capture.return_value = committing_result(latest["draft"]["content"])
            f.action(latest, "capture_save"); record("save freezes the latest corrected source")
            assert f.capture.call_count == 1 and f.capture.call_args.args[1] == latest["draft"]["content"]
            saving = copy.deepcopy(f.offer()); assert saving["status"] == "saving"
            commit = f.state()["tasks"][saving["save_task_id"]]
            ids = [knowledge["id"] for knowledge in commit["memory_package"]["knowledge"]]
            assert commit["status"] == "committing" and not saving.get("knowledge_ids")
            record("generation alone is not a saved result")

            f.harness.acknowledge_task(commit["task_id"], len(commit["events"]), ids)
            record("matching simulated Mac ACK confirms service saved state")
            assert f.offer()["status"] == "saved" and f.offer()["knowledge_ids"] == ids
            assert f.state()["active_task_id"] == task["task_id"]
            assert current_step(f.state()["tasks"][task["task_id"]])["id"] == step_id
            count = len(f.state()["runs"])
            f.harness.acknowledge_task(commit["task_id"], len(commit["events"]), ids)
            record("duplicate ACK does not resume teaching or generate again")
            assert len(f.state()["runs"]) == count and f.capture.call_count == 1
            f.harness.recover(); f.harness.drain(f.sid)
            record("worker recovery preserves the saved result")
            assert f.offer()["status"] == "saved" and f.offer()["knowledge_ids"] == ids
            assert f.capture.call_count == 1
            assert len({row["session_id"] for row in rows}) == 1
            assert len({row["offer"]["id"] for row in rows if row["offer"]}) == 1
            assert len({row["learning_step_id"] for row in rows}) == 1
            return dict(layer="controlled_service_continuous_trace", steps=rows,
                        stage_assertions_passed=len(rows), same_session=True, same_invitation=True,
                        real_supplier_requests=0, daily_database_written=False,
                        native_write=False, simulated_mac_ack=True,
                        semantic_quality_verified=False, production_changed=False)
    finally:
        f.tearDown()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="review-today-evaluation-global-") as directory:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "isolated.sqlite3")
        os.environ["REVIEW_TODAY_LLM_PROVIDER"] = "openai_compatible"
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
