"""Verify the closed zero-model native input run and preserve scoped evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", setup["port"])) != 0, "App-owned service must be closed"
    assert all(digest(ROOT / name) == value for name, value in setup["provider_config_sha256"].items())
    assert all(digest(ROOT / name) == value for name, value in setup["swift_source_sha256"].items())
    assert all(digest(x["path"]) == x["sha256"] for x in setup["daily_files_before"])
    assert all(digest(ROOT / name) == value for name, value in setup["old_evidence_sha256"].items())
    old = Path(setup["old_runtime"])
    assert digest(old / "STOP") == setup["old_stop_sha256"]
    assert digest(old / "request-count.json") == setup["old_counter_sha256"]
    assert hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest() == setup["project_diff_sha256"]
    before = json.loads((directory / "backend-before.json").read_text())
    after = json.loads((directory / "backend-after.json").read_text())
    for key in ("tasks", "capture_offers", "draft", "pending"):
        assert before[key] == after[key], key
    assert before["messages"] == after["messages"][:len(before["messages"])]
    new_messages = after["messages"][len(before["messages"]):]
    assert len(new_messages) == 2 and [x["role"] for x in new_messages] == ["user", "coach"]
    new_runs = [r for rid, r in after["runs"].items() if rid not in before["runs"]]
    assert len(new_runs) == 1 and new_runs[0]["status"] == "completed" and new_runs[0]["knowledge_status_reply"]
    rid = new_runs[0]["run_id"]
    reply = new_messages[1]["content"]
    assert "已成功写入 4 张知识卡" in reply and "还没有整理成知识卡" not in reply
    rows = [json.loads(x) for x in (directory / "service-audit.jsonl").read_text().splitlines()]
    assert sum(x["type"] == "frozen_status_route" for x in rows) == 1
    assert not any(x["type"].startswith("forbidden") for x in rows)
    posts = [x for x in rows if x["type"] == "local_http" and x["method"] == "POST" and x["path"].endswith("/messages")]
    assert len(posts) == 1 and posts[0]["status"] == 200
    native = json.loads((directory / "native-disk-read.json").read_text())
    original_native = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/repair/native-disk-read.json").read_text())
    assert (native["knowledge_count"], native["source_count"], native["fsrs_count"]) == (4, 1, 4)
    assert sorted(native["cards"], key=lambda x:x["id"]) == sorted(original_native["cards"], key=lambda x:x["id"])
    native_messages = {m["id"]:m for m in native["messages"]}
    user = native_messages[new_messages[0]["message_id"]]
    coach = native_messages[new_messages[1]["message_id"]]
    # Production records the service's MessageAccepted.status, not a UI label.
    assert user["text"] == new_messages[0]["content"] and user["delivery"] == "accepted" and user["client_id"] == user["id"]
    assert user["run_id"] == rid and coach["run_id"] == rid
    assert coach["text"] == reply and coach["response_state"] == "complete" and coach["role"] == "assistant" and coach["delivery"] == "received"
    assert sum(r["id"] == rid and r["status"] == "completed" for r in native["runs"]) == 1
    initial = json.loads((directory / "native-events.jsonl").read_text().splitlines()[0])
    assert len(native["messages"]) == len(initial["messages"]) + 2
    for message in initial["messages"]:
        actual = native_messages[message["id"].lower()]
        assert message["text"] == actual["text"] and message["role"] == actual["role"]
    native_events = [json.loads(x) for x in (directory / "native-events.jsonl").read_text().splitlines()]
    assert not any(x["phase"] == "durable_receipt" for x in native_events)
    for name in ("backend-before.json", "backend-after.json", "service-audit.jsonl", "native-events.jsonl", "native-disk-read.json"):
        shutil.copy2(directory / name, EVIDENCE / name)
    result = dict(outcome="PASS", baseline_commit=setup["baseline_commit"],
        layer="native_input_outbox_local_http_production_harness_sync_and_fresh_disk_read",
        real_model_requests=0, frozen_router_invocations=1, synthetic_capability_ready=True,
        native_input_tested=True, user_entry="Existing native learning input, Return", native_message_post_count=1,
        user_message_id=user["id"], coach_message_id=coach["id"], run_id=rid, reply=reply,
        native_delivery=user["delivery"], native_reply_state=coach["response_state"],
        tasks_invitations_draft_pending_unchanged=True, existing_knowledge_unchanged=True,
        native_knowledge_count=4, original_history_unchanged=True, new_save_receipt_count=0,
        old_counter=29, original_stop_preserved=True, daily_files_and_configs_unchanged=True,
        service_closed=True, not_covered=["fresh model intent", "startup probes", "new save", "continuous fresh RAG chain", "VoiceOver", "motion and resize review", "Rex acceptance"])
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
