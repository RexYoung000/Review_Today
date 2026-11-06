"""Decision-278 independent baseline; old failed scenes stay sealed as evidence."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex/2026-11-06-managed-teaching-v2"
ARCHIVE = PRIVATE / "archives"
DAILY = Path("/Applications/Review Today.app")
SUPPORT = Path.home() / "Library/Application Support/Review Today"
LS = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
BASELINE_SHA256 = "0446e768a6fa46354b6fd541b190803c9526829e8a2def4f55c6d00c378e0158"


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = load("frozen_packaging_helpers", ROOT / "docs/evidence/2026-10-23-daily-update-preflight/common.py")
files, inventory, stopped = helpers.files, helpers.inventory, helpers.stopped


def require_idle_port(port):
    require(subprocess.run(["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN", "-t"],
                           capture_output=True).returncode == 1, f"Port {port} is active")


def source_files():
    pins = read(ROOT / "docs/evidence/2026-10-25-managed-teaching-preflight/source-pins.json")
    return pins


def unchanged():
    require(sha(OUT / "baseline.json") == BASELINE_SHA256, "Approved new baseline changed")
    baseline = read(OUT / "baseline.json")
    require(baseline["decision"] == 278 and baseline["preparation_only"] is True and
            baseline["actual_execution_authorized"] is False, "Preparation authority changed")
    for name, anchor in baseline["anchors"].items():
        require(sha(ROOT / anchor["path"]) == anchor["sha256"], "Baseline anchor changed: " + name)
    gate_path = ROOT / baseline["anchors"]["gate_277"]["path"]
    gate = load("historical_primitives_for_278", gate_path)
    policy, docs, expected, copies = gate.load_authorized_policy(gate_path.parent / "policy.json", ROOT)
    gate.strict_files(policy["strict_metadata"], label="Frozen strict metadata")
    history = gate.historical_files(expected, copies, copy_root=policy["copy_root"])
    pins = source_files()
    gate.strict_files({str(ROOT / p): h for p, h in pins.items()}, label="Current source")
    stopped()
    prepared, old = docs["prepared_setup"], docs["baseline"]
    require(inventory(DAILY) == prepared["daily_app_inventory"], "Daily App changed")
    require(not any(p.is_symlink() for p in SUPPORT.rglob("*")), "Formal data symlink added")
    require(files(SUPPORT) == baseline["formal_files"], "Current formal baseline changed")
    gate.strict_files(baseline["formal_files"], label="Current formal data")
    require(all(not os.path.lexists(p) for p in old["known_missing_old_paths"]), "Older gaps changed")
    require(all(not os.path.lexists(p) for p in baseline["old_missing_paths"]), "Sealed old missing paths changed")
    candidates = read(ROOT / baseline["anchors"]["strict_candidates"]["path"])["mapping"]
    archive_pins = {r["candidate"]["archive"]: r["candidate"]["archive_sha256"] for r in candidates.values()}
    gate.strict_files(archive_pins, label="Sealed strict-byte archives")
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    require(hashlib.sha256(diff).hexdigest() == prepared["user_project_diff_sha256"], "User project diff changed")
    gate.strict_files(read(ROOT / "output/daily-service-preflight-2026-10-25/backup-pins.json"), label="Original backups")
    gate.strict_files(prepared["prior_records"], label="Prior 273 records")
    for name in ["2026-10-25-daily-service-preflight", "2026-10-25-daily-service-real", "2026-10-25-managed-teaching-preflight",
                 "2026-10-26-managed-teaching-entry", "2026-10-26-historical-copy-gate", "2026-11-06-historical-copy-gate-v2"]:
        folder = ROOT / "docs/evidence" / name
        gate.strict_files({str(folder / p): h for p, h in read(folder / "artifact-sha256.json").items()}, label="Frozen evidence")
    previous = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex/2026-10-25-daily-service"
    for name in ["actual-runtime", "actual-public-records"]:
        manifest = read(previous / (name + "-manifest.json"))
        gate.strict_files({manifest["archive"]: manifest["sha256"]}, label="273 archive")
    prior = ROOT / "docs/evidence/2026-10-25-daily-service-real"
    require(read(prior / "verification.json")["status"] == "PASS_SERVICE_ONLY_STARTUP_CLOSED", "273 result changed")
    require(read(ROOT / "output/daily-service-preflight-2026-10-25/activation/quota.json") == read(prior / "quota-final.json"), "273 quota changed")
    gate.strict_files({prepared["native_zip"]: prepared["native_zip_sha256"]}, label="Old candidate archive")
    runtime = Path(baseline["old_batch_runtime"])
    require(files(runtime) == baseline["old_runtime_remaining_files"], "Sealed old runtime changed")
    gate.strict_links(runtime, baseline["old_runtime_links"])
    require(not os.path.lexists(prepared["native_app"]), "Old candidate restored")
    require(not any(os.path.lexists(runtime / name) for name in ["quota.json", "startup-claim.json", "bootstrap-ready.json", "app.store", "checkpoint.sqlite3"]), "Old batch activity appeared")
    require(subprocess.run(["lsof", "-nP", "-iTCP:" + str(baseline["old_batch_port"]), "-sTCP:LISTEN", "-t"], capture_output=True).returncode == 1, "Old port is active")
    if (OUT / "setup.json").exists():
        setup = read(OUT / "setup.json")
        if "runtime_alias" in setup:
            alias = Path(setup["runtime_alias"])
            require(alias.is_symlink() and os.readlink(alias) == setup["directory"] and alias.resolve() == Path(setup["directory"]),
                    "New isolated runtime alias changed")
        gate.strict_files(setup["post_exit_native_dependencies"], label="New execution dependencies")
        gate.strict_links(Path(setup["directory"]), setup["dependency_links"])
        require_idle_port(setup["port"])
    require_idle_port(8742)
    stopped()
    require(files(SUPPORT) == baseline["formal_files"], "Formal files changed during check")
    return dict(status="PASS_NEW_BASELINE_OFFLINE", history_original_paths=history["original_paths_matched"],
                history_copy_paths=len(history["original_paths_missing"]), current_source_pins=len(pins),
                current_formal_files=7, sealed_old_missing_paths=len(baseline["old_missing_paths"]),
                previous_277_result_kept_blocked=True, actual_model_requests=0, actual_web_operations=0), pins


def text_section(path):
    rows = subprocess.check_output(["otool", "-s", "__TEXT", "__text", str(path)], text=True).splitlines()[2:]
    return hashlib.sha256(bytes.fromhex("".join("".join(row.split()[1:]) for row in rows))).hexdigest()
