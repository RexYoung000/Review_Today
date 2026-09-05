"""Deterministic learning evidence. Display progress is never write authority."""
import uuid
from copy import deepcopy


def set_plan(task, titles, success_check="", step_ids=None):
    old = task["context"].get("learning_plan") or {}
    old_steps = {s["title"]: s for s in old.get("steps", [])}
    by_id = {s["id"]: s for s in old.get("steps", [])}
    step_ids = step_ids or [""] * len(titles)
    if not by_id and len(step_ids) == len(titles):
        # There is no prior evidence to inherit on first creation. Model-generated
        # identifiers are suggestions only; runtime owns all new stable IDs.
        step_ids = [""] * len(titles)
    explicit = [value for value in step_ids if value]
    if len(step_ids) != len(titles) or len(set(explicit)) != len(explicit) or any(value not in by_id for value in explicit):
        raise ValueError("RT.PLAN.INVALID_STEP_REFERENCE")
    steps, seen = [], set()
    for title, identity in zip(titles, step_ids):
        if not title.strip() or title in seen or len(steps) == 10:
            continue
        seen.add(title)
        prior = by_id.get(identity) if identity else old_steps.get(title)
        step = deepcopy(prior) if prior else dict(
            id=str(uuid.uuid4()), state="pending", understanding="unknown", message_ids=[], completion_condition=success_check)
        if any(s["id"] == step["id"] for s in steps):
            raise ValueError("RT.PLAN.INVALID_STEP_REFERENCE")
        step["title"] = title
        steps.append(step)
    unchanged = [(s["id"], s["title"]) for s in old.get("steps", [])] == [(s["id"], s["title"]) for s in steps]
    task["context"]["learning_plan"] = dict(
        id=task["task_id"], version=old.get("version", 0) + (0 if unchanged else 1),
        goal=task["context"].get("learning_goal") or task["content"], steps=steps,
        current_step_id=old.get("current_step_id") if any(s["id"] == old.get("current_step_id") for s in steps) else (steps[0]["id"] if steps else None),
        success_check=success_check or old.get("success_check", ""))
    return task["context"]["learning_plan"]


def current_step(task):
    plan = task["context"].get("learning_plan") or {}
    return next((s for s in plan.get("steps", []) if s["id"] == plan.get("current_step_id")), None)


def record_understanding(task, understanding, skipped=False):
    step = current_step(task)
    if step:
        step["understanding"] = understanding
        step["state"] = "verified" if understanding == "verified" else "skipped" if skipped else "explained"


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
