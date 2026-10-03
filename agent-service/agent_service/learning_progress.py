"""Deterministic learning evidence. Display progress is never write authority."""
import hashlib
import re
import uuid
from copy import deepcopy


def set_plan(task, titles, success_check="", step_ids=None, *, step_conditions=None):
    old = task["context"].get("learning_plan") or {}
    old_steps = {s["title"]: s for s in old.get("steps", [])}
    by_id = {s["id"]: s for s in old.get("steps", [])}
    conditions = step_conditions or []
    if conditions and (len(conditions) != len(titles)
                       or any(not isinstance(condition, str) or not condition.strip() for condition in conditions)):
        raise ValueError("RT.PLAN.INVALID_STEP_CONDITIONS")
    step_ids = step_ids or [""] * len(titles)
    if not by_id and len(step_ids) == len(titles):
        # There is no prior evidence to inherit on first creation. Model-generated
        # identifiers are suggestions only; runtime owns all new stable IDs.
        step_ids = [""] * len(titles)
    explicit = [value for value in step_ids if value]
    if len(step_ids) != len(titles) or len(set(explicit)) != len(explicit) or any(value not in by_id for value in explicit):
        raise ValueError("RT.PLAN.INVALID_STEP_REFERENCE")
    steps, seen = [], set()
    for index, (title, identity) in enumerate(zip(titles, step_ids)):
        if not title.strip() or title in seen or len(steps) == 10:
            continue
        seen.add(title)
        prior = by_id.get(identity) if identity else old_steps.get(title)
        step = deepcopy(prior) if prior else dict(
            id=str(uuid.uuid4()), state="pending", understanding="unknown", message_ids=[], completion_condition="")
        if any(s["id"] == step["id"] for s in steps):
            raise ValueError("RT.PLAN.INVALID_STEP_REFERENCE")
        step["title"] = title
        if conditions:
            step["completion_condition"] = conditions[index]
        steps.append(step)
    unchanged = [(s["id"], s["title"], s.get("completion_condition", "")) for s in old.get("steps", [])] == [
        (s["id"], s["title"], s.get("completion_condition", "")) for s in steps]
    task["context"]["learning_plan"] = dict(
        id=task["context"].get("goal_ownership", {}).get("goal_id", task["task_id"]), version=old.get("version", 0) + (0 if unchanged else 1),
        goal=task["context"].get("learning_goal") or task["content"], steps=steps,
        current_step_id=old.get("current_step_id") if any(s["id"] == old.get("current_step_id") for s in steps) else (steps[0]["id"] if steps else None),
        success_check=success_check or old.get("success_check", ""))
    return task["context"]["learning_plan"]


def current_step(task):
    plan = task["context"].get("learning_plan") or {}
    return next((s for s in plan.get("steps", []) if s["id"] == plan.get("current_step_id")), None)


def step_target(task):
    """Project the current objective without promoting legacy global placeholders."""
    step = current_step(task)
    if not step:
        return None
    target = {key: step.get(key, "") for key in ("id", "title", "completion_condition")}
    plan = task["context"].get("learning_plan") or {}
    if len(plan.get("steps", [])) > 1 and all(
            item.get("completion_condition") == plan.get("success_check") for item in plan["steps"]):
        target["completion_condition"] = ""
    return target


def record_understanding(task, understanding, skipped=False):
    step = current_step(task)
    if step:
        step["understanding"] = understanding
        step["state"] = "verified" if understanding == "verified" else "skipped" if skipped else "explained"


def check_reference(task):
    ctx = task["context"]
    if ctx.get("requires_mastery"):
        return "\n\n".join(dict.fromkeys(part for part in
            (ctx.get("reference_answer", ""), ctx.get("last_lesson", "")) if part and part.strip()))
    return ctx.get("last_lesson") or ctx.get("reference_answer") or ""


def _reference_stamp(task):
    return hashlib.sha256(check_reference(task).encode()).hexdigest()


def _visible_quote(text):
    """Ignore paired inline display markers, preserving words, numbers and punctuation."""
    # Models often quote rendered prose without its emphasis/code delimiters.
    # Do not normalize synonyms, punctuation, spacing or sentence order.
    for pattern in (r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"(`+)([^`]+)\1"):
        text = re.sub(pattern, lambda match: match[2], text)
    return text


