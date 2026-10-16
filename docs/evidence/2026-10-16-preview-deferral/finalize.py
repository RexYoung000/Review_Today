"""Check controlled results and that the stopped real trial stayed untouched."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
CHANGED_SOURCE = "agent-service/agent_service/knowledge_invitation.py"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    results = {}
    for name, expected in (("baseline-tests.log", (1, 7)), ("fixed-tests.log", (4, 7)),
                           ("full-tests.log", (1233, 556)), ("deepseek-tests.log", (36, 20))):
        log = (EVIDENCE / name).read_text()
        lines = [line for line in log.splitlines() if re.search(r"\d+ passed", line)]
        summary = lines[-1]
        assert f"{expected[0]} passed" in summary and f"{expected[1]} subtests passed" in summary, summary
        assert ("3 failed" in summary) if name.startswith("baseline") else ("failed" not in summary), summary
        if name == "full-tests.log":
            assert "4 skipped" in summary
        results[name] = summary

    protection = {}
    for group in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256", "prior_evidence_sha256"):
        changes = [name for name, sha in setup["protected"][group].items() if digest(ROOT / name) != sha]
        assert changes == ([CHANGED_SOURCE] if group == "python_source_sha256" else []), (group, changes)
        protection[group] = dict(files=len(setup["protected"][group]), changes=changes)
    for file in setup["protected"]["daily_files_before"]:
        assert digest(file["path"]) == file["sha256"]
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == setup["project_diff_sha256"]
    for name, archive in setup["archives"].items():
        folder = EVIDENCE.parent / "2026-10-16-continuous-acceptance" / name
        assert digest(folder / "artifact-sha256.json") == archive["manifest_sha256"]
        assert all(digest(folder / path) == sha for path, sha in archive["files"].items()), name
    runtime = Path(setup["runtime"])
    assert all(digest(runtime / name) == sha for name, sha in setup["runtime_sha256"].items())
    assert json.loads((runtime / "request-count.json").read_text()) == {"actual_requests": 20, "limit": 30}
    prior = Path(setup["prior_runtime"])
    assert digest(prior / "STOP") == setup["prior_stop_sha256"]
    assert digest(prior / "request-count.json") == setup["prior_counter_sha256"]
    assert digest(Path(setup["native_app"]) / "Contents/MacOS/ContinuousQA") == setup["native_binary_sha256"]
    listener = subprocess.run(["lsof", "-nP", "-iTCP:49316", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert listener.returncode == 1 and not listener.stdout.strip()
    replay = json.loads((EVIDENCE / "replay-result.json").read_text())
    assert replay["outcome"] == "PASS_CONTROLLED_RETAINED_DATA" and replay["real_model_requests"] == 0
    assert replay["original_invalid_update_still_rejected"]["code"] == "RT.MODEL.SCHEMA"

    result = dict(outcome="PASS_CONTROLLED_IMPLEMENTATION", decision=238, baseline_commit=setup["baseline_commit"],
        production_changed=[CHANGED_SOURCE], tests=results, retained_data_replay="replay-result.json",
        protection=protection, daily_files_unchanged=len(setup["protected"]["daily_files_before"]),
        original_trial_archives_unchanged={name: len(value["files"]) for name, value in setup["archives"].items()},
        stopped_trial_files_unchanged=len(setup["runtime_sha256"]), original_trial_listener_closed=True,
        actual_model_requests=20, limit=30, new_real_model_requests=0, unused_allowance=10,
        old_batch_30_and_stop_unchanged=True, project_user_difference_preserved=True,
        save_consent_version_quote_lifecycle_memory_and_one_repair_guards_preserved=True,
        daily_app_replaced=False, native_ui_revalidated=False, new_real_model_behavior_verified=False,
        complete_eight_step_acceptance=False, final_product_acceptance=False)
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
