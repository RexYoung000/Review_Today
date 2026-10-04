"""Observe source selection at the real Harness -> parse_model boundary.

Only synthetic sources and temporary stores are used. Model and reader transports
are replaced, while routing, budgets, checkpoints and prompt assembly stay real.
"""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
from unittest.mock import patch

# Importing the service constructs a default HarnessStore. Fence that import as
# well as each fixture, including direct execution of this test module.
_IMPORT_DB = tempfile.TemporaryDirectory(prefix="rt-source-selection-import-")
os.environ.setdefault("REVIEW_TODAY_HARNESS_DB", str(Path(_IMPORT_DB.name) / "harness.sqlite3"))
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

import pytest

from tests import test_conversation_v2 as base
from agent_service.call_errors import ModelCallError
from agent_service.conversation import ConversationHarness
from agent_service.conversation_materials import MaterialFinding, MaterialReadiness
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore
from agent_service.schemas import (
    ConversationOutput, EvidenceAssessmentV2, JDAnalysis, SourceList,
    TeachingPreparation,
)

URL = "https://example.com/synthetic-specification"
ALPHA = "Quantum checksum activation condition: compare the approved scope before activating the operation."
BETA = "Orbital rollback cancellation boundary: reverse only changes that have not been acknowledged."
QUESTION_ALPHA = "Explain the quantum checksum activation condition."
QUESTION_BETA = "Explain the orbital rollback cancellation boundary."
BODY = ("Synthetic background about unrelated ordinary examples.\n" * 240
        + ALPHA + "\n"
        + "Additional unrelated background about ordinary examples.\n" * 80
        + BETA + "\nEnd of the synthetic specification.")


@pytest.fixture
def flow():
    core = base.ConversationTests()
    core.setUp()
    core.harness.judgments = None
    value = SimpleNamespace(core=core, traces=[], search_calls=[], read_calls=[],
                            bodies={URL: BODY}, urls=[URL], fail_answer=False,
                            answer_text="A synthetic explanation grounded in the supplied excerpt.",
                            preparation_query=None)

    def model(system, user, schema, **kwargs):
        payload = json.loads(user)
        value.traces.append((schema.__name__, copy.deepcopy(payload)))
        if issubclass(schema, TeachingPreparation):
            return schema(public_query=value.preparation_query or core.decision.public_search_query,
                **({"verification_claims": [ALPHA]} if "verification_claims" in schema.model_fields else {}))
        if schema is SourceList:
            return SourceList(candidates=[dict(url=u, title="Synthetic specification") for u in value.urls])
        if schema is EvidenceAssessmentV2:
            return EvidenceAssessmentV2(state="supported", summary="Synthetic assessment of the supplied excerpts.",
                sources=[s["url"] for s in payload["sources"] if s.get("content")])
        if schema is MaterialReadiness:
            findings = [MaterialFinding(source_id=s["source_id"],
                role="jd" if payload["kind"] == "jd" else "other", sufficient=True,
                evidence=s["content"][:60]) for s in payload["sources"]
                if s.get("type") == "public_source" and s.get("content")]
            return MaterialReadiness(can_proceed=bool(findings), findings=findings,
                reply="" if findings else "Please supply a readable synthetic source.")
        if issubclass(schema, ConversationOutput):
            if value.fail_answer:
                raise ModelCallError("CONNECTION", "synthetic interrupted answer")
            return ConversationOutput(message=value.answer_text,
                check_question="Which operation must happen first?", learning_concepts=["Operation boundary"],
                check_binding=dict(step_title=(payload.get("learning_step") or {}).get("title", "当前资料讲解"), concepts=["Operation boundary"],
                    evidence_quotes=["A synthetic explanation grounded in the supplied excerpt."], scope="concept"))
        if schema is JDAnalysis:
            return JDAnalysis(role_goal="Synthetic specification reviewer", competency_map=["Scope review"],
                risk_points=["Prior experience is unknown"], prioritized_questions=["How is the scope checked?"])
        return core.model(system, user, schema, **kwargs)

    def search(query, **kwargs):
        value.search_calls.append(query)
        return json.dumps(dict(protocol="harness_web_tools_v1", results=[
            dict(url=u, title="Synthetic specification", snippet="Synthetic source") for u in value.urls]))

    def read(url, **kwargs):
        value.read_calls.append(url)
        return "Synthetic specification", value.bodies[url]

    patches = [
        patch("agent_service.conversation.parse_model", side_effect=model),
        patch("agent_service.conversation.web_search_text", side_effect=search),
        patch("agent_service.conversation.fetch_public_url", side_effect=read),
        patch("agent_service.conditional_teaching.fetch_public_url", side_effect=read),
        patch("agent_service.web_tools.web_context_pages", side_effect=AssertionError("Unexpected web fallback")),
        patch("agent_service.openai_client._client", side_effect=AssertionError("Unexpected real model")),
    ]
    for item in patches:
        item.start()
    try:
        yield value
    finally:
        for item in reversed(patches):
            item.stop()
        core.tearDown()


