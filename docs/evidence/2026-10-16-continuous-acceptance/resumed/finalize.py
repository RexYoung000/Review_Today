"""Verify stopped trial, all real requests, empty native knowledge and protection."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    live = EVIDENCE.parent / "live"
    setup = json.loads((live / "setup.json").read_text())
    qa = Path(setup["directory"])
    assert json.loads((qa / "request-count.json").read_text()) == {"actual_requests": 20, "limit": 30}
    assert (qa / "STOP").read_text().startswith("STOP: EVAL-03 same-topic update reached final")
    listener = subprocess.run(["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    processes = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    assert not any(str(qa) in line and "finalize.py" not in line for line in processes.splitlines())
    assert not any("/StartupDiagnosticQA.app/Contents/MacOS/" in line or "/ContinuousResumeQA.app/Contents/MacOS/" in line for line in processes.splitlines())
    data = json.loads((EVIDENCE / "backend-after.json").read_text())
    runs = list(data["runs"].values())
    assert len(runs) == 4 and [r["status"] for r in runs] == ["completed"] * 3 + ["retryable_failed"]
    assert runs[-1]["error_code"] == "RT.MODEL.SCHEMA"
    assert len(data["messages"]) == 7 and sum(m["role"] == "user" for m in data["messages"]) == 4
    assert len(data["capture_offers"]) == 1
    offer = next(iter(data["capture_offers"].values()))
    assert offer["version"] == 2 and offer["status"] == "invalidated" and not offer["knowledge_ids"]
    partial = json.loads((EVIDENCE / "phase-02-incomplete-result.json").read_text())
    assert not partial["capture_offers"]
    practices = next(iter(partial["tasks"].values()))["context"]["practice"]
    assert len(practices) == 1 and not practices[0]["evaluation"]["passed"] and not practices[0]["verified_concepts"]
    complete = json.loads((EVIDENCE / "phase-03-complete-result.json").read_text())
    before_offer = next(iter(complete["capture_offers"].values()))
    assert before_offer["id"] == offer["id"] and before_offer["version"] == 1 and before_offer["status"] == "offered"
    assert len(before_offer["preview"]["points"]) == 3 and before_offer["preview"]["summary"]["text"]
    progress = next(iter(data["tasks"].values()))["context"]["learning_plan"]
    assert progress["current_step_id"] == progress["steps"][0]["id"]
    assert all(s["understanding"] == "unknown" for s in progress["steps"])
    rows = [json.loads(line) for line in (qa / "live-events.jsonl").read_text().splitlines()]
    def events(kind):
        return [r for r in rows if r["type"] == kind]
    entries, wires, responses, reported = [events(k) for k in ("request_entry", "sdk_wire_request", "sdk_wire_response", "reported_usage")]
    assert all(len(values) == 20 for values in (entries, wires, responses, reported))
    identities = {r["request_id"] for r in entries}
    assert len(identities) == 20 and {r["number"] for r in entries} == set(range(1, 21))
    for values in (wires, responses, reported):
        assert {r["request_id"] for r in values} == identities
    assert all(r["status"] == 200 for r in responses)
    assert not any(events(k) for k in ("sdk_guard_blocked", "budget_blocked", "transport_error", "same_batch_verified_probe_reused"))
    assert len(events("fresh_continuous_bootstrap")) == 1
    posts = [r for r in events("native_http_post") if r["path"].endswith("/messages")]
    assert len(posts) == 4 and all(r["status"] == 200 for r in posts)
    with sqlite3.connect(f"file:{qa / 'checkpoint.sqlite3'}?mode=ro", uri=True) as db:
        batches = [json.loads(r[0]) for r in db.execute("SELECT payload FROM agent_capability_batches")]
    assert len(batches) == 1 and batches[0]["rounds"] == 1 and batches[0]["status"] == "finished"
    probe_calls = batches[0]["calls"]
    run_calls = [call for run in runs for call in run["model_calls"]]
    assert sum(c["transport_requests"] for c in probe_calls) == 8
    assert sum(c["transport_requests"] for c in run_calls) == 12
    calls = probe_calls + run_calls
    assert len(calls) == 20 and all(c["transport_requests"] == 1 and c["usage_state"] == "reported" and len(c["usage"]) == 1 for c in calls)
    assert {c["request_ids"][0] for c in calls} == identities
    audited = {r["request_id"]: r["usage"] for r in reported}
    for call in calls:
        usage = call["usage"][0]
        assert usage["request_id"] == call["request_ids"][0]
        assert all(usage[k] == audited[usage["request_id"]][k] for k in ("input_tokens", "output_tokens", "total_tokens"))
    totals = {key: sum(r["usage"][key] for r in reported) for key in ("input_tokens", "output_tokens", "total_tokens")}
    native = json.loads((qa / "native-disk-read.json").read_text())
    assert native["knowledge_count"] == native["source_count"] == native["fsrs_count"] == 0 and not native["cards"]
    assert native["sessions"] == [{"cursor": 121, "id": setup["session_id"]}]
    assert {r["id"]: r["status"] for r in native["runs"]} == {r["run_id"]: r["status"] for r in runs}
    messages = {m["id"]: m for m in native["messages"]}
    assert len(messages) == 8
    for message in data["messages"]:
        stored = messages[message["message_id"]]
        assert stored["text"] == message["content"] and stored["run_id"] == message["run_id"]
        assert stored["response_state"] == "complete"
        if message["role"] == "user":
            assert stored["client_id"] == stored["id"] and stored["delivery"] == "accepted"
    response = runs[-1]["active_response"]
    failed_message = messages[response["response_id"]]
    assert failed_message["text"] == response["text"] and failed_message["response_state"] == response["status"] == "failed"
    native_events = [json.loads(line) for line in (qa / "native-resume-events.jsonl").read_text().splitlines()]
    assert not any(e["phase"] == "durable_receipt" for e in native_events)
    projection = json.loads(native_events[-1]["capture_offers_json"])
    assert [(o["id"], o["version"], o["status"]) for o in projection] == [(offer["id"], 2, "invalidated")]
    protected = {}
    for key in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256", "prior_evidence_sha256"):
        assert all(digest(ROOT / name) == expected for name, expected in setup[key].items()), key
        protected[key] = dict(count=len(setup[key]), unchanged=True)
    assert all(digest(x["path"]) == x["sha256"] for x in setup["daily_files_before"])
    original_manifest = json.loads((live / "artifact-sha256.json").read_text())
    assert all(digest(live / name) == expected for name, expected in original_manifest.items())
    assert digest(qa / "native-disk-read-before-resume.json") == digest(live / "native-disk-read.json")
    assert digest(qa / "startup-HOLD-before-resume.txt") == digest(live / "STOP")
    assert digest(Path(setup["native_app"]) / "Contents/MacOS/ContinuousQA") == setup["native_binary_sha256"]
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == setup["project_diff_sha256"]
    prior = Path(setup["prior_runtime"])
    assert digest(prior / "STOP") == setup["prior_stop_sha256"]
    assert digest(prior / "request-count.json") == setup["prior_counter_sha256"]
    for name in ("request-count.json", "STOP", "native-resume-events.jsonl", "native-disk-read.json", "live-events.jsonl"):
        shutil.copy2(qa / name, EVIDENCE / name)
    (EVIDENCE / "capability-ledger.json").write_text(json.dumps(batches, ensure_ascii=False, indent=2) + "\n")
    shutil.copy2(live / "native-reader-source.json", EVIDENCE / "native-reader-source.json")
    result = dict(outcome="FAILED_AT_SAME_TOPIC_UPDATE", decision=237, actual_requests=20, limit=30, unused_allowance=10,
        startup_probe_requests=8, conversation_requests=12, startup_interrupted_then_resumed=True,
        same_native_and_backend_session=True, new_message_posts=4, native_runs=4, native_messages=8,
        reported_usage_requests=20, unknown_usage_requests=0, reported_tokens=totals,
        incomplete_answer_rejected=True, complete_followup_created_preview=True, preview_points=3,
        same_topic_update_failed=True, final_error="RT.MODEL.SCHEMA", current_offer_version=2,
        current_offer_status="invalidated", knowledge_saved=0, source_saved=0, native_save_clicked=False,
        other_topic_save_details_status_progress_acceptance="not run after failed gate",
        independent_native_disk=True, failed_partial_preserved_as_failed=True,
        native_and_service_closed=True, protected=protected, daily_files_unchanged=len(setup["daily_files_before"]),
        original_startup_archive_unchanged=True, old_batch_30_and_stop_unchanged=True,
        production_changed=False, daily_app_replaced=False, final_product_acceptance=False,
        retained_data_replay="same-topic-replay.json", proposed_fix="not yet authorized")
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
