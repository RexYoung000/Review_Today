"""Verify scoped non-merge behavior and disclose the observed source-workspace change."""
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
    assert json.loads((directory / "request-count.json").read_text()) == dict(actual_requests=30, limit=30)
    assert (directory / "STOP").read_text().startswith("STOP: original EVAL-03 30/30 admitted")
    rows = [json.loads(x) for x in (directory / "live-events.jsonl").read_text().splitlines()]
    events = lambda kind: [r for r in rows if r["type"] == kind]
    entry, wires, responses, usages = [events(kind) for kind in ("request_entry", "sdk_wire_request", "sdk_wire_response", "reported_usage")]
    assert all(len(items) == 4 for items in (entry, wires, responses, usages))
    ids = {r["request_id"] for r in entry}
    assert len(ids) == 4 and {r["number"] for r in entry} == {27, 28, 29, 30}
    assert all({r["request_id"] for r in items} == ids for items in (wires, responses, usages))
    assert all(r["status"] == 200 for r in responses)
    assert not any(events(k) for k in ("sdk_guard_blocked", "budget_blocked", "transport_error"))
    starts = events("semantic_start")
    assert [r["schema"] for r in starts] == ["IntentDecision", "TeachingPreparation", "ConversationOutput", "ConversationOutput"]
    assert len(events("semantic_error")) == 1 and events("semantic_error")[0]["error_code"] == "RT.MODEL.SCHEMA"
    assert len(events("same_batch_verified_probe_reused")) == 1
    assert all(r["input"]["capture_candidates"] == [] for r in starts if r["schema"] == "ConversationOutput")
    posts = [r for r in events("native_http_post") if r["path"].endswith("/messages")]
    assert len(posts) == 1 and posts[0]["status"] == 200
    before = json.loads((EVIDENCE / "before-input.json").read_text())
    actual = json.loads((EVIDENCE / "backend-after.json").read_text())
    original = json.loads((ROOT / setup["source_checkpoint"]).read_text())
    run = list(actual["runs"].values())[-1]
    assert len(actual["runs"]) == 6 and run["status"] == "completed" and not run.get("error_code")
    assert before["runs"] == {key: actual["runs"][key] for key in before["runs"]}
    assert original["messages"] == actual["messages"][:len(original["messages"])]
    assert len(actual["messages"]) == len(original["messages"]) + 2 == 11
    question, reply = actual["messages"][-2:]
    assert question["role"] == "user" and reply["role"] == "coach"
    assert question["content"] == (EVIDENCE / "input.txt").read_text().strip()
    output = events("semantic_output")[-1]["output"]
    assert reply["content"] == output["message"] and output["capture_update"] is None
    assert run["intent"]["conversation_kind"] == "ordinary" and run["intent"]["answer_only"] is True
    assert run["intent"]["scope"] == "conversation" and run["intent"]["relation"] == "new_topic"
    assert run["intent"]["proposed_actions"] == [] and run.get("capture_scope_update") is None
    assert actual["capture_offers"] == before["capture_offers"] == original["capture_offers"]
    offer = next(iter(actual["capture_offers"].values()))
    assert offer["version"] == offer["preview_version"] == 3 and len(offer["preview_points"]) == 4
    assert offer["status"] == "offered" and not offer["knowledge_ids"]
    assert actual["active_task_id"] == original["active_task_id"] and actual["draft"] is None and actual["pending"] is None
    assert list(actual["tasks"]) == list(original["tasks"])
    task_id = actual["active_task_id"]
    old_task = before["tasks"][task_id]
    task = actual["tasks"][task_id]
    assert task["context"]["learning_plan"] == old_task["context"]["learning_plan"]
    # Do not describe this as all task context being preserved: the real run
    # clears its source working list. Preserve this observation, not a new fix.
    changes = json.loads((EVIDENCE / "task-diff.json").read_text())
    assert {tuple(r["path"][2:]) for r in changes} == {("updated_at",), ("context", "sources")}
    assert len(old_task["context"]["sources"]) == 1 and task["context"]["sources"] == []
    failures = [e for e in actual["events"] if e["run_id"] == run["run_id"] and e["node"] == "model_attempt_failed"]
    assert len(failures) == 1 and failures[0]["payload"]["step"] == "answer"
    errors = json.loads(failures[0]["detail_summary"])
    assert errors[0]["type"] == "json_invalid" and errors[0]["output_format"] == "non_json"
    started = [e for e in actual["events"] if e["run_id"] == run["run_id"] and e["node"] == "response.started"]
    assert len(started) == 1 and started[0]["payload"]["response"]["response_id"] == reply["message_id"]
    with sqlite3.connect(f"file:{directory / 'checkpoint.sqlite3'}?mode=ro", uri=True) as db:
        batches = [json.loads(row[0]) for row in db.execute("SELECT payload FROM agent_capability_batches")]
    assert len(batches) == 1 and batches[0]["status"] == "finished" and batches[0]["rounds"] == 1
    probes = batches[0]["calls"]
    run_calls = [c for r in actual["runs"].values() for c in r["model_calls"]]
    assert len(probes) == 8 and sum(c["transport_requests"] for c in run_calls) == 19
    assert [c["node"] for c in run["model_calls"]] == ["intent", "teaching_preparation", "answer", "answer"]
    assert [c["status"] for c in run["model_calls"]] == ["returned", "returned", "failed_or_cancelled", "returned"]
    assert all(c["usage_state"] == "reported" for c in run["model_calls"])
    assert {identity for c in run["model_calls"] for identity in c["request_ids"]} == ids
    by_id = {r["request_id"]: r["usage"] for r in usages}
    for c in run["model_calls"]:
        u = c["usage"][0]
        assert all(u[k] == by_id[u["request_id"]][k] for k in ("input_tokens", "output_tokens", "total_tokens"))
    tokens = {k: sum(r["usage"][k] for r in usages) for k in ("input_tokens", "output_tokens", "total_tokens")}
    archived_rows = [json.loads(x) for x in (EVIDENCE.parent / "2026-10-16-preview-real-recheck/live-events.jsonl").read_text().splitlines()]
    archived_ids = {r["request_id"] for r in archived_rows if r["type"] == "request_entry"}
    probe_ids = {i for c in probes for i in c["request_ids"]}
    current_ids = {i for c in run_calls for i in c["request_ids"]}
    assert len(archived_ids) == 3 and len(probe_ids) == 8 and len(current_ids) == 19
    assert not (archived_ids & current_ids or archived_ids & probe_ids or current_ids & probe_ids)
    assert len(archived_ids | current_ids | probe_ids) == 30
    native = json.loads((directory / "native-disk-read.json").read_text())
    assert native["knowledge_count"] == native["source_count"] == native["fsrs_count"] == 0 and not native["cards"]
    assert len(native["messages"]) == 12 and len(native["runs"]) == 6
    assert {r["id"]: r["status"] for r in native["runs"]} == {r["run_id"]: r["status"] for r in actual["runs"].values()}
    messages = {m["id"]: m for m in native["messages"]}
    for m in actual["messages"]:
        assert messages[m["message_id"]]["text"] == m["content"]
        assert messages[m["message_id"]]["run_id"] == m["run_id"]
        assert messages[m["message_id"]]["response_state"] == "complete"
    assert messages[question["message_id"]]["client_id"] == question["message_id"]
    assert messages[question["message_id"]]["delivery"] == "accepted"
    failed = [r["active_response"] for r in before["runs"].values() if r.get("active_response") and r["status"] == "retryable_failed"]
    assert len(failed) == 1 and messages[failed[0]["response_id"]]["response_state"] == "failed"
    assert messages[failed[0]["response_id"]]["text"] == failed[0]["text"]
    snapshots = [json.loads(x) for x in (directory / "native-recheck-events.jsonl").read_text().splitlines()]
    assert not any(r["phase"] == "durable_receipt" for r in snapshots)
    projected = json.loads(snapshots[-1]["capture_offers_json"])
    assert projected == json.loads(snapshots[0]["capture_offers_json"])
    assert len(projected) == 1 and projected[0]["version"] == 3
    assert projected[0]["preview_points"] == offer["preview_points"] and projected[0]["preview_summary"] == offer["preview_summary"]
    assert native["sessions"] == [dict(cursor=snapshots[-1]["cursor"], id=setup["session_id"])]
    protected = {}
    for group in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256", "protected_archive_sha256"):
        assert all(digest(ROOT / name) == sha for name, sha in setup[group].items()), group
        protected[group] = len(setup[group])
    for item in setup["daily_files_before"]:
        path = Path(item["path"])
        assert path.exists() == item["exists"]
        if path.exists():
            assert digest(path) == item["sha256"]
    for parent in setup["parent_runtimes"].values():
        assert all(digest(Path(parent["directory"]) / name) == sha for name, sha in parent["sha256"].items())
    base = json.loads((EVIDENCE.parent / "2026-10-16-continuous-acceptance/live/setup.json").read_text())
    prior = Path(base["prior_runtime"])
    assert digest(prior / "request-count.json") == base["prior_counter_sha256"] and digest(prior / "STOP") == base["prior_stop_sha256"]
    assert hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest() == setup["project_diff_sha256"]
    app, backup = Path(setup["native_app"]), Path(setup["prior_native_app_backup"])
    assert {str(p.relative_to(app)): digest(p) for p in app.rglob("*") if p.is_file()} == {str(p.relative_to(backup)): digest(p) for p in backup.rglob("*") if p.is_file()}
    assert digest(app / "Contents/MacOS/ContinuousResumeQA") == setup["prior_native_binary_sha256"]
    assert not subprocess.run(["pgrep", "-fl", "/ContinuousResumeQA.app/Contents/MacOS/"], capture_output=True, text=True).stdout.strip()
    listener = subprocess.run(["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    for name in ("request-count.json", "STOP", "live-events.jsonl", "native-recheck-events.jsonl", "native-disk-read.json", "authorization.json"):
        shutil.copy2(directory / name, EVIDENCE / name)
    (EVIDENCE / "capability-ledger.json").write_text(json.dumps(batches, ensure_ascii=False, indent=2) + "\n")
    result = dict(outcome="SCOPED_SEPARATE_TOPIC_PASS_WITH_SOURCE_WORKSPACE_OBSERVATION", decision=241,
        parent_decision=240, batch_decision=237, baseline_commit=setup["baseline_commit"],
        starting_requests=26, new_requests=4, total_requests=30, limit=30, unused_allowance=0,
        new_request_numbers=[27,28,29,30], reported_usage_requests=4, unknown_usage_requests=0,
        reported_tokens=tokens, new_startup_probes=0, schema_repair_requests=1,
        initial_error="json_invalid/non_json", generic_format_repair_succeeded=True,
        update_preview_grounding_repair_verified=False, same_batch_actual_probes_reused=True,
        model_outputs_substituted=False, unique_global_request_ids=30, backend_run_status="completed",
        original_offer_exactly_preserved=True, original_preview_version=3, original_preview_points=4,
        original_source_fragments_and_draft_preserved=True, new_capture_candidates=0,
        active_task_and_learning_plan_preserved=True, new_goal_created=False,
        task_source_workspace_cleared=True, all_task_context_preserved=False,
        return_to_rag_source_reuse_verified=False, source_workspace_fix_implemented=False,
        native_scoped_behavior_checked=True, native_message_posts=1, native_messages=12, native_runs=6,
        knowledge_saved=0, source_saved=0, review_state_count=0, save_clicked=False,
        original_history_and_failed_partial_preserved=True, fresh_process_disk_read=True,
        protected=protected, daily_existing_files_identical=5, daily_absent_files_still_absent=2,
        parent_20_23_26_runtimes_preserved=True, old_batch_stop_preserved=True,
        user_project_difference_preserved=True, native_and_service_closed=True,
        test_app_restored=True, daily_app_replaced=False, production_changed=False,
        full_eight_step_acceptance=False, later_save_and_query_gates_run=False,
        general_semantic_accuracy_verified=False, user_visual_acceptance=False)
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