def calls(flow, schema):
    return [payload for name, payload in flow.traces if name == schema]


def public(payload):
    return [s for s in payload["sources"] if s.get("type") == "public_source"]


def assert_same_packet(left, right):
    left = {s["source_id"]: (s["content"], s["source_selection"]) for s in public(left)}
    right = {s["source_id"]: (s["content"], s["source_selection"]) for s in public(right)}
    assert left == right


def verify(flow, *, teaching=False, question=QUESTION_ALPHA, refresh=False):
    flow.core.decision = base.intent("goal" if teaching else "question",
        workflow="source_learning" if teaching else None, scope="learning" if teaching else "conversation",
        direct_teaching=teaching, needs_verification=True, refresh_sources=refresh,
        public_search_query="public specification")
    result = flow.core.send(question, mode="source_learning" if teaching else "auto")
    assert flow.core.state()["runs"][result.run_id]["status"] == "completed"
    return result


@pytest.mark.parametrize("teaching", [False, True])
def test_tail_fact_is_shared_by_assessment_and_answer_without_extra_calls(flow, teaching):
    assert 10_000 < BODY.index(ALPHA) < BODY.index(BETA) < len(BODY) <= 20_000
    accepted = verify(flow, teaching=teaching)
    assessment = calls(flow, "EvidenceAssessmentV2")[-1]
    answer = calls(flow, "TeachingConversationOutput" if teaching else "ConversationOutput")[-1]
    assert_same_packet(assessment, answer)
    source = public(answer)[0]
    assert ALPHA in source["content"] and len(source["content"]) <= 4_000
    span = source["source_selection"]["ranges"][0]
    assert source["content"] == BODY[span["start"]:span["end"]]
    run = flow.core.state()["runs"][accepted.run_id]
    assert run["source_cache"][URL]["content"] == BODY
    assert next(s for s in run["answer_sources"] if s["url"] == URL)["content"] == BODY
    assert "source_selection" not in run["source_cache"][URL]
    assert answer["evidence"]["state"] == "supported"
    assert len(flow.search_calls) == len(flow.read_calls) == 1
    assert [name for name, _ in flow.traces] == ["IntentDecision", "TeachingPreparation", "SourceList",
        "EvidenceAssessmentV2", "TeachingConversationOutput" if teaching else "ConversationOutput"]


def test_same_question_reuses_binding_but_new_question_reselects_without_verification(flow):
    verify(flow)
    original = public(calls(flow, "ConversationOutput")[-1])[0]
    flow.core.decision = base.intent("followup", public_search_query="public specification")
    repeated = flow.core.send(QUESTION_ALPHA)
    same = calls(flow, "ConversationOutput")[-1]
    assert same["evidence"]["state"] == "supported"
    assert public(same)[0]["source_selection"]["ranges"] == original["source_selection"]["ranges"]
    changed = flow.core.send(QUESTION_BETA)
    answer = calls(flow, "ConversationOutput")[-1]
    selected = public(answer)[0]
    assert BETA in selected["content"] and ALPHA not in selected["content"]
    assert selected["source_selection"]["ranges"] != original["source_selection"]["ranges"]
    assert answer["evidence"]["state"] == "unverified"
    assert answer["evidence"]["selection_changed"] is True
    assert flow.core.state()["runs"][changed.run_id]["teaching_evidence"]["state"] == "unverified"
    assert flow.core.state()["runs"][repeated.run_id]["teaching_evidence"]["state"] == "supported"
    assert len(flow.search_calls) == len(flow.read_calls) == 1
    assert len(calls(flow, "EvidenceAssessmentV2")) == 1


