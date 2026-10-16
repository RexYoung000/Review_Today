"""Verify controlled repair and preserve the original stopped 23/30 trial."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
CHANGED = {"agent-service/agent_service/capture_preview.py", "agent-service/agent_service/knowledge_invitation.py"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    base = setup["protected"]
    tests = {}
    for name, passed, subtests in (("fixed-tests.log", 26, 25), ("full-tests.log", 1241, 565), ("deepseek-tests.log", 44, 29)):
        summaries = [line for line in (EVIDENCE / name).read_text().splitlines() if re.search(r"\d+ passed", line)]
        summary = summaries[-1]
        assert f"{passed} passed" in summary and f"{subtests} subtests passed" in summary and "failed" not in summary, summary
        if name == "full-tests.log":
            assert "4 skipped" in summary
        tests[name] = summary
    baseline = (EVIDENCE / "baseline-tests.log").read_text().splitlines()[-1]
    assert "8 failed, 4 passed" in baseline and "5 subtests passed" in baseline
    protected = {}
    for group in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256", "protected_archive_sha256"):
        changes = {name for name, sha in base[group].items() if digest(ROOT / name) != sha}
        assert changes == (CHANGED if group == "python_source_sha256" else set()), (group, changes)
        protected[group] = dict(count=len(base[group]), changes=sorted(changes))
    assert all(digest(ROOT / path) == sha for path, sha in setup["real_trial_archive_sha256"].items())
    trial = Path(base["directory"])
    assert digest(trial / "request-count.json") == setup["trial_counter_sha256"]
    assert digest(trial / "STOP") == setup["trial_stop_sha256"]
    assert json.loads((trial / "request-count.json").read_text()) == dict(actual_requests=23, limit=30)
    real_after = json.loads((EVIDENCE.parent / "2026-10-16-preview-real-recheck/backend-after.json").read_text())
    with sqlite3.connect(f"file:{trial / 'checkpoint.sqlite3'}?mode=ro", uri=True) as db:
        current = json.loads(db.execute("SELECT payload FROM agent_sessions_v2 WHERE session_id=?", (base["session_id"],)).fetchone()[0])
    for key in ("messages", "runs", "capture_offers"):
        assert current[key] == real_after[key], key
    assert all(digest(item["path"]) == item["sha256"] for item in base["daily_files_before"])
    parent = Path(base["parent_runtime"])
    assert all(digest(parent / name) == sha for name, sha in base["parent_runtime_sha256"].items())
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == base["project_diff_sha256"]
    assert digest(Path(base["native_app"]) / "Contents/MacOS/ContinuousResumeQA") == base["prior_native_binary_sha256"]
    old = json.loads((EVIDENCE.parent / "2026-10-16-continuous-acceptance/live/setup.json").read_text())
    assert digest(Path(old["prior_runtime"]) / "request-count.json") == old["prior_counter_sha256"]
    assert digest(Path(old["prior_runtime"]) / "STOP") == old["prior_stop_sha256"]
    listener = subprocess.run(["lsof", "-nP", f"-iTCP:{base['port']}", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    replay = json.loads((EVIDENCE / "replay-result.json").read_text())
    assert replay["outcome"] == "PASS_CONTROLLED_REAL_DATA_REPAIR" and replay["real_model_requests"] == 0
    result = dict(outcome="PASS_CONTROLLED_UPDATE_PREVIEW_REPAIR", decision=239, baseline_commit=setup["baseline_commit"],
        changed_production_sources=sorted(CHANGED), baseline_tests=baseline, tests=tests,
        new_tests=8, new_subtests=9, existing_one_fallback_expectation_revised=True,
        retained_data_replay="replay-result.json", original_real_quotes_rejected_before_publication=True,
        safe_field_locations_received_by_existing_repair=True, one_repair_total_preserved=True,
        legacy_missing_malformed_first_invitation_and_existing_source_guards_preserved=True,
        new_real_model_requests=0, original_requests=23, original_limit=30, unused_allowance=7,
        original_stop_and_failed_preview_state_preserved=True, protected=protected,
        real_trial_archive_files_unchanged=len(setup["real_trial_archive_sha256"]),
        daily_files_unchanged=len(base["daily_files_before"]), project_user_difference_preserved=True,
        old_batch_30_and_stop_preserved=True, service_remains_closed=True, daily_app_replaced=False,
        native_ui_revalidated=False, new_real_model_repair_verified=False, full_eight_step_acceptance=False)
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
