"""One trial per process. No service imports before temporary DB isolation."""

from __future__ import annotations
import argparse
import copy
from datetime import datetime
import os
import tempfile
import time
import uuid
import traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from evals.core import check_rules, classify, load_dataset, write_json
from evals.instrument import Meter


def state_view(data):
    tasks = []
    for t in data["tasks"].values():
        ctx = t.get("context", {})
        tasks.append(
            dict(
                id=t["task_id"],
                mode=t["mode"],
                status=t["status"],
                stage=t["stage"],
                understanding=ctx.get("understanding", "unknown"),
                transfer_passed=bool(ctx.get("transfer_passed")),
                steps=(ctx.get("learning_plan") or {}).get("steps", []),
                commit_claimed=bool(ctx.get("commit_claimed")),
                source_type=ctx.get("source_type"),
                required_action=t.get("required_action"),
            )
        )
    return dict(
        mode=data["mode"],
        paused=data["paused"],
        tasks=tasks,
        draft=data.get("draft"),
        pending=data.get("pending"),
        commit_packages=[
            t["memory_package"]
            for t in data["tasks"].values()
            if t.get("memory_package")
        ],
        memory_references=[
            r for run in data["runs"].values() for r in run.get("memory_references", [])
        ],
        learning_evidence=[
            e["payload"]["learning_evidence"]
            for e in data["events"]
            if e.get("payload", {}).get("learning_evidence")
        ],
    )


