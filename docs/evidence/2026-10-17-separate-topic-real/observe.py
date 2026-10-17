"""Read the current isolated checkpoint; never send input or call a model."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
EVIDENCE=Path(__file__).resolve().parent


def main():
    setup=json.loads((EVIDENCE/"setup.json").read_text())
    directory=Path(setup["directory"])
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(directory/"checkpoint.sqlite3"),REVIEW_TODAY_JEV_TEST="0")
    sys.path.insert(0,str(ROOT/"agent-service"))
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    store=ConversationStore(HarnessStore(str(directory/"checkpoint.sqlite3")))
    data=store.get(setup["session_id"])
    phase=sys.argv[1]
    (EVIDENCE/(phase+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    rows=[json.loads(x) for x in (directory/"live-events.jsonl").read_text().splitlines()]
    result=dict(phase=phase,requests=json.loads((directory/"request-count.json").read_text())["actual_requests"],
        messages=[{k:m.get(k) for k in ("message_id","role","content","run_id")} for m in data["messages"][-3:]],
        runs=[dict(id=r["run_id"],status=r["status"],error=r.get("error_code")) for r in data["runs"].values()],
        offers=[dict(id=o.get("id",oid),version=o.get("version"),status=o.get("status"),scope=o.get("scope"),preview=o.get("preview")) for oid,o in data["capture_offers"].items()],
        tasks=[dict(id=t["task_id"],mode=t["mode"],status=t["status"],context_keys=list(t["context"])) for t in data["tasks"].values()],
        sdk_requests=sum(r["type"]=="sdk_wire_request" for r in rows),
        semantic_outputs=[r["schema"] for r in rows if r["type"]=="semantic_output"],stop=(directory/"STOP").exists())
    (EVIDENCE/(phase+"-summary.json")).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
