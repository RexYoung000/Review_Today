"""Freeze offline results and held runtime; no App, server or provider startup."""
import ast
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import zipfile
from common import *


def main():
    assert not (OUT / "verification.json").exists()
    old, source_pins = unchanged()
    state = read(OUT / "setup.json")
    runtime = Path(state["directory"])
    assert read(OUT / "checks.json")["status"] == "PASS"
    assert read(runtime / "authorization.json")["status"] == "pending" and (runtime / "HOLD").exists()
    assert not Path(state["native_app"]).exists()
    assert not any((runtime / name).exists() for name in ["quota.json", "app.store", "checkpoint.sqlite3", "review.sqlite3", "startup-claim.json", "bootstrap-ready.json", "live-events.jsonl"])
    assert files(runtime) == read(PRIVATE / "runtime-pins.json")
    # Current component reader and its eight modules already have a read-verified
    # durable archive from 271. Pin their current paths as well for post-exit use.
    earlier = read(ROOT / "docs/evidence/2026-10-24-teaching-scope-fullflow-preflight/setup.json")
    reader = Path(earlier["directory"]) / "native-disk-reader"
    dependencies = {str(reader): sha(reader), **earlier["owned_support_files"]}
    assert all(sha(Path(p)) == h for p, h in dependencies.items())
    state["post_exit_native_reader"] = str(reader)
    state["post_exit_native_dependencies"] = dependencies
    write(OUT / "setup.json", state)
    def audit(event, args):
        if event in {"socket.connect", "sqlite3.connect"}:
            raise AssertionError("Static environment check must stay offline without databases")
    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service import config
    assert config.PROVIDER == "deepseek" and config.openai_key()
    write(OUT / "environment.json", dict(platform="macOS", version=platform.mac_ver()[0],
        build=subprocess.check_output(["sw_vers", "-buildVersion"], text=True).strip(), architecture=platform.machine(),
        python_version=platform.python_version(), python_executable=sys.executable,
        provider=config.PROVIDER, configured_models=dict(router=config.ROUTER_MODEL, coach=config.COACH_MODEL, risk=config.RISK_MODEL),
        provider_key_configured=bool(config.openai_key()), config_changed=False,
        credentials_or_app_child_permissions_not_tested=True, native_ui_status="MAC_LOCKED",
        native_ui_action_required="User unlocks Mac manually; recheck CUA before launching once",
        daily_data_matches_closed_273=True, formal_databases_opened=False, model_requests=0, web_operations=0))
    packages = [Path(state["native_zip"]), ARCHIVE / "initial-preparation-attempt/ManagedTeachingQA.zip",
                ARCHIVE / "before-cua-launch-adaptation/ManagedTeachingQA.zip", ARCHIVE / "failed-cua-signature.zip"]
    archive_checks = []
    for path in packages:
        with zipfile.ZipFile(path) as z:
            members = {}
            for name in z.namelist():
                with z.open(name) as stream:
                    members[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        archive_checks.append(dict(path=str(path), sha256=sha(path), members=members, every_member_stream_read=True))
    with zipfile.ZipFile(Path(state["native_zip"])) as z:
        info = plistlib.loads(z.read("ManagedTeachingQA.app/Contents/Info.plist"))
        assert info["CFBundleIdentifier"] == state["native_bundle_id"] and info["CFBundleExecutable"] == "ManagedTeachingEntry"
        assert hashlib.sha256(z.read("ManagedTeachingQA.app/Contents/MacOS/ManagedTeachingEntry")).hexdigest() == state["fixed_environment_wrapper_sha256"]
    for path in OUT.glob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
    pins = dict(state["protected_fingerprints"])
    for path in list(OUT.glob("*.py")) + [OUT / n for n in ["plan.json", "setup.json", "ui-channel.json", "environment.json"]]:
        pins[str(path.relative_to(ROOT))] = sha(path)
    write(OUT / "source-pins.json", pins)
    spec = read(runtime / "authorization.json")
    spec.update(plan_sha256=sha(OUT / "plan.json"), source_pins_sha256=sha(OUT / "source-pins.json"))
    write(runtime / "authorization.json", spec)
    write(PRIVATE / "runtime-pins.json", files(runtime))
    raw_pins = files(runtime)
    owned_files = {str(p): sha(p) for p in runtime.rglob("*") if p.is_file() and not p.is_symlink()}
    runtime_zip = ARCHIVE / "prepared-runtime.zip"
    with zipfile.ZipFile(runtime_zip, "x", zipfile.ZIP_DEFLATED) as z:
        for path in owned_files:
            z.write(path, str(Path(path).relative_to(runtime)))
    with zipfile.ZipFile(runtime_zip) as z:
        for path, digest in owned_files.items():
            with z.open(str(Path(path).relative_to(runtime))) as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    write(OUT / "archives.json", dict(packages=archive_checks, runtime_archive=str(runtime_zip), runtime_sha256=sha(runtime_zip),
        runtime_members=len(owned_files), runtime_files=raw_pins, owned_archive_files=owned_files,
        dependency_links={str(p.relative_to(runtime)): os.readlink(p) for p in (runtime / "owned-project/agent-service/.venv").rglob("*") if p.is_symlink()},
        all_members_stream_read=True, failed_preparation_and_signing_candidates_preserved=True,
        initial_script_reconstruction_explicit=True))
    unchanged()
    assert files(runtime) == raw_pins
    write(OUT / "verification.json", dict(status="OFFLINE_READY_PENDING_20_0_AND_MANUAL_MAC_UNLOCK", decision=274,
        verified_at=datetime.now(timezone.utc).isoformat(), actual_model_requests=0, actual_web_operations=0,
        original_app_and_service_stopped=True, no_daily_replacement=True, current_daily_seven_bytes_preserved=True,
        original_app_inventory_and_user_project_diff_preserved=True, original_formal_databases_opened=False,
        previous_307_source_pins_preserved=True, current_source_config_execution_pins=len(pins),
        old_753_evidence_pins_preserved=True, prior_273_records_preserved=len(state["prior_records"]),
        post_exit_native_dependencies_pinned=len(dependencies), native_package_code_text_sections_unchanged=3,
        exact_full_app_ui_and_monitor=True, launch_wrapper_and_test_identity_differ=True,
        candidate_strict_signature_and_extracted_inventory_passed=True, raw_app_removed_and_unregistered=True,
        native_and_service_stores_absent=True, new_pending_hold_and_no_real_ledger=True,
        fake_sdk_20_requests_and_21st_denial=True, zero_web_12_paths_checked=True, startup_first_failure_stops=True,
        thirteen_approval_cases=True, real_child_and_restore_entry_pending_denied=True,
        external_pending_source_audit_no_runtime=True, package_archives_read=len(packages), prepared_runtime_read=True,
        source_path_production_identity_and_ui_experience_not_yet_verified=True,
        native_ui_blocker="Mac locked; user must manually unlock before CUA launch",
        new_20_0_not_authorized=True, all_previous_allowances_frozen=True, rex_acceptance_and_m1_open=True))
    print("OFFLINE READY: same-code full App + CUA wrapper, pending 20/0, guards and read-verified packages; real 0/0. Native UI blocked until user manually unlocks Mac.")


if __name__ == "__main__":
    main()
