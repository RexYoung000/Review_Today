"""Read-only admission diagnostics; every original strict group remains required."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from evidence_gate_v2 import (EvidenceMismatch, absent, historical_files, load_authorized_policy,
                              read, require, strict_file_report, stopped_runtime_report)

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
_AUDIT_INSTALLED = False
REQUIRED_GROUPS = frozenset({
    "policy", "project_location", "strict_metadata", "current_source", "historical_evidence",
    "original_module_files", "owned_support_files", "daily_files", "post_exit_native_dependencies",
    "prior_records", "original_backups", "known_older_gaps", "user_project_diff", "prepared_native_zip",
    "frozen_public_evidence", "daily_processes_stopped_before", "daily_app_inventory_before",
    "formal_inventory_before", "prior_273_archives", "prior_273_result", "prior_273_quota",
    "stopped_runtime", "stopped_authorization_pending", "stopped_hold_and_stop", "stopped_native_app_absent",
    "no_current_activation_artifacts", "old_batch_port_idle_now", "daily_processes_stopped_after",
    "formal_inventory_after", "daily_app_inventory_after",
})


def enforce_offline():
    global _AUDIT_INSTALLED
    if not _AUDIT_INSTALLED:
        def audit(event, args):
            if event in {"socket.connect", "socket.bind", "sqlite3.connect"}:
                raise PermissionError("Offline entry cannot connect to network or SQLite")
            if event == "subprocess.Popen":
                command = args[1]
                allowed = (isinstance(command, (list, tuple)) and (
                    command == ["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"] or
                    command == ["pgrep", "-x", "Review_Today"] or
                    (command[:2] == ["lsof", "-nP"] and command[2].startswith("-iTCP:") and
                     command[3:] in [["-sTCP:LISTEN"], ["-sTCP:LISTEN", "-t"]])))
                if not allowed:
                    raise PermissionError("Offline entry permits only fixed read-only process checks")
        sys.addaudithook(audit)
        _AUDIT_INSTALLED = True


def finish(groups):
    missing = sorted(REQUIRED_GROUPS - groups.keys())
    blocked = sorted(set(missing) | {name for name, value in groups.items() if value["status"] != "PASS"})
    return dict(status="OFFLINE_PROTECTION_BLOCKED" if blocked else "OFFLINE_PROTECTION_PASS_BATCH_STILL_STOPPED",
                decision=277, groups=groups, blocked_groups=blocked, missing_check_groups=missing,
                ready_for_new_batch=not blocked,
                no_batch_activation=True, no_frozen_allowance_restore=True,
                actual_model_requests=0, actual_web_operations=0, formal_databases_opened=False,
                app_or_service_started=False, old_runtime_restoration_performed=False)


def collect():
    enforce_offline()
    groups = {}

    def observe(label, action):
        try:
            value = action()
            if value is False:
                raise EvidenceMismatch(label + " differs from the frozen baseline")
            groups[label] = dict(status="PASS", result=value)
        except (EvidenceMismatch, OSError, ValueError, KeyError, PermissionError, subprocess.SubprocessError) as error:
            groups[label] = dict(status="FAIL", error=f"{type(error).__name__}: {error}")

    try:
        policy, documents, expected, copies = load_authorized_policy(OUT / "policy.json", ROOT)
    except (EvidenceMismatch, OSError, ValueError, KeyError) as error:
        return finish(dict(policy=dict(status="FAIL", error=str(error))))
    groups["policy"] = dict(status="PASS", decision=277, approved_paths=157)
    baseline, prepared = documents["baseline"], documents["prepared_setup"]
    # Old absolute paths are retained; relocation does not silently rebase pins.
    old_root = Path(next(iter(policy["strict_metadata"]))).parents[3]
    observe("project_location", lambda: old_root.resolve() == ROOT)
    groups["strict_metadata"] = strict_file_report(policy["strict_metadata"], label="Strict reference metadata")
    if any(groups[k]["status"] != "PASS" for k in ["project_location", "strict_metadata"]):
        groups["dependent_checks"] = dict(status="SKIPPED", reason="Untrusted reference metadata or relocation")
        return finish(groups)
    source = read(ROOT / "docs/evidence/2026-10-25-managed-teaching-preflight/source-pins.json")
    groups["current_source"] = strict_file_report({str(ROOT / p): h for p, h in source.items()}, label="Current source/config/entry")
    observe("historical_evidence", lambda: historical_files(expected, copies, copy_root=policy["copy_root"]))
    for key in ["original_module_files", "owned_support_files"]:
        groups[key] = strict_file_report(baseline[key], label=key)
    for key in ["daily_files", "post_exit_native_dependencies", "prior_records"]:
        groups[key] = strict_file_report(prepared[key], label=key)
    backup = read(ROOT / "output/daily-service-preflight-2026-10-25/backup-pins.json")
    groups["original_backups"] = strict_file_report(backup, label="Prepared original backups")
    observe("known_older_gaps", lambda: all(absent(p) for p in baseline["known_missing_old_paths"]))
    observe("user_project_diff", lambda: hashlib.sha256(subprocess.check_output(
        ["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest() == prepared["user_project_diff_sha256"])
    groups["prepared_native_zip"] = strict_file_report({prepared["native_zip"]: prepared["native_zip_sha256"]}, label="Prepared native candidate")
    public_pins = {}
    for name in ["2026-10-25-daily-service-preflight", "2026-10-25-daily-service-real",
                 "2026-10-25-managed-teaching-preflight", "2026-10-26-managed-teaching-entry"]:
        folder = ROOT / "docs/evidence" / name
        public_pins.update({str(folder / p): h for p, h in read(folder / "artifact-sha256.json").items()})
    groups["frozen_public_evidence"] = strict_file_report(public_pins, label="Frozen public evidence")
    if groups["current_source"]["status"] != "PASS":
        groups["helper_dependent_checks"] = dict(status="SKIPPED", reason="Frozen helper source is not verified")
        return finish(groups)
    helper_path = ROOT / "docs/evidence/2026-10-25-managed-teaching-preflight/common.py"
    spec = importlib.util.spec_from_file_location("frozen_274_helpers", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    observe("daily_processes_stopped_before", helper.stopped)
    observe("daily_app_inventory_before", lambda: helper.inventory(helper.DAILY) == prepared["daily_app_inventory"])
    observe("formal_inventory_before", lambda: formal_inventory_matches(helper.SUPPORT, prepared["daily_files"], helper.files))
    archive_pins = {}
    for name in ["actual-runtime", "actual-public-records"]:
        manifest = read(helper.PREVIOUS_ARCHIVE / (name + "-manifest.json"))
        archive_pins[manifest["archive"]] = manifest["sha256"]
    groups["prior_273_archives"] = strict_file_report(archive_pins, label="Prior 273 archive")
    observe("prior_273_result", lambda: read(helper.PRIOR / "verification.json")["status"] == "PASS_SERVICE_ONLY_STARTUP_CLOSED")
    observe("prior_273_quota", lambda: read(helper.PREVIOUS_ACTIVATION / "quota.json") == read(helper.PRIOR / "quota-final.json"))
    runtime = Path(prepared["directory"])
    runtime_pins = read(ROOT / "output/managed-teaching-preflight-2026-10-25/runtime-pins.json") | policy["stopped_control_files"]
    links = read(ROOT / "docs/evidence/2026-10-25-managed-teaching-preflight/archives.json")["dependency_links"]
    groups["stopped_runtime"] = stopped_runtime_report(runtime, runtime_pins, links, helper.files)
    observe("stopped_authorization_pending", lambda: read(runtime / "authorization.json")["status"] == "pending")
    observe("stopped_hold_and_stop", lambda: (runtime / "HOLD").is_file() and (runtime / "STOP").is_file())
    observe("stopped_native_app_absent", lambda: absent(prepared["native_app"]))
    observe("no_current_activation_artifacts", lambda: all(absent(runtime / p) for p in [
        "quota.json", "startup-claim.json", "bootstrap-ready.json", "app.store", "checkpoint.sqlite3"]))
    observe("old_batch_port_idle_now", lambda: subprocess.run(
        ["lsof", "-nP", "-iTCP:" + str(prepared["port"]), "-sTCP:LISTEN", "-t"], capture_output=True).returncode == 1)
    observe("daily_processes_stopped_after", helper.stopped)
    observe("formal_inventory_after", lambda: formal_inventory_matches(helper.SUPPORT, prepared["daily_files"], helper.files))
    observe("daily_app_inventory_after", lambda: helper.inventory(helper.DAILY) == prepared["daily_app_inventory"])
    return finish(groups)


def formal_inventory_matches(directory, expected, files):
    # The frozen helper resolves paths; reject aliases before they collapse into
    # an existing key and conceal an added formal-data path.
    require(not any(p.is_symlink() for p in Path(directory).rglob("*")), "Formal data contains a symlink")
    return files(directory) == expected


def check():
    result = collect()
    require(result["status"] == "OFFLINE_PROTECTION_PASS_BATCH_STILL_STOPPED",
            "Offline protection blocked: " + ", ".join(result["blocked_groups"]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print every group, with nonzero exit on any failure")
    args = parser.parse_args()
    result = collect()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          result["status"] + ": " + ", ".join(result["blocked_groups"]))
    return 0 if result["ready_for_new_batch"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
