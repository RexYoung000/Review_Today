"""Byte-copy closed daily data first; SQLite touches only new private copies."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
import zipfile
from common import *


def main():
    assert not PRIVATE.exists() and not ARCHIVE.exists() and not (OUT / "setup.json").exists()
    unchanged()
    previous = read(PREVIOUS / "setup.json")
    prior_candidate = read(ROOT / "docs/evidence/2026-10-23-daily-update-preflight/candidate.json")
    assert inventory(DAILY) == prior_candidate["inventory"]
    old_pins = read(ROOT / "docs/evidence/2026-10-23-daily-update-preflight/source-pins.json")
    swift = {n: h for n, h in old_pins.items() if n.startswith("Review_Today/") and n.endswith(".swift")}
    assert all(sha(ROOT / n) == h for n, h in swift.items())
    backend = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / "agent-service/agent_service").rglob("*.py")}
    delta = sorted(n for n, h in backend.items() if old_pins.get(n) != h)
    fixed_delta = ["answer_style", "conversation", "conversation_prompts", "learning_progress",
                   "response_projection", "schemas", "structured_output", "teaching_check"]
    assert delta == ["agent-service/agent_service/" + n + ".py" for n in fixed_delta]
    compiled_path = str(ROOT / "Review_Today/AgentServiceMonitor.swift")
    assert compiled_path in subprocess.check_output(["strings", "-a", str(DAILY / "Contents/MacOS/Review_Today.debug.dylib")], text=True)
    helpers = backup_helpers()
    signature = helpers.signature(DAILY)
    assert signature == prior_candidate["signature"]
    archived_app = Path(prior_candidate["zip"])
    assert sha(archived_app) == prior_candidate["zip_sha256"]
    with zipfile.ZipFile(archived_app) as z:
        matched = 0
        for item in z.infolist():
            prefix = "Review_Today.app/"
            if item.is_dir() or not item.filename.startswith(prefix):
                continue
            original = DAILY / item.filename[len(prefix):]
            assert original.is_file() and hashlib.sha256(z.read(item)).hexdigest() == sha(original)
            matched += 1
    assert matched == sum(row["type"] == "file" for row in inventory(DAILY).values())
    PRIVATE.mkdir(mode=0o700)
    ARCHIVE.mkdir(parents=True, mode=0o700)
    os.chmod(ARCHIVE, 0o700)
    source_pins = dict(previous["protected_fingerprints"])
    prior_evidence = dict(previous["frozen_existing_files"])
    prior_evidence.update(files(ROOT / "docs/evidence/2026-10-24-teaching-scope-fullflow-real"))
    old_archive = Path(read(ROOT / "docs/evidence/2026-10-24-teaching-scope-fullflow-real/archive.json")["runtime"]["archive"]).parent
    prior_evidence.update(files(old_archive))
    old_runtime = Path(previous["directory"])
    for name in ["authorization.json", "quota.json", "STOP"]:
        prior_evidence[str(old_runtime / name)] = sha(old_runtime / name)
    state = dict(date="2026-10-25", prepared_at=datetime.now(timezone.utc).isoformat(),
        baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        daily_files=files(SUPPORT), daily_app_inventory=inventory(DAILY),
        source_config_pins=source_pins, prior_evidence_pins=prior_evidence,
        known_missing_old_paths=previous["known_missing_old_paths"],
        original_module_files=previous["original_module_files"], owned_support_files=previous["owned_support_files"],
        project_diff_sha256=previous["project_diff_sha256"])
    write(OUT / "setup.json", state)
    raw = ARCHIVE / "raw-active-support"
    raw.mkdir(mode=0o700)
    for name, digest in state["daily_files"].items():
        destination = raw / Path(name).relative_to(SUPPORT)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(name, destination)
        destination.chmod(0o600)
        assert sha(destination) == digest
    def audit(event, args):
        if event == "socket.connect":
            raise AssertionError("Preparation must remain offline")
        if event == "sqlite3.connect":
            from urllib.parse import urlsplit, unquote
            value = str(args[0])
            path = Path(unquote(urlsplit(value).path) if value.startswith("file:") else value).resolve()
            assert path.is_relative_to(ARCHIVE), "Original formal databases must not be opened"
    sys.addaudithook(audit)
    inspection = ARCHIVE / "inspection-copy"
    shutil.copytree(raw, inspection)
    consistent = ARCHIVE / "consistent-databases"
    consistent.mkdir(mode=0o700)
    summaries = {}
    for relative, name in DBS.items():
        source = inspection / relative
        before = helpers.summary(source)
        destination = consistent / name
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                dst.execute("pragma journal_mode=delete")
        destination.chmod(0o600)
        assert helpers.summary(destination) == before
        summaries[relative] = before
    shutil.rmtree(inspection)
    assert all(sha(raw / Path(name).relative_to(SUPPORT)) == digest
               for name, digest in state["daily_files"].items())
    write(PRIVATE / "before-tables.json", summaries)
    configs = {}
    for path in [ROOT / "agent-service/.env", *sorted((ROOT / "agent-service/providers").glob("*/.env"))]:
        if path.is_file():
            destination = ARCHIVE / "private-config" / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, destination)
            destination.chmod(0o600)
            assert sha(destination) == sha(path)
            configs[str(path.relative_to(ROOT))] = sha(path)
    backup_members = {str(p.relative_to(ARCHIVE)): sha(p) for p in ARCHIVE.rglob("*") if p.is_file()}
    backup_zip = ARCHIVE / "prepared-backup.zip"
    with zipfile.ZipFile(backup_zip, "x", zipfile.ZIP_DEFLATED) as z:
        for name in backup_members:
            z.write(ARCHIVE / name, name)
    with zipfile.ZipFile(backup_zip) as z:
        assert set(z.namelist()) == set(backup_members)
        assert all(hashlib.sha256(z.read(n)).hexdigest() == digest for n, digest in backup_members.items())
    write(ARCHIVE / "prepared-backup-manifest.json", dict(archive=str(backup_zip), sha256=sha(backup_zip), members=backup_members))
    write(OUT / "source-delta.json", dict(backend_delta=delta, changed_swift_files=[],
        daily_app_matches_previous_signed_candidate=True, daily_app_replacement_needed=False,
        service_sources_embedded_in_app=False, native_default_source_file_present_in_installed_binary=True,
        native_service_launch_source="Review_Today/AgentServiceMonitor.swift:329",
        existing_app_archive=str(archived_app), existing_app_archive_sha256=sha(archived_app),
        existing_archive_members_read_and_current_app_matched=matched, current_signature=signature))
    plan = dict(status="PREPARED_PENDING_NEW_8_0", decision=272, date="2026-10-25", batch_id=str(uuid.uuid4()),
        scope="current workspace service only; one startup probe batch against daily service stores; daily App remains closed; no messages/save/cleanup or App replacement",
        actual_model_request_limit=8, provider_web_operation_limit=0,
        startup_command="PYTHONDONTWRITEBYTECODE=1 agent-service/.venv/bin/python -B docs/evidence/2026-10-25-daily-service-preflight/start_service.py",
        daily_app=str(DAILY), database_path=str(SUPPORT / "agent-harness.sqlite3"),
        source_commit="b0cd32c", previous_functional_evidence_commit="81928af",
        steps=["Recheck closed daily App/service, seven bytes, source/config/old evidence pins and backup",
               "After explicit new 8/0 approval, start this guarded service once on port 8742; pin the current workspace repair modules",
               "Observe one new capability batch and real smart/deep streaming readiness; never manually rerun",
               "Close the owned service normally, freeze the ledger and inspect fresh copies; original rows remain with only the new capability batch and documented startup fields allowed"],
        stop_conditions=["First probe failure or extra request needed", "Either cap reached: no new transports", "Source, data, ownership or protection mismatch"],
        no_app_replacement_or_launch=True, no_new_messages_or_cards=True, no_test_data_promoted=True,
        formal_database_writes_after_approval="Only existing service startup behavior, including its new readiness batch; no automatic data restore",
        prior_271_remaining_10_16_frozen=True, all_old_allowances_frozen=True,
        app_managed_child_startup_and_rex_experience_not_covered=True,
        rationale="All eight repair files are Python sources; the signed daily App and Swift sources are unchanged. A service-only check avoids repackaging or repeating the already passed native functional chain.")
    write(OUT / "plan.json", plan)
    activation = PRIVATE / "activation"
    activation.mkdir(mode=0o700)
    write(activation / "authorization.json", dict(status="pending", batch_id=plan["batch_id"],
        actual_model_request_limit=8, provider_web_operation_limit=0, daily_app=str(DAILY),
        database_path=plan["database_path"], scope=plan["scope"], plan_sha256=sha(OUT / "plan.json")))
    (activation / "HOLD").write_text("New 8/0 service-only startup requires explicit approval. All previous allowances stay frozen.\n")
    write(PRIVATE / "backup-pins.json", files(ARCHIVE))
    native = summaries["Data/ReviewToday.store"]["tables"]
    service = summaries["agent-harness.sqlite3"]["tables"]
    write(OUT / "backup.json", dict(status="PREPARED_SERVICE_ONLY_NOT_STARTED", archive=str(ARCHIVE),
        raw_formal_files=7, consistent_database_copies=3, private_config_files=len(configs),
        archive_sha256=sha(backup_zip), archive_actual_members_read=len(backup_members),
        formal_databases_opened=False, original_formal_files_unchanged=True, existing_app_package_reused=True,
        native_counts={t: native[t]["count"] for t in ["ZAGENTSESSION", "ZAGENTMESSAGE", "ZKNOWLEDGE", "ZFSRSSTATE", "ZLEARNINGTASK", "ZAGENTRUN", "ZSOURCE"]},
        service_counts={t: service[t]["count"] for t in ["agent_sessions_v2", "harness_tasks", "agent_capability_batches"]},
        original_and_consistent_copy_logical_rows_match=True, cross_database_atomic_snapshot=False,
        model_requests=0, web_operations=0, app_replaced=False, app_started=False))
    unchanged()
    print("Prepared service-only delta, seven original byte copies, three consistent DB copies, five private configs and held new 8/0 allowance; real 0/0.")


if __name__ == "__main__":
    main()
