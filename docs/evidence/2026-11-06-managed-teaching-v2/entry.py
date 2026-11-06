"""Read-only admission for decision 278; passing still grants no execution."""
import argparse
import json
import os
from pathlib import Path
import sys
from common import ROOT, OUT, PRIVATE, read, sha, files, inventory, unchanged, require, load


def held_runtime(setup, pins):
    runtime = Path(setup["directory"])
    require(files(runtime) == pins, "New pending runtime changed, missing or added files")
    links = {str(p.relative_to(runtime)): os.readlink(p) for p in runtime.rglob("*") if p.is_symlink()}
    require(links == setup["dependency_links"], "New pending dependency links changed")
    auth = read(runtime / "authorization.json")
    require(auth["status"] == "pending" and (runtime / "HOLD").is_file(), "New batch is not held/pending")
    require(not any(os.path.lexists(runtime / p) for p in ["STOP", "quota.json", "startup-claim.json", "bootstrap-ready.json",
        "app.store", "checkpoint.sqlite3", "review.sqlite3", "restored-app.json", "live-events.jsonl"]), "Unexpected new batch activity")
    require(not os.path.lexists(setup["native_app"]), "Candidate is not archived")
    require(auth["batch_id"] == setup["batch_id"] and auth["scope"] == setup["scope"], "Pending identity changed")
    require((auth["actual_model_request_limit"], auth["provider_web_operation_limit"]) == (20, 0), "Pending limits changed")
    require(auth["plan_sha256"] == sha(OUT / "plan.json") and auth["source_pins_sha256"] == sha(OUT / "source-pins.json"), "Pending plan/source pins changed")
    require(sha(setup["native_zip"]) == setup["native_zip_sha256"], "Native candidate changed")
    return len(pins)


def check():
    def audit(event, args):
        if event in {"socket.connect", "socket.bind", "sqlite3.connect"}:
            raise PermissionError("Offline admission cannot connect to network or SQLite")
    sys.addaudithook(audit)
    result, _ = unchanged()
    setup = read(OUT / "setup.json")
    for p, h in read(OUT / "source-pins.json").items():
        require(sha(ROOT / p) == h, "New source pin changed: " + p)
    archives = read(OUT / "archives.json")
    require(sha(archives["runtime_archive"]) == archives["runtime_sha256"], "Prepared runtime archive changed")
    count = held_runtime(setup, archives["runtime_files"])
    require(__import__("subprocess").run(["lsof", "-nP", "-iTCP:" + str(setup["port"]), "-sTCP:LISTEN", "-t"], capture_output=True).returncode == 1,
            "New batch port is active")
    return dict(status="OFFLINE_READY_PENDING_NEW_20_0", decision=278, protection=result,
        runtime_files_matched=count, execution_dependencies_matched=len(setup["post_exit_native_dependencies"]),
        batch_id=setup["batch_id"], pending_hold=True, actual_execution_authorized=False,
        actual_model_requests=0, actual_web_operations=0, app_or_service_started=False, formal_databases_opened=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["status"])


if __name__ == "__main__":
    main()
