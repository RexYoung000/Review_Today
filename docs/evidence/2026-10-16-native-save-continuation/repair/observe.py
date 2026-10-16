"""Read only the isolated service checkpoint; never sends a message or retry."""
import json
from pathlib import Path
import sqlite3
import sys
import time


EVIDENCE = Path(__file__).resolve().parent
setup = json.loads((EVIDENCE / "setup.json").read_text())
directory = Path(setup["directory"])


def read():
    with sqlite3.connect(f"file:{directory / 'checkpoint.sqlite3'}?mode=ro", uri=True) as db:
        row = db.execute("SELECT payload FROM agent_sessions_v2 WHERE session_id=?", (setup["session_id"],)).fetchone()
        data = json.loads(row[0])
        data["tasks"] = {row[0]: json.loads(row[1]) for row in db.execute("SELECT task_id,payload FROM harness_tasks")}
    offer = data["capture_offers"][setup["offer_id"]]
    run = data["runs"].get(data.get("foreground")) or {}
    count = json.loads((directory / "request-count.json").read_text())["actual_requests"]
    return data, dict(requests=count, foreground_status=run.get("status"), foreground_stage=run.get("stage"),
                      offer_status=offer["status"], saved_ids=offer.get("knowledge_ids", []))


if __name__ == "__main__":
    deadline = time.monotonic() + int(sys.argv[1] if len(sys.argv) > 1 else "0")
    previous = None
    while True:
        data, summary = read()
        if summary != previous:
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            previous = summary
        if summary["offer_status"] in {"saved", "failed"} or time.monotonic() >= deadline:
            (directory / "observed-checkpoint.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            break
        time.sleep(1)
