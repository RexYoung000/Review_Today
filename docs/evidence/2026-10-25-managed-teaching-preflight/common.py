"""Incremental protection after batch 273; no service or database imports."""
import importlib.util
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIVATE = ROOT / "output/managed-teaching-preflight-2026-10-25"
ARCHIVE = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex/2026-10-25-managed-teaching"
PRIOR = ROOT / "docs/evidence/2026-10-25-daily-service-real"
PREVIOUS_PREP = ROOT / "docs/evidence/2026-10-25-daily-service-preflight"
PREVIOUS_ARCHIVE = Path.home() / "Library/Developer/ReviewTodayEvidence.noindex/2026-10-25-daily-service"
PREVIOUS_ACTIVATION = ROOT / "output/daily-service-preflight-2026-10-25/activation"
spec = importlib.util.spec_from_file_location("previous_272_common", PREVIOUS_PREP / "common.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
read, write, sha, files, inventory, stopped = previous.read, previous.write, previous.sha, previous.files, previous.inventory, previous.stopped
DAILY, SUPPORT = previous.DAILY, previous.SUPPORT
LS = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"


def unchanged():
    stopped()
    state = read(PREVIOUS_PREP / "setup.json")
    pins = read(PREVIOUS_PREP / "source-pins.json")
    assert inventory(DAILY) == state["daily_app_inventory"]
    assert all(sha(ROOT / p) == h for p, h in pins.items())
    for key in ["prior_evidence_pins", "original_module_files", "owned_support_files"]:
        assert all(Path(p).is_file() and sha(Path(p)) == h for p, h in state[key].items()), key
    assert all(not Path(p).exists() for p in state["known_missing_old_paths"])
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == state["project_diff_sha256"]
    assert all(sha(Path(p)) == h for p, h in read(ROOT / "output/daily-service-preflight-2026-10-25/backup-pins.json").items())
    assert all(sha(PREVIOUS_PREP / p) == h for p, h in read(PREVIOUS_PREP / "artifact-sha256.json").items())
    assert files(SUPPORT) == read(PREVIOUS_ARCHIVE / "actual/after-file-pins.json"), "Daily data drift after 273"
    assert read(PRIOR / "verification.json")["status"] == "PASS_SERVICE_ONLY_STARTUP_CLOSED"
    assert read(PREVIOUS_ACTIVATION / "quota.json") == read(PRIOR / "quota-final.json")
    assert all(sha(PRIOR / p) == h for p, h in read(PRIOR / "artifact-sha256.json").items())
    for name in ["actual-runtime", "actual-public-records"]:
        manifest = read(PREVIOUS_ARCHIVE / (name + "-manifest.json"))
        assert sha(Path(manifest["archive"])) == manifest["sha256"]
    if (OUT / "setup.json").exists():
        new = read(OUT / "setup.json")
        assert all(sha(Path(p)) == h for p, h in new["prior_records"].items())
    return state, pins


def text_section(path):
    rows = subprocess.check_output(["otool", "-s", "__TEXT", "__text", str(path)], text=True).splitlines()[2:]
    import hashlib
    return hashlib.sha256(bytes.fromhex("".join("".join(row.split()[1:]) for row in rows))).hexdigest()
