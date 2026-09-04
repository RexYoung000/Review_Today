"""Explicit real-model timing check; never discovered by the offline test suite.

Uses synthetic inputs and an isolated temporary database, never user knowledge.
PYTHONPATH may point at an older checkout to measure the same cases before/after.
"""
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from datetime import datetime
from unittest.mock import patch
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CASES = [
    ("greeting", "auto", "你好"),
    ("rag_answer", "auto", "RAG 是什么？这次只解释，不安排训练，也不保存。"),
    ("source_lesson", "source_learning", "请用下面资料开始分段教学，先讲第一部分约 400 字，不保存。资料：RAG 包含离线索引和在线问答两部分。离线阶段解析文档、按语义切块、保存段落与出处，并生成向量。在线阶段根据问题检索候选段落，必要时重排，再把问题与相关上下文交给生成模型。评估时分别检查检索召回、引用准确性与回答是否有依据。材料更新后要重新索引变化的段落。请明确区分检索不足和生成不忠实。"),
    ("problem_solving", "problem_solving", "解释 RAG 的工作原理，面试中应怎么回答？请按问题攻克流程带我学习，不保存。"),
]

def main():
    with tempfile.TemporaryDirectory(prefix="review-today-stream-smoke-") as directory:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "checkpoint.sqlite3")
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        store = ConversationStore(HarnessStore(os.environ["REVIEW_TODAY_HARNESS_DB"]))
        harness = ConversationHarness(store)
        for label, mode, content in CASES:
            sid = str(uuid.uuid4())
            start = time.monotonic()
            accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=content, mode_preset=mode))
            local_ms = round((time.monotonic() - start) * 1000)
            with patch("agent_service.conversation.run_capture", side_effect=AssertionError("Smoke tests must not submit knowledge")):
                harness.drain(sid)
            elapsed = round((time.monotonic() - start) * 1000)
            data = store.get(sid)
            run = data["runs"][accepted.run_id]
            created = datetime.fromisoformat(run["created_at"])
            public = next((e for e in data["events"] if e["stage"] == "response.delta" or e.get("message")), None)
            first_ms = round((datetime.fromisoformat(public["occurred_at"]) - created).total_seconds() * 1000) if public else None
            print(json.dumps(dict(case=label, status=run["status"], local_accept_ms=local_ms,
                                  first_public_event_ms=first_ms, total_ms=elapsed,
                                  response_chunks=sum(e["stage"] == "response.delta" for e in data["events"]),
                                  steps=[dict(node=e["node"], model=e["model"], ms=e["duration_ms"], error=e["error_code"])
                                         for e in data["events"] if e.get("duration_ms")],
                                  error=run.get("error_code")), ensure_ascii=False), flush=True)

if __name__ == "__main__": main()
