"""Verify the stopped real subcheck, accounting, native disk and protected data."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    assert json.loads((directory / "request-count.json").read_text()) == dict(actual_requests=26, limit=30)
    assert (directory / "STOP").read_text().startswith("STOP: KT-04 single real preview recheck finished at 26/30")
    rows = [json.loads(line) for line in (directory / "live-events.jsonl").read_text().splitlines()]
    events = lambda kind: [row for row in rows if row["type"] == kind]
    entry, wires, responses, reported = [events(kind) for kind in ("request_entry", "sdk_wire_request", "sdk_wire_response", "reported_usage")]
    assert all(len(values) == 3 for values in (entry, wires, responses, reported))
    identities = {row["request_id"] for row in entry}
    assert len(identities) == 3 and {r["number"] for r in entry} == {24, 25, 26}
    assert all({r["request_id"] for r in values} == identities for values in (wires, responses, reported))
    assert all(r["status"] == 200 for r in responses)
    assert not any(events(kind) for kind in ("sdk_guard_blocked", "budget_blocked", "transport_error", "semantic_error"))
    starts = events("semantic_start")
    assert [r["schema"] for r in starts] == ["IntentDecision", "TeachingPreparation", "ConversationOutput"]
    assert len(events("same_batch_verified_probe_reused")) == 1
    posts = [r for r in events("native_http_post") if r["path"].endswith("/messages")]
    assert len(posts) == 1 and posts[0]["status"] == 200
    payload = starts[-1]["input"]
    assert len(payload["capture_candidates"]) == 1 and payload["capture_candidates"][0]["version"] == 2
    before = json.loads((EVIDENCE / "before-input.json").read_text())
    actual = json.loads((EVIDENCE / "backend-after.json").read_text())
    original = json.loads((ROOT / setup["source_checkpoint"]).read_text())
    run = list(actual["runs"].values())[-1]
    assert len(actual["runs"]) == 5 and run["status"] == "completed" and not run.get("error_code")
    assert before["runs"] == {key: actual["runs"][key] for key in before["runs"]}
    assert original["messages"] == actual["messages"][:len(original["messages"])]
    assert len(actual["messages"]) == len(original["messages"]) + 2 == 9
    new_input, reply = actual["messages"][-2:]
    assert new_input["role"] == "user" and reply["role"] == "coach"
    assert new_input["content"] == original["messages"][-1]["content"]
    assert reply["content"] == events("semantic_output")[-1]["output"]["message"]
    assert actual["active_task_id"] == original["active_task_id"]
    old_plan = original["tasks"][original["active_task_id"]]["context"]["learning_plan"]
    plan = actual["tasks"][actual["active_task_id"]]["context"]["learning_plan"]
    assert plan["current_step_id"] == old_plan["current_step_id"]
    assert [(s["id"], s["understanding"]) for s in plan["steps"]] == [(s["id"], s["understanding"]) for s in old_plan["steps"]]
    offer = next(iter(actual["capture_offers"].values()))
    assert list(actual["capture_offers"]) == list(original["capture_offers"])
    assert offer["version"] == 3 and offer["status"] == "offered" and not offer["knowledge_ids"]
    assert "产品版本" in offer["scope_summary"] and len(offer["preview_points"]) == 4
    assert offer["preview_summary"] and offer["preview_version"] == 3
    assert not offer.get("correction_pending") and actual["draft"] is None and actual["pending"] is None
    with sqlite3.connect(f"file:{directory / 'checkpoint.sqlite3'}?mode=ro", uri=True) as db:
        batches = [json.loads(row[0]) for row in db.execute("SELECT payload FROM agent_capability_batches")]
    assert len(batches) == 1 and batches[0]["status"] == "finished" and batches[0]["rounds"] == 1
    probes = batches[0]["calls"]
    run_calls = [call for r in actual["runs"].values() for call in r["model_calls"]]
    assert len(probes) == 8 and sum(call["transport_requests"] for call in run_calls) == 15
    assert all(call["usage_state"] == "reported" for call in run["model_calls"])
    assert {call["request_ids"][0] for call in run["model_calls"]} == identities
    audit_usage = {row["request_id"]: row["usage"] for row in reported}
    for call in run["model_calls"]:
        usage = call["usage"][0]
        assert all(usage[key] == audit_usage[usage["request_id"]][key] for key in ("input_tokens", "output_tokens", "total_tokens"))
    totals = {key: sum(row["usage"][key] for row in reported) for key in ("input_tokens", "output_tokens", "total_tokens")}
    native = json.loads((directory / "native-disk-read.json").read_text())
    assert native["knowledge_count"] == native["source_count"] == native["fsrs_count"] == 0 and not native["cards"]
    assert len(native["messages"]) == 10 and len(native["runs"]) == 5
    assert {r["id"]: r["status"] for r in native["runs"]} == {r["run_id"]: r["status"] for r in actual["runs"].values()}
    native_messages = {m["id"]: m for m in native["messages"]}
    for message in actual["messages"]:
        stored = native_messages[message["message_id"]]
        assert stored["text"] == message["content"] and stored["run_id"] == message["run_id"]
        assert stored["response_state"] == "complete"
    assert native_messages[new_input["message_id"]]["client_id"] == new_input["message_id"]
    assert native_messages[new_input["message_id"]]["delivery"] == "accepted"
    failed = list(original["runs"].values())[-1]["active_response"]
    assert native_messages[failed["response_id"]]["text"] == failed["text"]
    assert native_messages[failed["response_id"]]["response_state"] == "failed"
    snapshots = [json.loads(line) for line in (directory / "native-recheck-events.jsonl").read_text().splitlines()]
    assert not any(row["phase"] == "durable_receipt" for row in snapshots)
    projected = json.loads(snapshots[-1]["capture_offers_json"])
    assert len(projected) == 1 and projected[0]["id"] == offer["id"]
    assert projected[0]["version"] == 3 and projected[0]["status"] == "offered"
    assert projected[0]["preview_points"] == offer["preview_points"]
    assert projected[0]["preview_summary"] == offer["preview_summary"]
    assert native["sessions"] == [dict(cursor=snapshots[-1]["cursor"], id=setup["session_id"])]
    diagnosis = json.loads((EVIDENCE / "preview-diagnosis.json").read_text())
    assert diagnosis["outcome"] == "REAL_FIRST_OUTPUT_GROUNDED_PREVIEW_PUBLISHED" and diagnosis["diagnostic_new_model_requests"] == 0
    protected = {}
    for group in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256", "protected_archive_sha256"):
        assert all(digest(ROOT / path) == sha for path, sha in setup[group].items()), group
        protected[group] = len(setup[group])
    daily = []
    for item in setup["daily_files_before"]:
        path = Path(item["path"])
        if path.exists():
            assert digest(path) == item["sha256"]
            daily.append(dict(path=str(path), status="byte_identical"))
        else:
            assert path.name in {"agent-harness.sqlite3-wal", "agent-harness.sqlite3-shm"}
            daily.append(dict(path=str(path), status="absent_transient_after_offline_default_store_import"))
    assert sum(item["status"] == "byte_identical" for item in daily) == 5
    assert next(x for x in setup["daily_files_before"] if x["path"].endswith("agent-harness.sqlite3-wal"))["sha256"] == hashlib.sha256(b"").hexdigest()
    assert digest(next(x["path"] for x in setup["daily_files_before"] if x["path"].endswith("agent-harness.sqlite3"))) == next(x["sha256"] for x in setup["daily_files_before"] if x["path"].endswith("agent-harness.sqlite3"))
    parent = Path(setup["parent_runtime"])
    assert all(digest(parent / name) == sha for name, sha in setup["parent_runtime_sha256"].items())
    assert digest(parent / "STOP") == setup["parent_stop_sha256"]
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == setup["project_diff_sha256"]
    app = Path(setup["native_app"])
    backup = Path(setup["prior_native_app_backup"])
    assert all(digest(app / p.relative_to(backup)) == digest(p) for p in backup.rglob("*") if p.is_file())
    assert digest(app / "Contents/MacOS/ContinuousResumeQA") == setup["prior_native_binary_sha256"]
    listener = subprocess.run(["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    base = json.loads((EVIDENCE.parent / "2026-10-16-continuous-acceptance/live/setup.json").read_text())
    prior = Path(base["prior_runtime"])
    assert digest(prior / "request-count.json") == base["prior_counter_sha256"]
    assert digest(prior / "STOP") == base["prior_stop_sha256"]
    for name in ("request-count.json", "STOP", "live-events.jsonl", "native-recheck-events.jsonl", "native-disk-read.json", "authorization.json"):
        shutil.copy2(directory / name, EVIDENCE / name)
    (EVIDENCE / "capability-ledger.json").write_text(json.dumps(batches, ensure_ascii=False, indent=2) + "\n")
    parent23 = Path(setup["previous_real_runtime"])
    assert all(digest(parent23 / name) == sha for name, sha in setup["previous_real_runtime_sha256"].items())
    previous_events = [json.loads(line) for line in (EVIDENCE.parent / "2026-10-16-preview-real-recheck/live-events.jsonl").read_text().splitlines()]
    previous_ids = {r["request_id"] for r in previous_events if r["type"] == "request_entry"}
    assert len(previous_ids) == 3
    probe_ids = {identity for call in probes for identity in call["request_ids"]}
    current_store_ids = {identity for call in run_calls for identity in call["request_ids"]}
    assert len(probe_ids) == 8 and len(current_store_ids) == 15
    assert not (probe_ids & current_store_ids or previous_ids & current_store_ids or previous_ids & probe_ids)
    assert len(probe_ids | current_store_ids | previous_ids) == 26
    assert sum(call["transport_requests"] for call in probes + run_calls) + 3 == 26
    assert digest(EVIDENCE / "backend-after.json") == json.loads((EVIDENCE / "capture-aliases.json").read_text())["after-send.json"]["sha256"]
    assert len(events("semantic_output")) == 3 and not diagnosis["automatic_repair_triggered"]
    result = dict(outcome="REAL_CURRENT_PREVIEW_AND_NATIVE_SUBCHECK_PASSED", decision=240,
        repair_decision=239, batch_decision=237, baseline_commit=setup["baseline_commit"],
        starting_requests=23, new_requests=3, total_requests=26, limit=30, unused_allowance=4,
        new_request_numbers=[24,25,26], reported_usage_requests=3, unknown_usage_requests=0,
        reported_tokens=totals, new_startup_probes=0, retry_requests=0,
        same_batch_actual_probes_reused=True, new_model_outputs_frozen=False,
        current_store_requests=23, prior_archived_branch_requests=3, unique_global_request_ids=26,
        backend_run_status="completed", backend_error_code=None, candidate_count=1,
        candidate_version=2, published_offer_version=3, structured_preview_present=True,
        preview_points=4, preview_summary_present=True, fallback_scope_summary_only=False,
        source_quote_errors=0, automatic_repair_triggered=False, real_error_to_repair_path_verified=False,
        native_scope_updated=True, native_light_and_dark_inspected=True,
        native_window_size_points=[1040,820], native_message_posts=1,
        native_messages=10, native_runs=5, new_input_and_reply_durable=True,
        knowledge_saved=0, source_saved=0, review_state_count=0, save_clicked=False,
        learning_step_and_understanding_preserved=True, original_history_and_failed_partial_preserved=True,
        fresh_process_native_disk_checked=True, original_20_runtime_preserved=True,
        original_23_runtime_preserved=True, old_batch_30_and_stop_preserved=True,
        protected=protected, daily_files_byte_identical=5, daily_transient_files_absent=2,
        daily_database_content_unchanged=True, daily_file_check=daily,
        offline_diagnostic_default_store_import=True, diagnostic_import_now_isolated=True,
        project_user_difference_preserved=True, native_and_service_closed=True,
        previous_test_app_restored=True, daily_app_replaced=False,
        production_changed_this_round=False, later_gates_not_run=True,
        full_eight_step_acceptance=False, user_visual_acceptance=False,
        native_narrow_window_rechecked=False, voiceover_run=False,
        motion_revalidated=False, general_semantic_accuracy_verified=False)
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
