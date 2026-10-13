"""Emit real service recovery events with synthetic model callbacks, no supplier.

Public event pages come from the production route function. This is an offline
protocol replay, not HTTP transport or real upstream cancellation evidence.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix="review-today-invalidation-global-") as global_dir:
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(global_dir) / "isolated.sqlite3")
    from tests import test_conversation_v2 as fixtures
    from agent_service import main
    from agent_service.schemas import ConversationOutput, SessionMessageRequest
    from agent_service.call_errors import ModelCallError
    from agent_service.interruptible_call import pool
    from agent_service.execution_policy import current_budget

    f = fixtures.ConversationTests()
    f.setUp()
    origin = str(uuid.uuid4())
    evidence = str(uuid.uuid4())
    candidate = dict(id=evidence, session_id=origin, policy_version=0, content_version=0,
                     kind="explained", concept="数据库索引", excerpt="索引帮助查找。", dependencies=[])
    f.harness.memory_policy(origin, allowed=True, policy_version=0, content_version=0)
    f.decision = fixtures.intent("question", answer_only=True,
                                memory_selections=[dict(id=evidence, relation="analogy")])
    entered, release = threading.Event(), threading.Event()
    attempts = []
    worker_errors = []

    def model(system, user, schema, **kwargs):
        if schema is not ConversationOutput:
            return f.model(system, user, schema, **kwargs)
        current_budget.get().take()
        kwargs["on_request"]()  # synthetic wire-admission callback only
        attempts.append(schema.__name__)
        if len(attempts) == 1:
            kwargs["on_partial"]({"message": "合成初稿：可以用索引类比理解检索。"})
            raise ModelCallError("SCHEMA", "controlled malformed output after public preview")
        entered.set()
        assert release.wait(5), "bounded synthetic repair wait"
        return ConversationOutput(message="合成修复结果，失效后不得发布。")

    def drain():
        try:
            f.harness.drain(f.sid)
        except BaseException as exc:
            worker_errors.append(repr(exc))

    try:
        with patch("agent_service.conversation.parse_model", side_effect=model), \
             patch.object(f.harness, "start"), patch.object(f.harness, "_schedule_summary"), \
             patch.object(main, "conversation_harness", f.harness):
            accepted = f.harness.accept(f.sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                content="用索引解释 RAG 检索", context={"memory_candidates": [candidate]}))
            worker = threading.Thread(target=drain)
            worker.start()
            assert entered.wait(2)
            before = main.session_events(f.sid)
            assert any(event["stage"] == "response.recovering" for event in before["events"])
            before_cursor = before["last_seq"]
            f.harness.memory_policy(origin, allowed=False, policy_version=1, content_version=0)
            receipt = f.harness.public_run(f.state()["runs"][accepted.run_id])
            assert receipt["status"] == "interrupted" and receipt["revision"] == 2
            release.set(); worker.join(3)
            assert not worker.is_alive() and not worker_errors
            deadline = time.monotonic() + 3
            while True:
                with pool.lock:
                    pending = any(key[0] == f.sid for key in pool.active)
                if not pending:
                    break
                assert time.monotonic() < deadline
                threading.Event().wait(.01)
            after = main.session_events(f.sid, after_seq=before_cursor)
            assert any(event["stage"] == "response.interrupted" for event in after["events"])
            assert not any(m["role"] == "coach" for m in f.state()["messages"])
            assert f.state()["runs"][accepted.run_id]["status"] == "interrupted"
            print(json.dumps(dict(kind="controlled_schema_recovery_invalidation", origin_session_id=origin,
                destination_session_id=f.sid, candidate=candidate, run_id=accepted.run_id,
                before=before, stop_receipt=receipt, after=after, simulated_answer_attempts=len(attempts),
                late_answer_blocked=True, real_supplier_requests=0, daily_database_written=False),
                ensure_ascii=False, indent=2))
    finally:
        release.set()
        deadline = time.monotonic() + 3
        while True:
            with pool.lock:
                pending = any(key[0] == f.sid for key in pool.active)
            if not pending:
                break
            assert time.monotonic() < deadline, "wait for fixture transport bookkeeping"
            threading.Event().wait(.01)
        f.tearDown()
