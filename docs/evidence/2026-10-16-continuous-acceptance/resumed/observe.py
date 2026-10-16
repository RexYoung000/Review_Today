"""Read only the already-running isolated service checkpoint; no input/model call."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent


def main():
    setup = json.loads((EVIDENCE.parent / "live/setup.json").read_text())
    directory = Path(setup["directory"])
    assert (directory / "checkpoint.sqlite3").exists(), "Never initialize a missing service store"
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory / "checkpoint.sqlite3"), REVIEW_TODAY_JEV_TEST="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    store = ConversationStore(HarnessStore(str(directory / "checkpoint.sqlite3")))
    data = store.get(setup["session_id"])
    phase = sys.argv[1]
    (EVIDENCE / (phase + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    rows = [json.loads(line) for line in (directory / "live-events.jsonl").read_text().splitlines()]
    result = dict(phase=phase, requests=json.loads((directory / "request-count.json").read_text())["actual_requests"],
        messages=[{key: message.get(key) for key in ("message_id", "role", "content", "run_id")} for message in data["messages"][-3:]],
        runs=[dict(id=run["run_id"], status=run["status"], error=run.get("error_code")) for run in data["runs"].values()],
        offers=[dict(id=offer.get("id", key), version=offer.get("version"), status=offer.get("status"),
            scope=offer.get("scope"), preview=offer.get("preview")) for key, offer in data["capture_offers"].items()],
        tasks=[dict(id=task["task_id"], mode=task["mode"], status=task["status"], context_keys=list(task["context"])) for task in data["tasks"].values()],
        sdk_requests=sum(row["type"] == "sdk_wire_request" for row in rows),
        semantic_outputs=[row["schema"] for row in rows if row["type"] == "semantic_output"],
        stop=(directory / "STOP").exists())
    (EVIDENCE / (phase + "-summary.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