@pytest.mark.parametrize("jd", [False, True])
def test_material_readiness_and_final_analysis_share_the_same_excerpt(flow, jd):
    flow.core.decision = base.intent("material", "goal" if jd else "question",
        workflow="source_learning" if jd else None, scope="learning" if jd else "conversation",
        is_jd=jd, jd_request="analyze" if jd else "none", target_description=QUESTION_ALPHA)
    accepted = flow.core.send(QUESTION_ALPHA + " " + URL)
    readiness = calls(flow, "MaterialReadiness")[-1]
    final = calls(flow, "JDAnalysis" if jd else "ConversationOutput")[-1]
    assert_same_packet(readiness, final)
    assert ALPHA in public(final)[0]["content"]
    run = flow.core.state()["runs"][accepted.run_id]
    assert run["status"] == "completed" and run["source_cache"][URL]["content"] == BODY
    assert len(flow.read_calls) == 1 and flow.search_calls == []
    assert len(calls(flow, "MaterialReadiness")) == 1
    assert len(calls(flow, "JDAnalysis" if jd else "ConversationOutput")) == 1


def test_problem_answer_refreshes_sources_and_excludes_raw_task_source_fields(flow):
    flow.core.decision = base.intent("question", workflow="problem_solving", scope="learning",
        needs_verification=True, public_search_query="public specification")
    accepted = flow.core.send(QUESTION_ALPHA, mode="problem_solving")
    problem = calls(flow, "ProblemCoachBundle")[-1]
    assert_same_packet(calls(flow, "EvidenceAssessmentV2")[-1], problem)
    assert ALPHA in public(problem)[0]["content"]
    assert not {"sources", "source_history", "source_pack"} & set(problem["context"])
    state = flow.core.state()
    assert state["runs"][accepted.run_id]["status"] == "completed"
    assert state["tasks"][state["active_task_id"]]["context"]["sources"][0]["content"] == BODY
    assert len(flow.search_calls) == len(flow.read_calls) == 1


def test_mixed_sources_obey_budget_and_keep_user_material_whole(flow):
    sources = [dict(source_id=f"public-{i}", version=1, type="public_source", url=f"https://example.com/source-{i}",
        title="Synthetic source", content=BODY if i == 3 else ("Irrelevant background.\n" * 900).strip()) for i in range(4)]
    user = dict(source_id="user-source", version=1, type="user_material", url="", title="User material",
                content="Explicit synthetic user constraints.\n" * 600)
    original = copy.deepcopy(sources + [user])
    with flow.core.store.transaction(flow.core.sid) as data:
        data["teaching_context"] = dict(sources=copy.deepcopy(original))
    flow.core.decision = base.intent("followup")
    accepted = flow.core.send(QUESTION_ALPHA)
    answer = calls(flow, "ConversationOutput")[-1]
    projected = public(answer)
    assert sum(len(s["content"]) for s in projected) <= 12_000
    assert all(len(s["content"]) <= 4_000 for s in projected)
    assert ALPHA in next(s for s in projected if s["source_id"] == "public-3")["content"]
    assert next(s for s in answer["sources"] if s["source_id"] == "user-source") == user
    omitted = [s for s in projected if not s["content"]]
    assert omitted and all(s["source_selection"]["reason"] == "budget_exhausted" for s in omitted)
    run = flow.core.state()["runs"][accepted.run_id]
    assert all(s["url"] not in run["allowed_source_urls"] for s in omitted)
    assert run["answer_sources"] == original
    assert flow.search_calls == flow.read_calls == []


