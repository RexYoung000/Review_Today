"""Archive the failed cold start without starting Python service or model calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    setup = json.loads((EVIDENCE / "setup.json").read_text())
    directory = Path(setup["directory"])
    count = json.loads((directory / "request-count.json").read_text())
    assert count == {"actual_requests": 0, "limit": 30}
    assert (directory / "STOP").read_text().startswith("HOLD:")
    assert not (directory / "live-events.jsonl").exists(), "Inspect any new audit before finalizing"
    listener = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    assert listener.returncode == 1 and not listener.stdout.strip()
    process_lines = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    owned = [line.strip() for line in process_lines
             if str(directory) in line and int(line.split(None, 1)[0]) != os.getpid()]
    assert not owned, "QA process still running"
    events = [json.loads(line) for line in (directory / "native-events.jsonl").read_text().splitlines()]
    assert len(events) == 2 and events[0]["phase"] == "initial" and events[-1]["phase"] == "snapshot"
    for event in events:
        assert event["session_id"].lower() == setup["session_id"]
        assert event["mode"] == "modelValidation" and event["knowledge_count"] == 0
        assert all(event[key] == [] for key in ("knowledge", "sources", "tasks", "messages", "runs"))
        assert json.loads(event["capture_offers_json"]) == []
        assert event["cursor"] == 0 and event["checkpoint_json"] == ""
    disk = json.loads((directory / "native-disk-read.json").read_text())
    assert disk["knowledge_count"] == disk["source_count"] == disk["fsrs_count"] == 0
    assert all(disk[key] == [] for key in ("cards", "messages", "runs"))
    assert disk["sessions"] == [{"cursor": 0, "id": setup["session_id"]}]
    protected = {}
    for key in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256", "prior_evidence_sha256"):
        assert all(digest(ROOT / name) == expected for name, expected in setup[key].items()), key
        protected[key] = {"count": len(setup[key]), "unchanged": True}
    assert all(digest(item["path"]) == item["sha256"] for item in setup["daily_files_before"])
    diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(diff).hexdigest() == setup["project_diff_sha256"]
    prior = Path(setup["prior_runtime"])
    assert digest(prior / "request-count.json") == setup["prior_counter_sha256"]
    assert digest(prior / "STOP") == setup["prior_stop_sha256"]
    assert digest(EVIDENCE / "NativeContinuousQA.swift") == setup["native_entry_sha256"]
    assert digest(Path(setup["native_app"]) / "Contents/MacOS/ContinuousQA") == setup["native_binary_sha256"]
    reader = json.loads((EVIDENCE / "native-reader-source.json").read_text())
    assert digest(ROOT / reader["source"]) == reader["sha256"]
    final_ui = (EVIDENCE / "startup-final.txt").read_text()
    assert "本地学习服务未能启动" in final_ui and "本地运行环境尚未完成初始化" in final_ui
    for name in ("request-count.json", "STOP", "authorization.json", "native-events.jsonl", "native-disk-read.json"):
        shutil.copy2(directory / name, EVIDENCE / name)
    sample = directory / "startup-sample.txt"
    text = sample.read_text()
    assert all(name in text for name in ("Py_InitializeFromConfig", "os_listdir", "__opendir2", "open$NOCANCEL"))
    (EVIDENCE / "startup-stack.txt").write_text(text.split("Binary Images:", 1)[0].rstrip() + "\n")
    shutil.copy2(directory / "startup-sample.log", EVIDENCE / "startup-sample.log")
    # The native disk reader calls the existing migration backup helper. Its
    # ReviewBackups/*.sqlite3 files are SwiftData snapshots, not service stores.
    backups = list((directory / "ReviewBackups").glob("*.sqlite3"))
    backend_candidates = [path for path in directory.glob("**/*.sqlite3")
                          if "ReviewBackups" not in path.relative_to(directory).parts]
    assert not backend_candidates, "Unexpected backend store; inspect before claiming absence"
    assert not (directory / "checkpoint.sqlite3").exists()
    result = dict(
        outcome="BLOCKED_BEFORE_MODEL_START", decision=237, real_model_requests=0, limit=30,
        remaining_requests=30, learning_input_sent=False, model_audit_started=False,
        default_startup_retry_limit=4, startup_terminal_failure_seen_in_native_ui=True,
        sampled_attempts=1, sampled_layer="Python initialization / directory read",
        root_cause="unknown; a macOS access prompt is a hypothesis, not an established denial",
        user_prompt_observation="User answered 没有理解; presence or absence of an OS prompt is unconfirmed",
        learning_steps="all not run", native_empty_store_before_and_after=True,
        independent_native_disk_read=True, native_app_and_owned_service_closed=True,
        qa_port_listeners=0, stop="HOLD", backend_store_created=False,
        native_reader_migration_backup_files=len(backups),
        protected=protected, daily_files_unchanged=len(setup["daily_files_before"]),
        original_project_diff_unchanged=True, original_batch_counter_and_stop_unchanged=True,
        source_sample=dict(path=str(sample), sha256=digest(sample), archived="startup-stack.txt (call graph excerpt)"),
        production_changes=False, daily_app_replaced=False, product_acceptance_passed=False,
    )
    (EVIDENCE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Startup evidence verified: blocked before model; 0/30; empty native disk; protected files unchanged")


if __name__ == "__main__":
    main()
