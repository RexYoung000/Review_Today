"""Offline input audit only. Stop before answer/capture; never call a provider.

Run with agent-service/.venv/bin/python. Uses archived JSON in independent DBs;
does not reopen the actual QA or daily databases. Fixed semantic decisions are
fixtures, not new evidence of model routing or answer quality.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / "docs/evidence/2026-10-17-separate-topic-real"
RETURN_INPUT = "回到刚才的 RAG：高相似度是否能证明资料可信？请结合刚才讲义中的过时接口例子解释；只解释，不保存或进入下一步。"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def tree(path):
    return {str(p.relative_to(path)): digest(p) for p in sorted(Path(path).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


class BoundaryReached(BaseException):
    """Deliberately escape the production Exception handler before generation."""


def main():
    prior = read(PRIOR / "setup.json")
    scratch = Path(tempfile.mkdtemp(prefix="review-today-source-workspace-audit-", dir="/tmp")).resolve()
    before = read(PRIOR / "before-input.json")
    after = read(PRIOR / "backend-after.json")
    sid, task_id = before["session_id"], before["active_task_id"]
    offer_id = next(iter(before["capture_offers"]))
    offer = before["capture_offers"][offer_id]
    assert offer["version"] == 3 and before["capture_offers"] == after["capture_offers"]
    restored = deepcopy(after)
    restored["tasks"][task_id]["context"]["sources"] = deepcopy(before["tasks"][task_id]["context"]["sources"])
    assert len(before["tasks"][task_id]["context"]["sources"]) == 1
    assert after["tasks"][task_id]["context"]["sources"] == []

    # Verify the inherited baselines before any module-level stores are imported.
    protected = {ROOT / k: v for k, v in prior["protected_archive_sha256"].items()}
    protected.update({PRIOR / k: v for k, v in tree(PRIOR).items()})
    protected.update({ROOT / k: v for group in ("provider_config_sha256", "swift_source_sha256", "python_source_sha256")
                      for k, v in prior[group].items()})
    daily_missing = []
    for item in prior["daily_files_before"]:
        if item["exists"]:
            protected[Path(item["path"])] = item["sha256"]
        else:
            daily_missing.append(item["path"])
    for runtime in prior["parent_runtimes"].values():
        protected.update({Path(runtime["directory"]) / k: v for k, v in runtime["sha256"].items()})
    current_runtime = Path(prior["directory"])
    protected.update({p: digest(p) for p in current_runtime.iterdir() if p.is_file()})
    app = Path(prior["native_app"])
    app_snapshot = tree(app)
    protected.update({app / k: v for k, v in app_snapshot.items()})
    old = read(ROOT / "docs/evidence/2026-10-16-continuous-acceptance/live/setup.json")
    for name, key in (("request-count.json", "prior_counter_sha256"), ("STOP", "prior_stop_sha256")):
        protected[Path(old["prior_runtime"]) / name] = old[key]
    assert read(current_runtime / "request-count.json")["actual_requests"] == 30
    assert (current_runtime / "STOP").is_file()
    assert all(p.is_file() and digest(p) == expected for p, expected in protected.items())
    assert all(not Path(p).exists() for p in daily_missing)
    project_diff = subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)
    assert hashlib.sha256(project_diff).hexdigest() == prior["project_diff_sha256"]
    write("setup.json", dict(directory=str(scratch), baseline_commit=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        checkpoints={str(p.relative_to(ROOT)): digest(p) for p in (PRIOR / "before-input.json", PRIOR / "backend-after.json")},
        session_id=sid, task_id=task_id, offer_id=offer_id, offer_version=offer["version"],
        protected_count=len(protected), protected_archive_count=len(prior["protected_archive_sha256"]) + len(tree(PRIOR)),
        daily_missing=daily_missing, production_mutation_authorized=False,
        real_model_limit_remaining=0, return_input=RETURN_INPUT,
        caveat="Semantic fixtures only; stop before answer or capture. No real routing, answer, verification, save or ACK."))

    # Required before imports: no default daily DB initialization or network.
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY", "EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
        os.environ[name] = ""
    os.environ.update(REVIEW_TODAY_HARNESS_DB=str(scratch / "default.sqlite3"), REVIEW_TODAY_JEV_TEST="0",
                      REVIEW_TODAY_LLM_PROVIDER="openai_compatible", REVIEW_TODAY_SEARCH_PROVIDER="none",
                      REVIEW_TODAY_CONTEXT_PROVIDER="none", REVIEW_TODAY_BROWSER_FALLBACK="0")
    sys.path.insert(0, str(ROOT / "agent-service"))
    calls = dict(network=0, sdk_client=0, request_identity=0, unexpected_model=0, outside_sqlite=0)
    sqlite_open = sqlite3.connect

    def forbidden(name):
        def stop(*args, **kwargs):
            calls[name] += 1
            raise AssertionError("Audit forbids " + name)
        return stop

    def isolated_sqlite(database, *args, **kwargs):
        if not Path(database).resolve().is_relative_to(scratch):
            calls["outside_sqlite"] += 1
            raise AssertionError("SQLite outside isolated audit directory")
        return sqlite_open(database, *args, **kwargs)

    results = []
    with ExitStack() as guards:
        guards.enter_context(patch("sqlite3.connect", side_effect=isolated_sqlite))
        guards.enter_context(patch("socket.socket.connect", side_effect=forbidden("network")))
        guards.enter_context(patch("socket.socket.connect_ex", side_effect=forbidden("network")))
        guards.enter_context(patch("socket.create_connection", side_effect=forbidden("network")))
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import ConversationOutput, IntentDecision, SessionMessageRequest, TeachingPreparation
        guards.enter_context(patch("agent_service.openai_client._client", side_effect=forbidden("sdk_client")))
        guards.enter_context(patch("agent_service.openai_client._request_identity", side_effect=forbidden("request_identity")))

        for case_name, checkpoint in (("before26", before), ("after30", after), ("after30_restored_sources", restored)):
            for action in ("return_answer", "bound_save"):
                store = ConversationStore(HarnessStore(str(scratch / f"{case_name}-{action}.sqlite3")))
                with store.transaction(sid) as data:
                    data.update(deepcopy(checkpoint))
                baseline = store.get(sid)
                # Task restoration updates only its timestamp; not its data.
                for key in checkpoint["tasks"]:
                    assert {k: v for k, v in baseline["tasks"][key].items() if k != "updated_at"} == {
                        k: v for k, v in checkpoint["tasks"][key].items() if k != "updated_at"}
                harness = ConversationHarness(store)
                observed = dict(case=case_name, action=action, fixture_schemas=[], boundary_reached=False)

                def model_fixture(system, user, schema, **kwargs):
                    observed["fixture_schemas"].append(schema.__name__)
                    if action == "return_answer" and schema is IntentDecision:
                        return IntentDecision(intents=["followup"], relation="continuation", scope="continue_goal",
                            target_task_id=task_id, answer_only=True, rationale="受控夹具：回到原 RAG，只解释、不保存或推进")
                    if action == "return_answer" and schema is TeachingPreparation:
                        return TeachingPreparation(concepts=[], public_query="")
                    if action == "return_answer" and issubclass(schema, ConversationOutput):
                        observed.update(boundary_reached=True, boundary="prepared_answer_input",
                                        system_sha256=hashlib.sha256(system.encode()).hexdigest(),
                                        input=json.loads(user))
                        raise BoundaryReached()
                    calls["unexpected_model"] += 1
                    raise AssertionError("Unexpected semantic node: " + schema.__name__)

                def capture_boundary(commit_id, content, language, **kwargs):
                    assert action == "bound_save"
                    current = store.get(sid)
                    observed.update(boundary_reached=True, boundary="before_capture_generation", input=dict(
                        content=content, language=language, draft=deepcopy(current["draft"]),
                        commit_sources=deepcopy(current["tasks"][commit_id]["context"]["sources"]),
                        selected_offer_id=offer_id, selected_offer_version=current["capture_offers"][offer_id]["version"],
                        confirmed_content=kwargs["confirmed_content"], force_source_view=kwargs["force_source_view"]))
                    raise BoundaryReached()

                operation = dict(kind="capture_save", target_id=offer_id, version=offer["version"]) if action == "bound_save" else None
                with patch("agent_service.conversation.parse_model", side_effect=model_fixture), \
                        patch("agent_service.conversation.run_capture", side_effect=capture_boundary):
                    accepted = harness.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()),
                        content="capture_save" if operation else RETURN_INPUT, mode_preset=checkpoint["mode"], operation=operation))
                    try:
                        harness.drain(sid)
                    except BoundaryReached:
                        pass
                current = store.get(sid)
                run = current["runs"][accepted.run_id]
                assert observed["boundary_reached"], {"case": case_name, "action": action, "run": run}
                assert current["messages"][:len(checkpoint["messages"])] == checkpoint["messages"]
                assert all(current["runs"][k] == v for k, v in checkpoint["runs"].items())
                assert current["tasks"][task_id]["context"]["learning_plan"] == checkpoint["tasks"][task_id]["context"]["learning_plan"]
                assert not any(t.get("memory_package") for t in current["tasks"].values())
                if action == "return_answer":
                    payload = observed["input"]
                    lesson = payload["context"]["task"]["context"]["last_lesson"]
                    assert current["capture_offers"] == checkpoint["capture_offers"]
                    observed.update(source_count=len(payload["sources"]),
                        source_ids=[s["source_id"] for s in payload["sources"]],
                        last_lesson_length=len(lesson), original_lesson_preserved=lesson == before["tasks"][task_id]["context"]["last_lesson"],
                        timeout_example_in_lesson="默认超时 30 秒" in lesson and "10 秒" in lesson,
                        run_teaching_sources_count=len(run.get("teaching_sources", [])))
                else:
                    assert observed["fixture_schemas"] == []
                    assert observed["input"]["draft"] == offer["draft"]
                    assert observed["input"]["commit_sources"] == offer["sources"]
                    observed.update(source_count=len(observed["input"]["commit_sources"]),
                        content_sha256=hashlib.sha256(observed["input"]["content"].encode()).hexdigest(),
                        frozen_draft_matches_original=True, frozen_sources_match_original=True)
                observed["model_calls"] = [{k: c[k] for k in ("node", "status", "transport_requests", "request_ids", "usage")}
                                           for c in run.get("model_calls", [])]
                assert all(c["transport_requests"] == 0 and c["request_ids"] == [] and c["usage"] == []
                           for c in observed["model_calls"])
                write(f"{case_name}-{action}.json", observed)
                results.append({k: v for k, v in observed.items() if k != "input"})

    answers = [x for x in results if x["action"] == "return_answer"]
    saves = [x for x in results if x["action"] == "bound_save"]
    assert [x["source_count"] for x in answers] == [1, 0, 1]
    assert all(x["original_lesson_preserved"] and x["timeout_example_in_lesson"] for x in answers)
    assert [x["source_count"] for x in saves] == [1, 1, 1]
    assert len({x["content_sha256"] for x in saves}) == 1
    assert all(v == 0 for v in calls.values())
    assert all(p.is_file() and digest(p) == expected for p, expected in protected.items())
    assert tree(app) == app_snapshot
    assert all(not Path(p).exists() for p in daily_missing)
    assert hashlib.sha256(subprocess.check_output(["git", "diff", "--", "Review_Today.xcodeproj/project.pbxproj"], cwd=ROOT)).hexdigest() == prior["project_diff_sha256"]
    assert read(current_runtime / "request-count.json")["actual_requests"] == 30
    write("result.json", dict(outcome="AUDIT_REPRODUCED_SOURCE_INPUT_GAP", real_model_requests=0,
        original_actual_requests=30, original_limit=30, original_stop_unchanged=True, cases=results,
        guards=calls, protected_count=len(protected), protected_files_unchanged=True,
        daily_existing_count=5, daily_missing_unchanged=daily_missing, app_files_unchanged=len(app_snapshot),
        production_code_unchanged=True, user_project_diff_unchanged=True,
        findings=dict(return_answer_explicit_sources=[1, 0, 1], narrative_lesson_preserved=True,
                      bound_save_frozen_sources=[1, 1, 1], bound_save_content_identical=True),
        unverified=["Real semantic route back to RAG", "Real answer quality", "Model grounding/verification", "Actual native save and ACK"],
        caveat="Stopped before generation; no successful model answer or saved card is claimed."))
    print(json.dumps(dict(outcome="AUDIT_REPRODUCED_SOURCE_INPUT_GAP", cases=len(results),
        explicit_answer_sources=[1, 0, 1], frozen_save_sources=[1, 1, 1], original_lesson_preserved=True,
        real_model_requests=0, guards=calls, protected_files_unchanged=len(protected)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