def test_refresh_changes_version_hash_and_rebinds_new_assessment(flow):
    first = verify(flow)
    old = public(calls(flow, "ConversationOutput")[-1])[0]
    flow.bodies[URL] = BODY.replace(ALPHA, ALPHA + " The revised requirement is explicit approval.")
    refreshed = verify(flow, refresh=True)
    fresh = calls(flow, "ConversationOutput")[-1]
    source = public(fresh)[0]
    assert source["version"] == old["version"] + 1
    assert source["source_selection"]["content_hash"] != old["source_selection"]["content_hash"]
    assert "explicit approval" in source["content"]
    assert_same_packet(calls(flow, "EvidenceAssessmentV2")[-1], fresh)
    assert fresh["evidence"]["state"] == "supported"
    state = flow.core.state()
    assert state["runs"][first.run_id]["source_cache"][URL]["content"] == BODY
    assert state["runs"][refreshed.run_id]["source_cache"][URL]["content"] == flow.bodies[URL]
    assert len(flow.search_calls) == len(flow.read_calls) == 2


@pytest.mark.parametrize("specific_preparation", [False, True])
def test_failed_answer_snapshot_and_retry_preserve_selection_without_rereading(flow, specific_preparation):
    flow.fail_answer = True
    flow.core.decision = base.intent("question", needs_verification=True, public_search_query="public specification")
    if specific_preparation:
        # The existing preparation call resolves an ambiguous request. A retry
        # may reuse that call's checkpoint, but must also retain its excerpt.
        flow.preparation_query = "quantum checksum activation condition"
    accepted = flow.core.send("Please explain this mechanism." if specific_preparation else QUESTION_ALPHA)
    failed = flow.core.state()["runs"][accepted.run_id]
    assert failed["status"] == "retryable_failed"
    assessed = calls(flow, "EvidenceAssessmentV2")[-1]
    assert ALPHA in public(assessed)[0]["content"]
    snapshot = flow.core.harness.export_snapshot(flow.core.sid)
    before = len(flow.traces)
    with tempfile.TemporaryDirectory(prefix="rt-source-selection-restore-") as directory:
        store = ConversationStore(HarnessStore(str(Path(directory) / "restored.sqlite3")))
        restored = ConversationHarness(store)
        restored.judgments = None
        restored.restore_snapshot(flow.core.sid, snapshot)
        run = store.get(flow.core.sid)["runs"][accepted.run_id]
        assert run["source_selection_packet"] == failed["source_selection_packet"]
        assert run["source_selection_records"] == failed["source_selection_records"]
        assert len(flow.traces) == before and len(flow.read_calls) == 1
        flow.fail_answer = False
        restored.action(accepted.run_id, base.RunActionRequest(action_id=str(base.uuid.uuid4()), action="retry"))
        restored.drain(flow.core.sid)
        final = store.get(flow.core.sid)["runs"][accepted.run_id]
        assert final["status"] == "completed" and final["revision"] > failed["revision"]
        assert final["source_cache"][URL]["content"] == BODY
        assert final["source_selection_packet"]["revision"] == final["revision"]
    assert_same_packet(assessed, calls(flow, "ConversationOutput")[-1])
    assert ALPHA in public(calls(flow, "ConversationOutput")[-1])[0]["content"]
    assert calls(flow, "ConversationOutput")[-1]["evidence"]["state"] == "supported"
    assert len(flow.search_calls) == len(flow.read_calls) == 1
    assert len(calls(flow, "EvidenceAssessmentV2")) == 1


def test_legacy_supported_evidence_without_selection_is_not_promoted(flow):
    verify(flow)
    with flow.core.store.transaction(flow.core.sid) as data:
        data["teaching_context"]["evidence"].pop("source_selection")
    flow.core.decision = base.intent("followup", public_search_query="public specification")
    flow.core.send(QUESTION_ALPHA)
    answer = calls(flow, "ConversationOutput")[-1]
    assert answer["evidence"]["state"] == "unverified"
    assert ALPHA in public(answer)[0]["content"]
    assert len(flow.search_calls) == len(flow.read_calls) == 1


