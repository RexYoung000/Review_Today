"""Validate the real status reply, original budget and native durable state."""
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
        assert sock.connect_ex(("127.0.0.1", setup["port"])) != 0
    assert all(digest(ROOT / name) == value for name, value in setup["provider_config_sha256"].items())
    assert all(digest(ROOT / name) == value for name, value in setup["swift_source_sha256"].items())
    assert all(digest(x["path"]) == x["sha256"] for x in setup["daily_files_before"])
    assert all(digest(ROOT / name) == value for name, value in setup["old_evidence_sha256"].items())
    assert hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest() == setup["project_diff_sha256"]
    old = Path(setup["old_runtime"])
    assert digest(old / "STOP") == setup["old_stop_sha256"] and digest(old / "request-count.json") == setup["old_counter_sha256"]
    assert json.loads((directory / "request-count.json").read_text()) == dict(actual_requests=30, limit=30)
    assert (directory / "STOP").exists()
    before = json.loads((directory / "backend-before.json").read_text())
    after = json.loads((directory / "backend-after.json").read_text())
    for key in ("tasks", "capture_offers", "draft", "pending"):
        assert before[key] == after[key], key
    assert before["messages"] == after["messages"][:len(before["messages"])]
    new = after["messages"][len(before["messages"]):]
    assert len(new) == 2 and [m["role"] for m in new] == ["user", "coach"]
    runs = [r for rid, r in after["runs"].items() if rid not in before["runs"]]
    assert len(runs) == 1 and runs[0]["status"] == "completed" and runs[0]["knowledge_status_reply"]
    run, reply = runs[0], new[1]["content"]
    assert "已成功写入 4 张知识卡" in reply and "还没有整理成知识卡" not in reply
    rows = [json.loads(x) for x in (directory / "live-events.jsonl").read_text().splitlines()]
    def events(kind):
        return [r for r in rows if r["type"] == kind]
    assert len(events("semantic_start")) == len(events("semantic_output")) == len(events("request_entry")) == len(events("sdk_wire_request")) == 1
    assert not events("semantic_error") and not events("budget_blocked") and not events("transport_error")
    assert events("semantic_start")[0]["schema"] == "IntentDecision"
    assert events("semantic_start")[0]["input"]["current_inputs"] == [new[0]["content"]]
    decision = events("semantic_output")[0]["output"]
    assert decision["knowledge_card_status"] and decision["status_context"]["focus"]
    old_messages = {m["message_id"]:m for m in before["messages"]}
    for focus in decision["status_context"]["focus"]:
        assert focus["quote"] in old_messages[focus["message_id"]]["content"]
    assert run["intent"] == decision
    calls = run["model_calls"]
    assert len(calls) == 1 and calls[0]["node"] == "intent" and calls[0]["transport_requests"] == 1 and calls[0]["status"] == "returned"
    assert calls[0]["usage_state"] == "reported" and len(calls[0]["usage"]) == 1
    usage = calls[0]["usage"][0]
    assert calls[0]["request_ids"] == [events("request_entry")[0]["request_id"]] == [usage["request_id"]]
    reported = events("reported_usage")
    assert len(reported) == 1 and reported[0]["request_id"] == usage["request_id"]
    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (20274, 541, 20815)
    posts = [r for r in events("native_http_post") if r["path"].endswith("/messages")]
    assert len(posts) == 1 and posts[0]["status"] == 200
    native = json.loads((directory / "native-disk-read.json").read_text())
    original = json.loads((EVIDENCE.parent / "2026-10-16-native-save-continuation/repair/native-disk-read.json").read_text())
    assert (native["knowledge_count"],native["source_count"],native["fsrs_count"]) == (4,1,4)
    assert sorted(native["cards"],key=lambda c:c["id"]) == sorted(original["cards"],key=lambda c:c["id"])
    messages = {m["id"]:m for m in native["messages"]}
    user, assistant = [messages[m["message_id"]] for m in new]
    assert user["client_id"] == user["id"] and user["delivery"] == "accepted" and user["text"] == new[0]["content"]
    assert user["run_id"] == assistant["run_id"] == run["run_id"]
    assert assistant["text"] == reply and assistant["response_state"] == "complete" and assistant["delivery"] == "received"
    assert sum(r["id"] == run["run_id"] and r["status"] == "completed" for r in native["runs"]) == 1
    native_events = [json.loads(x) for x in (directory / "native-events.jsonl").read_text().splitlines()]
    initial = native_events[0]
    assert len(native["messages"]) == len(initial["messages"]) + 2
    assert not any(r["phase"] == "durable_receipt" for r in native_events)
    for m in initial["messages"]:
        assert messages[m["id"].lower()]["text"] == m["text"]
    for name in ("backend-before.json", "backend-after.json", "live-events.jsonl", "native-events.jsonl", "native-disk-read.json", "request-count.json", "STOP"):
        shutil.copy2(directory / name, EVIDENCE / name)
    result = dict(outcome="PASS", layer="real_model_native_status_query_and_fresh_process_disk_read",
        baseline_commit=setup["baseline_commit"], real_model_requests=1, source_cumulative_requests=29, cumulative_requests=30,
        total_limit=30, retries=0, startup_probes=0, model_substituted=False, model=calls[0]["model"], usage=usage,
        request_id=usage["request_id"], user_message_id=user["id"], assistant_message_id=assistant["id"], run_id=run["run_id"],
        focus=decision["status_context"]["focus"], reply=reply, native_delivery=user["delivery"], native_response_state=assistant["response_state"],
        tasks_invitations_draft_pending_unchanged=True, existing_knowledge_count=4, existing_knowledge_unchanged=True,
        old_history_preserved=True, new_save_receipt_count=0, old_counter_and_stop_preserved=True,
        daily_files_configs_and_project_diff_unchanged=True, app_owned_service_closed=True,
        sdk_wire_request_count=1, outer_httpx_send_observed=bool(events("http_observed")),
        stop_marker_source="local observer after completed result; production request cap already at 30",
        scope="Fresh real status judgment from the original saved checkpoint; startup capability records reused",
        not_covered=["cold startup probes", "new save", "fresh continuous learning-to-save chain", "general semantic accuracy", "VoiceOver", "visual and motion acceptance"],
        qa_source_sha256={name:digest(EVIDENCE/name) for name in ("bootstrap.py","fence.py","NativeStatusRealQA.swift")})
    (EVIDENCE/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("focus","qa_source_sha256")},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