def bind_check(task, question, proposal, taught_concepts=None):
    """Freeze only an explicit, locally grounded scope; never infer it from an answer."""
    ctx = task["context"]
    ctx.pop("check_binding", None)
    step = current_step(task)
    if not question or proposal is None or not step:
        return None
    value = proposal.model_dump() if hasattr(proposal, "model_dump") else dict(proposal)
    concepts = list(dict.fromkeys(c.strip() for c in value.get("concepts", []) if c.strip()))
    quotes = [q.strip() for q in value.get("evidence_quotes", []) if q.strip()]
    reference = check_reference(task)
    if (value.get("step_title") != step["title"] or not concepts or not quotes or
            any(_visible_quote(quote) not in _visible_quote(reference) for quote in quotes) or
            taught_concepts is not None and not set(concepts).issubset(taught_concepts)):
        return None
    # A missing/legacy global condition cannot certify an entire local step.
    scope = value.get("scope", "concept")
    if scope == "step" and not (step_target(task) or {}).get("completion_condition"):
        scope = "concept"
    binding = dict(question=question, step_id=step["id"], step_title=step["title"], concepts=concepts,
                   evidence_quotes=quotes, scope=scope, reference_stamp=_reference_stamp(task),
                   plan_version=(ctx.get("learning_plan") or {}).get("version", 0),
                   completion_condition=step.get("completion_condition", "") if scope == "step" else "")
    ctx["check_binding"] = binding
    return binding


def bound_check(task):
    ctx = task["context"]
    binding = ctx.get("check_binding")
    step = current_step(task)
    if not binding and step and ctx.get("check_standard"):
        # Jev already freezes and validates the rubric before the answer. Use
        # that existing contract; never manufacture a rubric for an old answer.
        from agent_service.judgment_grading import standard_for
        spec = standard_for(task, ctx.get("check_question", ""))
        if spec is not None:
            binding = bind_check(deepcopy(task), ctx["check_question"], dict(
                step_title=step["title"], concepts=spec.must_cover,
                evidence_quotes=[check_reference(task)], scope="concept"))
    if (not binding or not step or binding.get("question") != ctx.get("check_question") or
            binding.get("step_id") != step["id"] or binding.get("step_title") != step["title"] or
            binding.get("reference_stamp") != _reference_stamp(task) or
            binding.get("plan_version") != (ctx.get("learning_plan") or {}).get("version", 0)):
        return None
    return deepcopy(binding)


def record_check(task, binding, message_id, *, step_completion_demonstrated=False):
    """A small check proves its named concepts, not every capability in a chapter."""
    if not binding:
        return
    plan = task["context"].get("learning_plan") or {}
    step = next((s for s in plan.get("steps", []) if s["id"] == binding["step_id"]), None)
    if not step:
        return
    evidence = step.setdefault("verified_concepts", [])
    for concept in binding["concepts"]:
        if not any(item["concept"] == concept and item["message_id"] == message_id for item in evidence):
            evidence.append(dict(concept=concept, message_id=message_id, question=binding["question"]))
    if binding["scope"] == "step" and binding.get("completion_condition") and step_completion_demonstrated:
        step.update(state="verified", understanding="verified")


def mastery_material(task, runs, current_run_id, valid_run):
    """Freeze verified-scope feedback into the first delivered mastery draft."""
    ctx = task["context"]
    base = ctx.get("reference_answer") or ctx.get("last_lesson") or task["content"]
    plan = ctx.get("learning_plan") or {}
    steps = {step["id"]: step for step in plan.get("steps", [])}
    feedback, source_runs = [], []
    for entry in ctx.get("practice", []):
        run = runs.get(entry.get("run_id"), {})
        binding = entry.get("binding") or {}
        step = steps.get(binding.get("step_id"), {})
        if (not binding or binding.get("plan_version") != plan.get("version") or
                not step or binding.get("step_title") != step.get("title") or
                run.get("task_id") != task["task_id"] or run.get("evaluated_binding") != binding or
                entry.get("revision") != run.get("revision") or
                run.get("evaluation_message_id") != entry.get("message_id") or
                entry.get("message_id") not in run.get("input_ids", []) or not valid_run(run) or
                not (run.get("status") == "completed" or
                     run.get("run_id") == current_run_id and run.get("status") == "running")):
            continue
        text = entry.get("evaluation", {}).get("feedback", "").strip()
        if text and text not in feedback:
            feedback.append(text)
            source_runs.append(run["run_id"])
    if feedback:
        base += "\n\n答题反馈中的解释与纠正（只整理知识补充，不把用户作答或评分描述当作知识事实）：\n" + "\n\n".join(feedback)
    return base, source_runs


def advance(task):
    plan = task["context"].get("learning_plan")
    step = current_step(task)
    if not plan or not step or step["state"] == "pending":
        return False
    index = plan["steps"].index(step)
    if index + 1 < len(plan["steps"]):
        plan["current_step_id"] = plan["steps"][index + 1]["id"]
        return False
    return True


def outcome(task):
    plan = task["context"].get("learning_plan") or {}
    verified = [s["title"] for s in plan.get("steps", []) if s["understanding"] == "verified"]
    explained = [s["title"] for s in plan.get("steps", []) if s["state"] != "pending" and s["understanding"] != "verified"]
    return dict(goal=plan.get("goal", task["content"]), verified=verified, explained=explained,
                needs_practice=explained, memory_status="not_saved", understanding=task["context"].get("understanding", "unknown"))