def execute(case, references, rubric, args, directory):
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "checkpoint.sqlite3")
    from dotenv import load_dotenv

    for env in args.env_file:
        load_dotenv(env, override=False)
    os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "checkpoint.sqlite3")
    from agent_service import config, conversation, conditional_teaching, openai_client
    from agent_service.conversation_store import ConversationStore
    from agent_service.harness_store import HarnessStore
    from agent_service.schemas import SessionMessageRequest, RunActionRequest
    from evals.judge import grade

    if (
        Path(config.HARNESS_DB).resolve()
        != Path(os.environ["REVIEW_TODAY_HARNESS_DB"]).resolve()
    ):
        raise RuntimeError("EVAL.ISOLATION_FAILED")
    if config.PROVIDER != "deepseek":
        raise RuntimeError("EVAL.PROVIDER_MUST_BE_EXISTING_DEEPSEEK")
    if not config.openai_key():
        raise RuntimeError("EVAL.NO_KEY")
    result = dict(
        trial_key=args.trial_key,
        case_id=case["id"],
        schema_version=case.get("schema_version", 1),
        case_contract=case,
        domain=case.get("domain"),
        mode=case["mode"],
        turns=[],
        tools=[],
        checks=[],
        judge=None,
        model_roles=dict(
            router=config.ROUTER_MODEL,
            coach=config.COACH_MODEL,
            risk=config.RISK_MODEL,
            judge=config.RISK_MODEL,
        ),
        provider=config.PROVIDER,
        thinking="smart",
        environment=args.environment,
        synthetic=True,
        grading=case.get("grading", "hybrid"),
        status="not_run",
        execution_error=None,
        judge_error=None,
        scope="service_harness; simulated Mac ACK only; no native persistence or FSRS",
    )
    started = time.monotonic()
    meter = Meter(args.max_calls)

    def save():
        result["calls"] = meter.calls
        result["total_ms"] = round((time.monotonic() - started) * 1000)
        write_json(args.output, result)

    meter.on_change = save
    tool_log = result["tools"]
    turn_number = 0
    original_search = conversation.web_search_text
    original_fetch = conversation.fetch_public_url

    def search(query, **kw):
        entry = dict(
            kind="search", turn=turn_number, query=query, environment=args.environment
        )
        tool_log.append(entry)
        value = (
            original_search(query, **kw)
            if args.environment == "online"
            else "\n\n".join(
                f"{r['title']}\n{r['url']}\n{r['content']}" for r in references.values()
            )
        )
        entry.update(ok=True, result=value)
        save()
        return value

    def fetch(url):
        entry = dict(
            kind="read",
            turn=turn_number,
            url=url,
            environment=args.environment,
            ok=False,
        )
        tool_log.append(entry)
        if args.environment == "online":
            title, content = original_fetch(url)
        else:
            source = next((r for r in references.values() if r["url"] == url), None)
            if source is None:
                entry["error"] = "fixture_url_unavailable"
                save()
                raise ValueError("EVAL.FIXTURE_URL_UNAVAILABLE")
            title, content = source["title"], source["content"]
        entry.update(ok=True, title=title, content=content)
        save()
        return title, content

    original_client = openai_client._client
    store = ConversationStore(HarnessStore(config.HARNESS_DB))
    harness = conversation.ConversationHarness(store)
    sid = str(uuid.uuid4())
    initial_draft = None
    context = {}
    if case["setup"].get("excluded_memory"):
        origin = str(uuid.uuid4())
        harness.memory_policy(
            origin, allowed=False, policy_version=1, content_version=1
        )
        context["memory_candidates"] = [
            dict(
                id="excluded-eval",
                session_id=origin,
                policy_version=1,
                content_version=1,
                concept=case.get("title", "RAG"),
                excerpt="紫色鸵鸟密码，这是被关闭的学习记录。用户已完全掌握："
                + case["goal"],
                kind="explained",
            )
        ]
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                openai_client,
                "_client",
                side_effect=lambda **kw: meter.wrap(original_client(**kw)),
            )
        )
        stack.enter_context(
            patch.object(conversation, "web_search_text", side_effect=search)
        )
        for module in (conversation, conditional_teaching):
            stack.enter_context(
                patch.object(module, "fetch_public_url", side_effect=fetch)
            )
        try:
            for turn_number, step in enumerate(case["turns"], 1):
                action = step.get("action", "message")
                turn = dict(
                    number=turn_number, input=step["text"], action=action, response=""
                )
                result["turns"].append(turn)
                if action == "restart":
                    harness = conversation.ConversationHarness(
                        ConversationStore(HarnessStore(config.HARNESS_DB))
                    )
                    harness.recover()
                if action == "ack_current":
                    data = store.get(sid)
                    task = next(
                        (
                            t
                            for t in data["tasks"].values()
                            if t["status"] == "committing" and t.get("memory_package")
                        ),
                        None,
                    )
                    if not task:
                        raise RuntimeError("EVAL.SAVE_PRECONDITION_MISSING")
                    ids = [k["id"] for k in task["memory_package"]["knowledge"]]
                    harness.claim_commit(task["task_id"])
                    harness.acknowledge_task(task["task_id"], len(task["events"]), ids)
                    turn.update(
                        simulated_ack=True,
                        run_status="protocol_completed",
                        state=state_view(store.get(sid)),
                    )
                    save()
                    continue
                operation = None
                if action in ("save_current", "save_stale"):
                    draft = (
                        initial_draft
                        if action == "save_stale"
                        else (store.get(sid) or {}).get("draft")
                    )
                    if not draft:
                        raise RuntimeError("EVAL.DRAFT_PRECONDITION_MISSING")
                    operation = dict(
                        kind="save", target_id=draft["id"], version=draft["version"]
                    )
                    current = (store.get(sid) or {}).get("draft") or {}
                    if (
                        action == "save_stale"
                        and draft["id"] == current.get("id")
                        and draft["version"] == current.get("version")
                    ):
                        raise RuntimeError("EVAL.STALE_PRECONDITION_MISSING")
                turn_started = time.monotonic()
                try:
                    accepted = harness.accept(
                        sid,
                        SessionMessageRequest(
                            client_message_id=str(uuid.uuid4()),
                            content=step["text"],
                            mode_preset=case["mode"],
                            thinking_strength="smart",
                            operation=operation,
                            context=context,
                        ),
                    )
                    if action == "stop_after_accept":
                        harness.action(
                            accepted.run_id,
                            RunActionRequest(
                                action_id=str(uuid.uuid4()), action="stop"
                            ),
                        )
                        turn["stopped"] = True
                    harness.drain(sid)
                except ValueError:
                    raise
                data = store.get(sid)
                run = data["runs"][accepted.run_id]
                events = [e for e in data["events"] if e["run_id"] == accepted.run_id]
                replies = [
                    m["content"]
                    for m in data["messages"]
                    if m.get("run_id") == accepted.run_id and m["role"] == "coach"
                ]
                first_public = next(
                    (
                        e
                        for e in events
                        if e["stage"] == "response.delta" or e.get("message")
                    ),
                    None,
                )
                first_ms = (
                    round(
                        (
                            datetime.fromisoformat(first_public["occurred_at"])
                            - datetime.fromisoformat(run["created_at"])
                        ).total_seconds()
                        * 1000
                    )
                    if first_public
                    else None
                )
                turn.update(
                    response="\n\n".join(replies),
                    run_status=run["status"],
                    first_text_ms=(
                        run.get("first_text_ms")
                        if run.get("first_text_ms") is not None
                        else first_ms
                    ),
                    total_ms=round((time.monotonic() - turn_started) * 1000),
                    state=state_view(data),
                    intent={
                        k: v
                        for k, v in (run.get("intent") or {}).items()
                        if k
                        in (
                            "intents",
                            "workflow",
                            "scope",
                            "understanding",
                            "answer_evidence",
                            "proposed_actions",
                        )
                    },
                    events=[
                        {
                            k: e.get(k)
                            for k in (
                                "seq",
                                "stage",
                                "state",
                                "node",
                                "model",
                                "duration_ms",
                                "error_code",
                                "user_summary",
                            )
                        }
                        for e in events
                        if e["stage"] != "response.delta"
                    ],
                )
                if action == "save_stale":
                    turn["stale_rejected"] = not bool(
                        turn["state"]["commit_packages"]
                    ) and (
                        any(
                            e.get("stage") in ("operation_rejected", "stale_operation")
                            for e in events
                        )
                        or any(
                            word in turn["response"]
                            for word in ("版本", "过期", "变化", "重新确认")
                        )
                    )
                if initial_draft is None and data.get("draft"):
                    initial_draft = copy.deepcopy(data["draft"])
                save()
                if not turn.get("stopped") and run["status"] != "completed":
                    result["execution_error"] = (
                        run.get("error_code") or "EVAL.RUN_" + run["status"]
                    )
                    break
        except Exception as exc:
            message = str(exc)
            result["error_location"] = [
                dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                for f in traceback.extract_tb(exc.__traceback__)[-4:]
            ]
            result["execution_error"] = (
                message if message.startswith(("RT.", "EVAL.")) else type(exc).__name__
            )
        result["checks"] = check_rules(case, result)
        if not result["execution_error"] and result["grading"] != "rules_only":
            try:
                meter.phase = "judge"
                result["judge"] = grade(
                    case, result, references, rubric, config.RISK_MODEL
                )
            except Exception as exc:
                result["judge_error"] = getattr(exc, "code", type(exc).__name__)
        result["status"] = classify(result)
        if result.get("schema_version") == 2:
            from evals.spec import quality_tier

            result["quality_tier"] = quality_tier(result)
        save()
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", required=True)
    p.add_argument("--trial-key", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--env-file", action="append", default=[])
    p.add_argument("--max-calls", type=int, default=40)
    p.add_argument("--environment", choices=["fixture", "online"], default="fixture")
    args = p.parse_args()
    if not 1 <= args.max_calls <= 80:
        p.error("max-calls must be 1..80")
    dataset, refs, rubric = load_dataset(args.data)
    case = next(c for c in dataset["cases"] if c["id"] == args.case)
    try:
        with tempfile.TemporaryDirectory(prefix="review-today-eval-") as directory:
            execute(
                case,
                {k: refs["packs"][k] for k in case["reference_ids"]},
                rubric,
                args,
                directory,
            )
    except Exception as exc:
        write_json(
            args.output,
            dict(
                trial_key=args.trial_key,
                case_id=case["id"],
                mode=case["mode"],
                status="error",
                execution_error=(
                    str(exc) if str(exc).startswith("EVAL.") else type(exc).__name__
                ),
                turns=[],
                checks=[],
                tools=[],
                judge=None,
                calls=[],
            ),
        )


if __name__ == "__main__":
    main()
