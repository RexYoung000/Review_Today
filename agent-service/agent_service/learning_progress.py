"""Deterministic learning evidence. Display progress is never write authority."""
import uuid


def set_plan(task, titles, success_check=""):
    old = task["context"].get("learning_plan") or {}
    old_steps = {s["title"]: s for s in old.get("steps", [])}
    titles = list(dict.fromkeys(titles))[:10]
    steps = [old_steps.get(title) or dict(
        id=str(uuid.uuid5(uuid.UUID(task["task_id"]), title)), title=title,
        state="pending", understanding="unknown", message_ids=[], completion_condition=success_check
    ) for title in titles]
    unchanged = [s["title"] for s in old.get("steps", [])] == titles
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
