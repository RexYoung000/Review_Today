"""Conservative local input accounting; critical state is never silently trimmed."""
import json
import math
import os
from copy import deepcopy

INPUT_LIMIT = 256_000
COMPACT_AT = 220_000
COMPACT_TARGET = 144_000
OUTPUT_RESERVE = 4096


def policy(window=None, reserve=OUTPUT_RESERVE, local_limit=None):
    limit = INPUT_LIMIT if local_limit is None else local_limit
    limit = min(limit, window - reserve) if window else limit
    if limit <= 0:
        raise ValueError("RT.CONTEXT.NO_INPUT_BUDGET")
    return limit, int(limit * COMPACT_AT / INPUT_LIMIT), int(limit * COMPACT_TARGET / INPUT_LIMIT)


def count_request(system, prompt, schema=None):
    envelope = json.dumps(schema, ensure_ascii=False) if schema else ""
    return estimate(system + prompt + envelope + "developer user structured_output")


def estimate(text):
    # No remote tokenizer or undocumented model window assumption. This is an
    # explicitly approximate, conservative mixed Chinese/English byte estimate.
    return math.ceil(len(text.encode("utf-8")) / 2)


def prepare(system, prompt, *, window=None, reserve=OUTPUT_RESERVE, local_limit=None, schema=None):
    limit, threshold, target = policy(window, reserve, local_limit)
    try:
        payload = json.loads(prompt)
    except (ValueError, TypeError):
        payload = None
    payload = deepcopy(payload)
    removed = []
    current = prompt
    envelope = json.dumps(schema, ensure_ascii=False) if schema else ""
    envelope += "developer user structured_output"  # conservative framing allowance
    context = payload.get("context", payload) if isinstance(payload, dict) else None
    if isinstance(context, dict):
        # These are narrative conveniences, not the authoritative current input,
        # constraints, goal, confirmation object/version or learning state.
        # History must be compacted transactionally before this final guard. Never
        # silently drop unsummarized turns or the only remaining handoff summary.
        for field in ("memory_candidates", "related_knowledge"):
            while estimate(system + current + envelope) > limit and context.get(field):
                value = context[field]
                if isinstance(value, list):
                    context[field] = value[1:] if field == "recent_messages" else value[:-1]
                else:
                    context[field] = ""
                if field not in removed: removed.append(field)
                context["omitted_narrative"] = removed
                current = json.dumps(payload, ensure_ascii=False)
    count = estimate(system + current + envelope)
    if count > limit:
        raise ValueError("RT.CONTEXT.INPUT_TOO_LARGE")
    return current, dict(estimated=True, input_tokens=count, input_budget=limit,
                         compact_threshold=threshold, compact_target=target,
                         ratio=count / limit, output_reserve=reserve, model_window=window,
                         budget_source="local_limit" if not window or limit < window - reserve else "model_window",
                         omitted_narrative=removed)


def configured_window(model=None):
    from agent_service.config import PROVIDER, MODEL
    name = "DEEPSEEK_CONTEXT_WINDOW" if PROVIDER == "deepseek" else "OPENAI_CONTEXT_WINDOW"
    raw = os.getenv(name, "")
    if raw:
        return int(raw) if raw.isdigit() and int(raw) > 4096 else None
    # Official model table checked 2026-09-10. Unknown names stay unknown.
    # https://api-docs.deepseek.com/quick_start/pricing/
    if PROVIDER == "deepseek" and (model or MODEL) in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"}:
        return 1_000_000
    return None
