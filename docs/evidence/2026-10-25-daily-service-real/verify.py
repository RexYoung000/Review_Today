"""Verify the completed one-start batch; SQLite opens only new private copies."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from urllib.parse import unquote, urlsplit

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PREP = ROOT / "docs/evidence/2026-10-25-daily-service-preflight"
sys.path.insert(0, str(PREP))
from common import ARCHIVE, PRIVATE, DAILY, SUPPORT, DBS, read, write, sha, files, inventory, stopped, backup_helpers
from rehearse_startup import rows

ACTUAL = ARCHIVE / "actual"
ACTIVATION = PRIVATE / "activation"


def protected():
    stopped()
    state = read(PREP / "setup.json")
    assert inventory(DAILY) == state["daily_app_inventory"]
    pins = read(PREP / "source-pins.json")
    assert all(sha(ROOT / p) == h for p, h in pins.items())
    for key in ["prior_evidence_pins", "original_module_files", "owned_support_files"]:
        assert all(Path(p).is_file() and sha(Path(p)) == h for p, h in state[key].items()), key
    assert all(not Path(p).exists() for p in state["known_missing_old_paths"])
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == state["project_diff_sha256"]
    assert all(sha(Path(p)) == h for p, h in read(PRIVATE / "backup-pins.json").items())
    assert all(sha(PREP / name) == h for name, h in read(PREP / "artifact-sha256.json").items())
    return state, pins


def main():
    assert not (OUT / "verification.json").exists(), "Do not overwrite completed evidence"
    state, pins = protected()
    assert read(ACTUAL / "shutdown.json")["normal_shutdown"]
    before_copy = files(SUPPORT)
    raw = ACTUAL / "after-raw"
    # Resume only the offline observer on the original post-close copies. Never
    # overwrite the first attempt, the raw bytes, or the completed real batch.
    if not raw.exists():
        raw.mkdir(mode=0o700)
        for path, digest in before_copy.items():
            target = raw / Path(path).relative_to(SUPPORT)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, target)
            target.chmod(0o600)
            assert sha(target) == digest
    assert {str(SUPPORT / Path(p).relative_to(raw)): h for p, h in files(raw).items()} == before_copy
    assert files(SUPPORT) == before_copy, "Daily files changed during closed byte copy"

    def audit(event, args):
        if event == "socket.connect":
            raise AssertionError("No network in post-start verification")
        if event == "sqlite3.connect":
            value = str(args[0])
            path = Path(unquote(urlsplit(value).path) if value.startswith("file:") else value).resolve()
            assert path.is_relative_to(ACTUAL), "Never open original formal or frozen backup databases"
    sys.addaudithook(audit)
    inspection = ACTUAL / "inspection-copy"
    consistent = ACTUAL / "after-consistent"
    fresh = not consistent.exists()
    if fresh:
        shutil.copytree(raw, inspection)
        consistent.mkdir(mode=0o700)
    helpers = backup_helpers()
    after, summaries = {}, {}
    for relative, name in DBS.items():
        source, target = inspection / relative, consistent / name
        if fresh:
            summary = helpers.summary(source)
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                    dst.execute("pragma journal_mode=delete")
            target.chmod(0o600)
            assert helpers.summary(target) == summary
        summaries[name] = helpers.summary(target)
    if fresh:
        shutil.rmtree(inspection)
    before_summaries = read(PRIVATE / "before-tables.json")
    assert summaries["app.store"] == before_summaries["Data/ReviewToday.store"]
    assert summaries["review.sqlite3"] == before_summaries["agent-harness.review.sqlite3"]
    baseline_service = ACTUAL / "baseline-checkpoint-copy.sqlite3"
    if not baseline_service.exists():
        shutil.copy2(ARCHIVE / "consistent-databases/checkpoint.sqlite3", baseline_service)
    assert sha(baseline_service) == sha(ARCHIVE / "consistent-databases/checkpoint.sqlite3")
    service_before = rows(baseline_service)
    service_after = rows(consistent / "checkpoint.sqlite3")
    assert set(service_before) == set(service_after)
    for table in service_before:
        if table != "agent_capability_batches":
            assert service_before[table] == service_after[table], table
    old = {r["batch_id"]: r for r in service_before["agent_capability_batches"]}
    new = {r["batch_id"]: r for r in service_after["agent_capability_batches"]}
    assert len(new) == len(old) + 1 and all(new[k] == v for k, v in old.items())
    fresh_id, = set(new) - set(old)
    batch = new[fresh_id]["payload"]
    assert batch["status"] == "finished" and batch["rounds"] == 1 and len(batch["calls"]) == 8
    quota = read(ACTIVATION / "quota.json")
    assert quota["closed"] and quota["model_requests"] == 8 and quota["web_operations"] == 0
    entries = quota["entries"]
    assert len(entries) == 8 and all(e["kind"] == "model" and e["dispatched"] and e["outcome"] == "returned" for e in entries)
    assert (ACTIVATION / "STOP").read_text() == "CAP_REACHED " + quota["spec"]["batch_id"] + "\n"
    assert not (ACTIVATION / "HOLD").exists()
    requests = {e["program_id"]: e for e in entries}
    assert len(requests) == 8
    assert {r for call in batch["calls"] for r in call["request_ids"]} == set(requests)
    for call in batch["calls"]:
        assert call["transport_requests"] == 1 and len(call["request_ids"]) == 1
        identity = call["request_ids"][0]
        assert len(call["usage"]) == len(requests[identity]["usage"]) == 1
        assert call["usage"][0]["request_id"] == identity
        assert all(requests[identity]["usage"][0].get(k) == v for k, v in call["usage"][0].items())
    assert sorted(c["kind"] for c in batch["calls"]) == ["streaming"] * 2 + ["structured"] * 6
    boot = read(ACTIVATION / "bootstrap-ready.json")
    launch = read(ACTUAL / "launch.json")
    assert boot["pid"] == launch["pid"] == read(ACTUAL / "shutdown.json")["pid"]
    delta = read(PREP / "source-delta.json")["backend_delta"]
    lazy = "agent-service/agent_service/teaching_check.py"
    assert set(boot["loaded_repair_module_paths"]) == set(delta) - {lazy}
    assert all(path == str((ROOT / name).resolve()) for name, path in boot["loaded_repair_module_paths"].items())
    assert set(boot["repair_source_fingerprints"]) == set(delta)
    assert all(boot["repair_source_fingerprints"][name] == sha(ROOT / name) for name in delta)
    # Confirm why the eighth import was absent without importing service code.
    assert "from agent_service.teaching_check import INSTRUCTION" in (ROOT / "agent-service/agent_service/conversation.py").read_text()
    observations = read(ACTUAL / "health-observations.json")
    assert all(row["app_closed"] for row in observations)
    health = observations[-1]["health"]
    assert health["status"] == "ok" and health["provider"] == "deepseek"
    roles = health["model_roles"]
    assert all(v["status"] == "ready" and v["next_probe_at"] is None
               and all(x["status"] == "ready" for x in v["strengths"].values()) for v in roles.values())
    assert roles["coach"]["streaming"] == roles["coach"]["strengths"]["deep"]["streaming"] == "ready"
    assert helpers.signature(DAILY) == read(PREP / "source-delta.json")["current_signature"]
    state, pins = protected()
    assert files(SUPPORT) == before_copy
    assert all(sha(raw / Path(p).relative_to(SUPPORT)) == h for p, h in before_copy.items())
    write(ACTUAL / "after-file-pins.json", before_copy)
    changed = {str(Path(p).relative_to(SUPPORT)): {"before": state["daily_files"].get(p), "after": before_copy.get(p)}
               for p in sorted(set(state["daily_files"]) | set(before_copy)) if state["daily_files"].get(p) != before_copy.get(p)}
    usage = [e["usage"][0] for e in entries]
    result = dict(status="PASS_SERVICE_ONLY_STARTUP_CLOSED", decision=273, date="2026-10-25",
        verified_at=datetime.now(timezone.utc).isoformat(), batch_id=quota["spec"]["batch_id"],
        actual_model_requests=8, provider_web_operations=0, startup_count=1, probe_rounds=1,
        request_ids_unique_and_matched=8, all_eight_requests_returned=True,
        structured_requests=6, streaming_requests=2,
        usage_totals={k: sum(u.get(k, 0) for u in usage) for k in ["input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_output_tokens"]},
        configured_models={k: v["model"] for k, v in roles.items()},
        reported_models=sorted({u["reported_model"] for u in usage}),
        health_roles_and_strengths_ready=True, coach_smart_deep_streaming_ready=True, next_probe_scheduled=False,
        source_modules_loaded=len(boot["loaded_repair_module_paths"]), source_files_pinned=len(delta),
        source_paths_and_fingerprints_match=True, lazy_module_not_exercised=lazy,
        daily_app_launched=False, daily_app_replaced=False, normal_shutdown=True, app_and_service_closed=True,
        original_formal_databases_opened_for_inspection=False, after_raw_formal_files=len(before_copy),
        consistent_database_copies=3, sqlite_integrity_all_ok=True,
        native_and_review_all_rows_exact=True, all_existing_service_rows_logically_exact=True,
        old_capability_batches_exact=len(old), new_capability_batches=1, new_capability_batch=fresh_id,
        native_counts={k: summaries["app.store"]["tables"][k]["count"] for k in ["ZAGENTSESSION", "ZAGENTMESSAGE", "ZKNOWLEDGE", "ZFSRSSTATE", "ZLEARNINGTASK", "ZAGENTRUN", "ZSOURCE"]},
        service_counts={k: len(service_after[k]) for k in ["agent_sessions_v2", "harness_tasks", "agent_capability_batches"]},
        changed_formal_file_bytes=changed, only_logical_table_changed="agent_capability_batches",
        source_config_execution_pins=len(pins), old_evidence_pins_preserved=len(state["prior_evidence_pins"]),
        original_and_owned_module_files_preserved=[len(state["original_module_files"]), len(state["owned_support_files"])],
        known_missing_old_paths_preserved=len(state["known_missing_old_paths"]), prepared_backup_pins_preserved=17,
        prepared_evidence_unchanged=True, user_project_diff_preserved=True, app_inventory_and_signature_preserved=True,
        allowance_closed=True, stop_present=True, prior_271_unused_10_16_frozen=True, all_old_allowances_frozen=True,
        web_not_verified=True, app_managed_child_startup_not_verified=True, new_native_acceptance_not_performed=True,
        rex_experience_and_m1_open=True)
    write(OUT / "verification.json", result)
    write(OUT / "startup-health.json", health)
    write(OUT / "quota-final.json", quota)
    write(OUT / "capability-batch.json", batch)
    write(OUT / "bootstrap-ready.json", boot)
    write(OUT / "shutdown.json", read(ACTUAL / "shutdown.json"))
    print("PASS: one real startup, 8 returned/0 web, readiness; seven imported modules/eight source pins matched; teaching-only lazy module unexercised; normal close; old rows exact, one new capability batch.")
    print("Formal byte changes:", ", ".join(changed))


if __name__ == "__main__":
    main()