def test_material_budget_is_frozen_when_verification_adds_a_page_and_blocks_its_citation(flow):
    material_urls = [f"https://example.com/supplied-{i}" for i in range(3)]
    flow.bodies.update({url: "Unrelated supplied background.\n" * 250 for url in material_urls})
    flow.answer_text += f" [Unseen source]({URL})"
    flow.core.decision = base.intent("material", "question", scope="conversation",
        needs_verification=True, public_search_query="public specification")
    accepted = flow.core.send(QUESTION_ALPHA + " " + " ".join(material_urls))
    readiness = calls(flow, "MaterialReadiness")[-1]
    assessment = calls(flow, "EvidenceAssessmentV2")[-1]
    answer = calls(flow, "ConversationOutput")[-1]
    final_by_url = {s["url"]: s for s in public(answer)}
    for selected in public(readiness):
        actual = final_by_url[selected["url"]]
        assert actual["content"] == selected["content"]
        assert actual["source_selection"] == selected["source_selection"]
    omitted = final_by_url[URL]
    assert omitted["content"] == ""
    assert omitted["source_selection"]["reason"] == "budget_exhausted"
    assert public(assessment)[0]["content"] == ""
    assert public(assessment)[0]["source_selection"] == omitted["source_selection"]
    assert answer["evidence"]["state"] == "insufficient"
    assert sum(len(s["content"]) for s in public(answer)) == 12_000
    state = flow.core.state()
    run = state["runs"][accepted.run_id]
    assert run["source_cache"][URL]["content"] == BODY
    assert URL not in run["allowed_source_urls"]
    assert URL not in [m for m in state["messages"] if m["role"] == "coach"][-1]["content"]
    assert len(flow.search_calls) == 1 and len(flow.read_calls) == 4
    assert len(calls(flow, "MaterialReadiness")) == len(calls(flow, "EvidenceAssessmentV2")) == 1


def test_jev_claim_assessment_receives_the_same_selected_source_as_the_final_answer(flow):
    import httpx
    from agent_service.jev_client import JevClient
    from agent_service.judgments import JudgmentEngine
    from agent_service.judgment_types import MODEL

    requests = []

    def response(request):
        payload = json.loads(request.content)
        requests.append(copy.deepcopy(payload))
        answers = {}
        for name, question in payload["questions"].items():
            criteria = question["criteria"]
            choice = next((label for label in ("supported", "relevant", "other") if label in criteria), "unsure")
            answers[name] = dict(type="choice", choice=choice, confidence=1.0,
                probabilities={label: float(label == choice) for label in criteria})
        return httpx.Response(200, json=dict(model=MODEL, answers=answers))

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        flow.core.harness.judgments = JudgmentEngine(JevClient("synthetic-key", client=http))
        accepted = verify(flow, question=ALPHA)
    assessment = next(p["state"] for p in requests if "pages" in p["state"])
    answer = calls(flow, "ConversationOutput")[-1]
    assert_same_packet(dict(sources=assessment["pages"]), answer)
    assert ALPHA in public(answer)[0]["content"]
    assert answer["evidence"]["state"] == "scoped"
    assert calls(flow, "EvidenceAssessmentV2") == []
    assert calls(flow, "SourceList") == []
    assert [name for name, _ in flow.traces] == ["IntentDecision", "TeachingPreparationWithClaims", "ConversationOutput"]
    run = flow.core.state()["runs"][accepted.run_id]
    assert run["status"] == "completed"
    assert any(j["node"] == "evidence_assessment" and j["applied"] for j in run["judgments"])
    assert len(requests) == 3 and len(flow.search_calls) == len(flow.read_calls) == 1


