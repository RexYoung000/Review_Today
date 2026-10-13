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


def quote_matches(quote, reference):
    """Accept exact raw excerpts or identical rendered words; never paraphrases."""
    return bool(quote.strip() and (quote in reference or _visible_quote(quote) in _visible_quote(reference)))


CHECK_SCOPE_POLICY = "explicit-comprehensive-1"


def completion_requirements(condition):
    """Keep the full condition plus its literal, explicitly enumerated details."""
    items = [condition]
    for group in re.findall(r"[（(]([^（）()]+)[）)]", condition):
        # Examples and optional alternatives are not additional pass conditions.
        if "、" in group and not re.search(r"例如|比如|如：|如:|可选|任选|或|等", group):
            items.extend(part.strip() for part in group.split("、") if part.strip())
    return list(dict.fromkeys(items))


def comprehensive_bound(binding):
    return bool(binding and binding.get("scope") == "step"
        and binding.get("check_kind") == "comprehensive"
        and binding.get("scope_policy") == CHECK_SCOPE_POLICY
        and binding.get("request_message_id") and binding.get("request_run_id")
        and binding.get("completion_condition", "").strip()
        and binding["completion_condition"] in binding.get("question", "")
        and binding.get("completion_requirements") == completion_requirements(binding["completion_condition"]))


def binding_for_model(binding, reference):
    """Locate rendered binding excerpts in raw Markdown before model selection.

    This changes only the request projection. Saved bindings and literal capture
    validation retain their original contracts; words and punctuation stay exact.
    """
    if not binding:
        return None
    visible, offsets = reference, list(range(len(reference)))
    for pattern in (r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"(`+)([^`]+)\1"):
        chunks, positions, cursor = [], [], 0
        for match in re.finditer(pattern, visible):
            chunks.extend([visible[cursor:match.start()], match[2]])
            positions.extend(offsets[cursor:match.start()] + offsets[match.start(2):match.end(2)])
            cursor = match.end()
        chunks.append(visible[cursor:])
        positions.extend(offsets[cursor:])
        visible, offsets = "".join(chunks), positions
    result = deepcopy(binding)
    for index, quote in enumerate(result["evidence_quotes"]):
        rendered = _visible_quote(quote)
        start = visible.find(rendered)
        if quote not in reference and rendered and start >= 0:
            left, right = offsets[start], offsets[start + len(rendered) - 1] + 1
            for pattern in (r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"(`+)([^`]+)\1"):
                for marker in re.finditer(pattern, reference):
                    if left <= marker.start(2) and right >= marker.end(2):
                        left, right = min(left, marker.start()), max(right, marker.end())
            result["evidence_quotes"][index] = reference[left:right]
    return result


def guard_completion(result, binding, answer):
    """A model's whole-step flag requires every frozen item and learner quotes."""
    if not comprehensive_bound(binding):
        result.step_completion_demonstrated = False
        return
    rows = [row.model_dump() if hasattr(row, "model_dump") else row
            for row in result.step_completion_evidence]
    expected = set(range(len(binding["completion_requirements"])))
    proof = (len(rows) == len(expected) and {r["requirement_index"] for r in rows} == expected
        and all(r["demonstrated"] and r["answer_quotes"]
                and all(q.strip() and q in answer for q in r["answer_quotes"]) for r in rows))
    result.step_completion_demonstrated = bool(result.step_completion_demonstrated and proof
                                               and getattr(result, "passed", True))
    if getattr(result, "passed", False) and not result.step_completion_demonstrated:
        result.passed = False
        result.feedback = "这次还不能确认本节完整通过。请用自己的话逐项说明题面要求；已通过的小题记录保留。"
        # The old positive feedback is no longer a source for an invitation.
        result.capture_feedback_quotes = []
        result.capture_preview = None
        result.capture_scope_summary = ""


def bind_check(task, question, proposal, taught_concepts=None, *, comprehensive=False):
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
            any(not quote_matches(quote, reference) for quote in quotes) or
            taught_concepts is not None and not set(concepts).issubset(taught_concepts)):
        return None
    # A missing/legacy global condition cannot certify an entire local step.
    scope = ("step" if comprehensive and value.get("scope") == "step"
             and (step_target(task) or {}).get("completion_condition") else "concept")
    binding = dict(question=question, step_id=step["id"], step_title=step["title"], concepts=concepts,
                   evidence_quotes=quotes, scope=scope, reference_stamp=_reference_stamp(task),
                   plan_version=(ctx.get("learning_plan") or {}).get("version", 0),
                   completion_condition=step.get("completion_condition", "") if scope == "step" else "",
                   completion_requirements=completion_requirements(step["completion_condition"]) if scope == "step" else [],
                   check_kind="comprehensive" if scope == "step" else "concept",
                   scope_policy=CHECK_SCOPE_POLICY)
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
            if binding:
                # This reference validates grading, but is not a knowledge-point
                # excerpt. An invitation needs separately validated capture quotes.
                binding["scope_source"] = "rubric_fallback"
    if (not binding or not step or binding.get("question") != ctx.get("check_question") or
            binding.get("step_id") != step["id"] or binding.get("step_title") != step["title"] or
            binding.get("reference_stamp") != _reference_stamp(task) or
            binding.get("plan_version") != (ctx.get("learning_plan") or {}).get("version", 0)):
        return None
    projected = deepcopy(binding)
    if projected.get("scope") == "step":
        if not comprehensive_bound(projected):
            # Legacy pending checks remain readable; their label cannot grant
            # whole-step progress under the current policy. Do not rewrite history.
            projected.update(scope="concept", completion_condition="", check_kind="concept")
        elif projected["completion_condition"] != step.get("completion_condition", ""):
            return None
    return projected


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
    if comprehensive_bound(binding) and step_completion_demonstrated:
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
