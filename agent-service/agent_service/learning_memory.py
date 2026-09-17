"""Learning evidence is a typed observation, not mastery or save permission."""
from agent_service.harness_store import now_iso


def merge_references(*groups):
    result, seen = [], set()
    for refs in groups:
        for ref in refs:
            key = (ref.get("id"), ref.get("content_version"), ref.get("policy_version"))
            if key not in seen:
                seen.add(key)
                result.append(ref)
    return result


def make_evidence(run, task, message_id, text, sid):
    if run.get('dialogue_only') or (run.get('intent') or {}).get('resource_boundary', 'none') in {'resource_delivery', 'capability_question'}:
        return None
    intent = run.get("intent") or {}
    intents = set(intent.get("intents", []))
    if run.get("status") != "completed" or not (run.get("activity_candidate") in {"knowledge_answer", "lesson_step"}
                                               or task and intents & {"answer", "self_report", "skip_check"}):
        return None
    ctx = (task or {}).get("context", {})
    plan = ctx.get("learning_plan") or {}
    step_id = run.get("evaluated_step_id") or plan.get("current_step_id")
    step = next((s for s in plan.get("steps", []) if s["id"] == step_id), {})
    practice = ctx.get("practice", [])
    hint = bool(ctx.get("hint_used") or intents & {"hint", "example"} or "answer" in intents and practice and practice[-1].get("hint_used"))
    kind = "explained"
    if "answer" in intents and not hint and ctx.get("practice") and ctx["practice"][-1].get("evaluation", {}).get("passed"):
        kind = "independently_verified"
    elif intent.get("understanding") == "self_reported":
        kind = "self_reported"
    elif "skip_check" in intents:
        kind = "skipped_check"
    return dict(id=message_id, session_id=sid, run_id=run["run_id"], message_id=message_id,
                task_id=(task or {}).get("task_id"), step_id=step.get("id"),
                concept=step.get("title") or (task or {}).get("content") or intent.get("target_description") or text[:80],
                concepts=run.get("learning_concepts", []), kind=kind, hint_used=hint,
                excerpt=text[:1600], source_ids=[s["source_id"] for s in ctx.get("sources", []) if s.get("source_id")],
                evidence_message_ids=run.get("input_ids", []) if "answer" in intents else [message_id],
                dependencies=run.get("memory_references", []), occurred_at=now_iso(), revision=run.get("revision", 1))


def select_references(candidates, selections):
    available = {value["id"]: value for value in candidates if isinstance(value.get("id"), str) and value["id"]}
    result, seen = [], set()
    for selection in selections:
        identity = selection.get("id")
        if identity not in available or identity in seen or selection.get("relation") not in {"prerequisite", "analogy", "contrast", "transfer"}:
            continue
        seen.add(identity)
        result.append(dict(available[identity], relation=selection["relation"]))
        if len(result) == 2:
            break
    return result