@pytest.mark.parametrize("duplicate", ["same_object", "same_version_new_body", "new_version"])
def test_real_run_packet_deduplicates_repeated_or_replaced_source_identity(flow, duplicate):
    source = dict(source_id="same-source", version=1, type="public_source", url=URL,
                  title="Synthetic specification", content=BODY)
    if duplicate == "same_object":
        supplied = [source, source]
        assert supplied[0] is supplied[1]
        expected = source
    else:
        expected = dict(source, version=2 if duplicate == "new_version" else 1,
            content=BODY.replace(ALPHA, ALPHA + " The replacement requires an explicit scope receipt."))
        supplied = [source, expected]
    # JSON checkpointing represents object aliases as repeated source records.
    # Observe their real per-run packet and final prompt, not a pure projection.
    with flow.core.store.transaction(flow.core.sid) as data:
        data["teaching_context"] = dict(sources=copy.deepcopy(supplied))
    flow.core.decision = base.intent("followup")
    accepted = flow.core.send(QUESTION_ALPHA)
    run = flow.core.state()["runs"][accepted.run_id]
    assert run["status"] == "completed"
    answer = calls(flow, "ConversationOutput")[-1]
    projected = public(answer)
    assert len(projected) == len(run["source_selection_packet"]["entries"]) == 1
    assert projected[0]["version"] == expected["version"]
    span = projected[0]["source_selection"]["ranges"][0]
    assert projected[0]["content"] == expected["content"][span["start"]:span["end"]]
    if duplicate != "same_object":
        assert "explicit scope receipt" in projected[0]["content"]
    assert sum(entry["selection"]["projected_chars"]
               for entry in run["source_selection_packet"]["entries"].values()) <= 12_000
    assert len(run["answer_sources"]) == 1
    assert run["answer_sources"][0]["content"] == expected["content"]
    assert flow.search_calls == flow.read_calls == []


def test_new_question_cannot_borrow_supported_evidence_through_teaching_task_context(flow):
    verify(flow, teaching=True)
    before = flow.core.state()
    task_id = before["active_task_id"]
    assert before["tasks"][task_id]["context"]["evidence"]["state"] == "supported"
    assert calls(flow, "TeachingPreparation")[-1]["previous_concepts"] == []
    flow.core.decision = base.intent("followup", public_search_query="public specification")
    changed = flow.core.send(QUESTION_BETA)
    answer = calls(flow, "ConversationOutput")[-1]
    assert BETA in public(answer)[0]["content"] and ALPHA not in public(answer)[0]["content"]
    assert answer["evidence"]["state"] == "unverified"
    assert answer["context"]["task"]["context"]["evidence"]["state"] == "unverified"
    after = flow.core.state()
    assert after["tasks"][task_id]["context"]["evidence"]["state"] == "unverified"
    assert after["runs"][changed.run_id]["teaching_evidence"]["state"] == "unverified"
    assert len(flow.search_calls) == len(flow.read_calls) == 1
    assert len(calls(flow, "EvidenceAssessmentV2")) == 1


def test_real_supplement_changes_same_run_packet_instead_of_freezing_retry_excerpt(flow):
    flow.preparation_query = "quantum checksum activation condition"
    flow.fail_answer = True
    flow.core.decision = base.intent("question", needs_verification=True, public_search_query="public specification")
    original = flow.core.send("Please explain this mechanism.")
    before = flow.core.state()["runs"][original.run_id]
    assert before["status"] == "retryable_failed"
    assert ALPHA in public(calls(flow, "EvidenceAssessmentV2")[-1])[0]["content"]
    # Retry accepts the old run; an actual steer message then supplies a new
    # input ID before execution, exercising the normal accept/merge boundary.
    flow.core.harness.action(original.run_id,
        base.RunActionRequest(action_id=str(base.uuid.uuid4()), action="retry"))
    flow.preparation_query = "orbital rollback cancellation boundary"
    flow.fail_answer = False
    flow.core.decision = base.intent("followup", public_search_query="public specification")
    supplement = flow.core.send(QUESTION_BETA, delivery="steer")
    assert supplement.run_id == original.run_id
    after = flow.core.state()["runs"][original.run_id]
    assert after["status"] == "completed" and after["revision"] > before["revision"]
    assert len(after["input_ids"]) == 2
    packet = after["source_selection_packet"]
    assert packet["input_signature"] != before["source_selection_packet"]["input_signature"]
    assert packet["query"] != before["source_selection_packet"]["query"]
    answer = calls(flow, "ConversationOutput")[-1]
    assert BETA in public(answer)[0]["content"] and ALPHA not in public(answer)[0]["content"]
    assert answer["evidence"]["state"] == "unverified"
    assert len(flow.search_calls) == len(flow.read_calls) == 1
    assert len(calls(flow, "EvidenceAssessmentV2")) == 1
