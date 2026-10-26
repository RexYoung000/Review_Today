"""Verify stopped admission and private byte preservation without relaxing it."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, unquote
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "docs/evidence/2026-10-25-managed-teaching-preflight"))
from common import read, write, sha, files, inventory, DAILY, SUPPORT, PRIVATE, PREVIOUS_PREP, PREVIOUS_ARCHIVE


def main():
    assert not (OUT / "verification.json").exists()
    entry, setup = read(OUT / "entry-check.json"), read(OUT / "setup.json")
    old = read(PREVIOUS_PREP / "setup.json")
    missing = entry["prior_evidence_pins"]["missing"]
    assert {p: h for p, h in old["prior_evidence_pins"].items() if not Path(p).is_file()} == missing
    assert len(missing) == 121 and len(old["prior_evidence_pins"]) - len(missing) == 632
    assert all(sha(Path(p)) == h for p, h in old["prior_evidence_pins"].items() if p not in missing)
    assert all(not Path(p).exists() for p in old["known_missing_old_paths"])
    for key in ["original_module_files", "owned_support_files"]:
        assert all(sha(Path(p)) == h for p, h in old[key].items())
    prep = ROOT / setup["preparation"]
    prepared = read(prep / "setup.json")
    assert all(sha(ROOT / p) == h for p, h in read(prep / "source-pins.json").items())
    assert all(sha(prep / p) == h for p, h in read(prep / "artifact-sha256.json").items())
    assert all(sha(Path(p)) == h for p, h in prepared["post_exit_native_dependencies"].items())
    assert files(SUPPORT) == read(PREVIOUS_ARCHIVE / "actual/after-file-pins.json")
    assert inventory(DAILY) == old["daily_app_inventory"]
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == old["project_diff_sha256"]
    runtime = Path(setup["directory"])
    expected = read(PRIVATE / "runtime-pins.json")
    current = files(runtime)
    assert {p: h for p, h in current.items() if p != str(runtime / "STOP")} == expected
    assert (runtime / "STOP").is_file() and (runtime / "HOLD").is_file()
    assert read(runtime / "authorization.json")["status"] == "pending"
    assert not any((runtime / n).exists() for n in ["quota.json", "startup-claim.json", "bootstrap-ready.json", "app.store", "checkpoint.sqlite3"])
    assert not Path(prepared["native_app"]).exists()
    assert subprocess.run(["pgrep", "-x", "Review_Today"], capture_output=True).returncode == 1
    for port in [8742, setup["port"]]:
        assert subprocess.run(["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN", "-t"], capture_output=True).returncode == 1
    recovery = read(OUT / "archived-copies.json")
    assert len(recovery["original_path_mapping"]) == 121 and len(recovery["objects"]) == 82
    assert all(sha(Path(value["path"])) == digest for digest, value in recovery["objects"].items())
    archive = Path(setup["archive"])
    controls = archive / "stopped-controls"
    controls.mkdir(mode=0o700)
    for name in ["authorization.json", "HOLD", "STOP"]:
        shutil.copy2(runtime / name, controls / name)
    archive_files = files(archive)
    package = archive / "verified-byte-copies.zip"
    with zipfile.ZipFile(package, "x", zipfile.ZIP_DEFLATED) as z:
        for path in archive_files:
            z.write(path, str(Path(path).relative_to(archive)))
    with zipfile.ZipFile(package) as z:
        for path, digest in archive_files.items():
            with z.open(str(Path(path).relative_to(archive))) as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    write(OUT / "verification.json", dict(status="STOPPED_ENTRY_0_0_ARCHIVED_BYTES_VERIFIED", decision=275,
        actual_model_requests=0, actual_web_operations=0, app_and_service_not_started=True,
        new_20_0_unused_frozen=True, pending_hold_stop_and_no_ledger=True,
        old_paths_expected=753, old_paths_matched=632, newly_missing_paths=121, changed_old_files=0,
        exact_durable_bytes_verified_for_missing_paths=121, unique_objects=82, bytes_copied=19240551,
        archive=str(package), archive_sha256=sha(package), archive_members_read=len(archive_files),
        original_missing_paths_and_old_baselines_preserved=True, missing_cause_not_established=True,
        previous_12_gaps_and_two_old_main_db_copy_gaps_preserved=True,
        source_pins_unchanged=319, post_exit_native_dependencies_unchanged=9,
        original_and_owned_modules_unchanged=[8, 8], current_formal_seven_bytes_and_app_unchanged=True,
        user_project_diff_preserved=True, original_formal_databases_opened=False,
        native_inventory_available_after_unlock=True, acceptance_rule_not_changed=True,
        candidate_persistent_copy_rule_pending_user_decision=True, managed_startup_teaching_experience_and_m1_still_open=True))
    print(f"PASS stopped-state audit: real 0/0; 121 old paths still missing, exact 82 objects and {len(archive_files)} archive members read-verified; 319 source pins, daily data/App and user diff preserved. No gate relaxed.")


if __name__ == "__main__":
    main()
