"""Read only this batch's consistent copies and fresh native-reader output.

No service imports, provider requests, UI actions, or product-data mutations.
Run before updating the project status documents, while input pins still match.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PREP = OUT.parent / "2026-10-24-teaching-scope-fullflow-preflight"
sys.path.insert(0, str(PREP))
import common


def load(path):
    return json.loads(path.read_text())


def main():
    setup = load(PREP / "setup.json")
    runtime = Path(setup["directory"])
    common.check_protection(setup)
    assert not subprocess.run(["pgrep", "-x", "FreshFullflowQA"], capture_output=True).stdout
    assert not subprocess.run(
        ["lsof", "-nP", f"-iTCP:{setup['port']}", "-sTCP:LISTEN"], capture_output=True
    ).stdout
    assert all(common.sha(Path(p)) == h for p, h in setup["owned_support_files"].items())
    capture = common.DURABLE / "captures/after-quit"
    native = load(runtime / "native-disk-read.json")
    with closing(sqlite3.connect((capture / "checkpoint.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("pragma quick_check").fetchall() == [("ok",)]
        rows = db.execute("select session_id,payload from agent_sessions_v2").fetchall()
        assert len(rows) == 1 and rows[0][0] == setup["session_id"]
        session = json.loads(rows[0][1])
        tasks = {tid: json.loads(p) for tid, p in db.execute("select task_id,payload from harness_tasks")}
        assert db.execute("select count(*) from agent_capability_batches").fetchone()[0] == 1
        capability = json.loads(db.execute("select payload from agent_capability_batches").fetchone()[0])
    offer = next(iter(session["capture_offers"].values()))
    save_task = tasks[offer["save_task_id"]]
    learning = tasks[offer["origin_task_id"]]
    assert len(tasks) == 2 and offer["status"] == "saved"
    assert offer["version"] == offer["preview_version"] == save_task["context"]["draft_version"] == 2
    assert save_task["status"] == "completed" and save_task["context"]["commit_claimed"]
    assert len([x for x in save_task["events"] if x["node"] == "mac_ack"]) == 1
    package = save_task["memory_package"]
    cards = {x["id"]: x for x in package["knowledge"]}
    assert len(cards) == 5 and set(cards) == set(offer["knowledge_ids"])
    disk_cards = {x["id"]: x for x in native["cards"]}
    assert set(cards) == set(disk_cards) and native["knowledge_count"] == 5
    assert native["source_count"] == 1 and native["fsrs_count"] == 5
    for kid, card in cards.items():
        actual = disk_cards[kid]
        assert actual["title"] == card["title"] and actual["explanation"] == card["explanation"]
        assert actual["evidence"] == card["evidence_excerpt"]
        assert set(actual["questions"]) == {x["prompt_text"] for x in card["questions"]}
        assert actual["origin_task"] == save_task["task_id"]
        assert actual["origin_session"] == setup["session_id"] and not actual["review"]
        assert card["evidence_excerpt"] in save_task["memory_source_text"]
    assert package["attribution"] == "source_view"
    assert not any(x in json.dumps(package, ensure_ascii=False) for x in ["Python", "元组", "列表"])
    by_message = {x["id"]: x for x in native["messages"]}
    assert len(by_message) == len(native["messages"]) == len(session["messages"]) == 15
    for message in session["messages"]:
        actual = by_message[message["message_id"]]
        assert actual["text"] == message["content"]
        assert actual["role"] == ("assistant" if message["role"] == "coach" else message["role"])
        assert actual["response_state"] == "complete"
        assert actual["run_id"] == message["run_id"]
        if message["role"] == "user":
            assert actual["client_id"] == message["message_id"] and actual["delivery"] == "accepted"
    assert Counter(x["role"] for x in native["messages"]) == {"user": 8, "assistant": 7}
    assert {x["id"] for x in native["runs"]} == set(session["runs"])
    assert len(native["runs"]) == 8 and all(x["status"] == "completed" for x in native["runs"])
    assert all(x["status"] == "completed" for x in session["runs"].values())
    assert native["sessions"] == [{"id": setup["session_id"], "cursor": session["last_acked_seq"]}]
    assert session["last_acked_seq"] == max(x["seq"] for x in session["events"]) == 273
    work = ROOT / "output/teaching-scope-fullflow-real-2026-10-24"
    before = load(work / "return-to-rag.json")["checkpoint"]["tasks"][learning["task_id"]]["context"]
    for key in ["learning_plan", "check_question", "check_binding", "last_lesson", "sources", "practice", "understanding"]:
        assert before.get(key) == learning["context"].get(key), key
    ctx = learning["context"]
    assert ctx["understanding"] == "unknown" and not ctx["practice"][-1]["evaluation"]["step_completion_demonstrated"]
    assert len(ctx["practice"][-1]["verified_concepts"]) == 2
    last = session["messages"][-1]["content"]
    assert "5 张" in last and all(c["title"] in last for c in cards.values())
    with closing(sqlite3.connect((capture / "app.store").as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("pragma quick_check").fetchall() == [("ok",)]
        sources = db.execute("select Z_PK,ZRAWTEXT,ZATTRIBUTION from ZSOURCE").fetchall()
        assert len(sources) == 1 and sources[0][1] == save_task["memory_source_text"]
        assert sources[0][2] == "source_view"
        assert db.execute("select distinct ZSOURCE from ZKNOWLEDGE").fetchall() == [(sources[0][0],)]
        assert db.execute("select ZREVIEWENROLLMENT,count(*) from ZKNOWLEDGE group by ZREVIEWENROLLMENT").fetchall() == [("reference", 5)]
        ntasks = {str(uuid.UUID(bytes=tid)): (status, committed, understood, seq, ack)
                  for tid, status, committed, understood, seq, ack in db.execute(
                      "select ZID,ZSTATUS,ZMEMORYCOMMITTED,ZUNDERSTANDING,ZLASTEVENTSEQ,ZLASTACKEDSEQ from ZLEARNINGTASK")}
        assert ntasks[save_task["task_id"]] == ("completed", 1, "unknown", 2, 2)
        assert ntasks[learning["task_id"]] == ("awaiting_user", 0, "unknown", 4, 4)
        assert db.execute("select ZLASTSESSIONEVENTSEQ,ZSYNCERROR from ZAGENTSESSION").fetchall() == [(273, None)]
    quota = load(runtime / "quota.json")
    assert quota["closed"] and (runtime / "STOP").is_file()
    assert (quota["model_requests"], quota["web_operations"]) == (30, 0)
    assert len(quota["entries"]) == len({x["program_id"] for x in quota["entries"]}) == 30
    assert all(x["dispatched"] and len(x["usage"]) == 1 for x in quota["entries"])
    assert all(x["program_id"] == x["usage"][0]["request_id"] for x in quota["entries"])
    calls = capability["calls"] + [c for run in session["runs"].values() for c in run["model_calls"]]
    assert len(capability["calls"]) == 8 and len(calls) == 30
    assert sum(x["transport_requests"] for x in calls) == 30
    assert {rid for x in calls for rid in x["request_ids"]} == {x["program_id"] for x in quota["entries"]}
    events = [json.loads(x) for x in (runtime / "live-events.jsonl").read_text().splitlines()]
    counts = Counter(x["type"] for x in events)
    assert counts["sdk_wire_request"] == counts["sdk_wire_response"] == counts["semantic_start"] == 30
    assert counts["bootstrap_ready"] == 1
    receipts = [json.loads(x) for x in (runtime / "native-recheck-events.jsonl").read_text().splitlines()
                if json.loads(x)["phase"] == "durable_receipt"]
    assert len(receipts) == 1 and receipts[0]["receipt_already_durable"]
    assert {x.lower() for x in receipts[0]["receipt_card_ids"]} == set(cards)
    assert receipts[0]["receipt_task"].lower() == save_task["task_id"]
    common.check_protection(setup)
    result = dict(
        status="PASS_FROZEN_FUNCTIONAL_PATH", checked_at=datetime.now(timezone.utc).isoformat(),
        native_app_normally_quit=True, owned_service_stopped=True, app_service_restarts=0,
        knowledge_count=5, source_count=1, fsrs_count=5, native_messages=15, native_runs=8,
        unique_native_user_inputs=8, native_assistant_messages=7, cursor_service_native=273,
        all_card_ids_titles_explanations_questions_evidence_and_ownership_match=True,
        one_durable_receipt_and_one_mac_ack_match=True, single_source_view_source_match=True,
        all_review_enrollment="reference", original_learning_context_unchanged=True,
        whole_step_understanding="unknown", only_followup_verified_concepts=2,
        no_step_advance_or_whole_step_mastery=True, status_count_titles_match=True,
        model_requests=30, web_operations=0, remaining_frozen=dict(model=10, web=16),
        all_sdk_requests_and_usage_accounted=True, fresh_capability_batches=1,
        daily_files_unchanged=len(setup["daily_files"]), daily_app_inventory_unchanged=True,
        fixed_source_config_qa_inputs=len(setup["protected_fingerprints"]),
        old_evidence_files_unchanged=len(setup["frozen_existing_files"]),
        original_modules_unchanged=len(setup["original_module_files"]),
        owned_modules_unchanged=len(setup["owned_support_files"]),
        old_missing_paths_remain_missing=len(setup["known_missing_old_paths"]),
        original_formal_databases_opened=False, user_project_diff_unchanged=True,
        limits=["760x620 minimum height not reached; dark 760x820 checked",
                "Full VoiceOver, cross-system behavior, Rex experience and M1 acceptance remain open",
                "This source-view save used no web operations; external factual verification path was not exercised",
                "Two bounded repairs used: teaching evidence eligibility and status intent schema",
                "Historical missing paths and earlier formal-file changes remain separately recorded"],
    )
    common.write(OUT / "disk-verification.json", result)
    private_cards = common.DURABLE / "saved-cards.json"
    card_report = dict(attribution=package["attribution"], cards=list(cards.values()))
    if private_cards.exists():
        assert load(private_cards) == card_report
    else:
        common.write(private_cards, card_report)
    print("PASS: 5 cards / 15 messages / 8 runs / cursor 273 match after normal quit; 30/0 closed; protection unchanged.")


if __name__ == "__main__":
    main()
