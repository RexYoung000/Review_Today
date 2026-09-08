from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "data"
MODES = (
    "auto",
    "memory_organization",
    "source_learning",
    "topic_exploration",
    "problem_solving",
)
DIMENSIONS = ("intent", "correctness", "product", "teaching", "evidence", "usability")
STATUSES = ("passed", "failed", "error", "needs_review", "not_run")
RULES = {
    "no_save",
    "no_task",
    "draft_exists",
    "task_exists",
    "no_verified",
    "excluded_memory",
    "stopped_no_output",
    "save_ack",
    "stale_rejected",
    "defer_unchanged",
    "searched",
    "read_source",
    "reuse_source",
    "mastery_complete",
}
ACTIONS = {
    "message",
    "restart",
    "stop_after_accept",
    "save_current",
    "save_stale",
    "ack_current",
}


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def load_dataset(directory=DATA):
    directory = Path(directory)
    dataset, refs, rubric = [
        read_json(directory / f"{name}.json")
        for name in ("scenarios", "references", "rubric")
    ]
    if dataset.get("schema_version") == 2:
        from evals.spec import validate

        validate(dataset, refs, rubric)
        return dataset, refs, rubric
    cases = dataset["cases"]
    ids, families = set(), {}
    for case in cases:
        if (
            case["id"] in ids
            or case["mode"] not in MODES
            or case["split"] not in ("dev", "holdout")
        ):
            raise ValueError("duplicate ID or invalid mode/split")
        ids.add(case["id"])
        if case["family"] in families and families[case["family"]] != case["split"]:
            raise ValueError("family leaked across dev and holdout")
        families[case["family"]] = case["split"]
        if (
            not case["synthetic"]
            or not case["turns"]
            or not case["goal"]
            or not case["expected"]
        ):
            raise ValueError(
                "only complete, explicitly synthetic cases supported in v1"
            )
        if (
            case["knowledge"] not in ("fact", "concept", "procedure")
            or not set(case["rules"]) <= RULES
        ):
            raise ValueError("unknown rule or knowledge kind")
        if (
            not case["reference_ids"]
            or not set(case["reference_ids"]) <= refs["packs"].keys()
        ):
            raise ValueError("missing reference pack")
        if case.get("grading", "hybrid") not in ("hybrid", "rules_only"):
            raise ValueError("unknown grading policy")
        if case.get("grading") == "rules_only" and (
            case["rules"] != ["no_save", "stopped_no_output"]
            or not all(t.get("action") == "stop_after_accept" for t in case["turns"])
        ):
            raise ValueError("rules-only grading is limited to stop protocol cases")
        for turn in case["turns"]:
            if turn.get("action", "message") not in ACTIONS or (
                not turn["text"] and turn.get("action") != "ack_current"
            ):
                raise ValueError("invalid scripted turn")
    if len(cases) != 40 or Counter(c["mode"] for c in cases) != Counter(
        dict.fromkeys(MODES, 8)
    ):
        raise ValueError("v1 requires 40 cases, eight per mode")
    if (
        sum(c["critical"] for c in cases) != 10
        or sum(c["calibration"] for c in cases) != 12
    ):
        raise ValueError("v1 critical/calibration coverage mismatch")
    if sum(c["split"] == "holdout" for c in cases) != 10 or any(
        c["calibration"] and c["split"] == "holdout" for c in cases
    ):
        raise ValueError("invalid holdout or calibration selection")
    if any(
        sum(c["mode"] == m and len(c["turns"]) > 1 for c in cases) < 3 for m in MODES
    ):
        raise ValueError("insufficient multi-turn coverage")
    if set(rubric["dimensions"]) != set(DIMENSIONS):
        raise ValueError("rubric dimensions mismatch")
    return dataset, refs, rubric


def check_rules(case, result):
    turns = result.get("turns", [])
    states = [t["state"] for t in turns if "state" in t]
    checks = []

    def check(name, passed, hard=False, detail=""):
        checks.append(dict(rule=name, passed=bool(passed), hard=hard, detail=detail))

    for name in case["rules"]:
        if not states:
            check(name, False, detail="没有可检查的状态")
            continue
        if name == "no_save":
            check(
                name,
                not any(s["commit_packages"] for s in states),
                True,
                "逐轮检查知识提交包",
            )
        elif name == "no_task":
            check(
                name,
                all(not s["tasks"] for s in states),
                detail="普通对话不创建学习任务",
            )
        elif name == "task_exists":
            check(name, any(s["tasks"] for s in states), detail="应建立明确学习目标")
        elif name == "draft_exists":
            check(name, bool(states[-1]["draft"]), detail="存在交付给用户的草稿")
        elif name == "no_verified":
            verified = any(
                t.get("understanding") == "verified"
                or t.get("transfer_passed")
                or any(
                    step.get("understanding") == "verified"
                    for step in t.get("steps", [])
                )
                for s in states
                for t in s["tasks"]
            )
            verified |= any(
                e.get("kind") == "independently_verified"
                for s in states
                for e in s.get("learning_evidence", [])
            )
            check(name, not verified, True, "无无依据的独立验证/迁移通过状态")
        elif name == "excluded_memory":
            check(
                name,
                all(not s["memory_references"] for s in states)
                and "紫色鸵鸟密码"
                not in "\n".join(t.get("response", "") for t in turns),
                True,
                "关闭候选不可被引用或泄露",
            )
        elif name == "stopped_no_output":
            check(
                name,
                turns[-1].get("stopped") and not turns[-1].get("response"),
                True,
                "停止后不发布正文",
            )
        elif name == "mastery_complete":
            check(
                name,
                any(
                    t.get("mode") == "problem_solving"
                    and t.get("status") == "completed"
                    and t.get("transfer_passed")
                    for t in states[-1]["tasks"]
                ),
                detail="攻克须有独立作答及迁移完成状态",
            )
        elif name == "save_ack":
            check(
                name,
                any(t.get("simulated_ack") for t in turns)
                and any(
                    t.get("commit_claimed") and t["status"] == "completed"
                    for t in states[-1]["tasks"]
                ),
                detail="只验证服务 claim/ACK 契约",
            )
        elif name == "stale_rejected":
            check(
                name,
                any(t.get("stale_rejected") for t in turns),
                detail="过期草稿授权未被接受",
            )
        elif name == "defer_unchanged":
            keys = ("tasks", "draft", "pending", "paused")
            check(
                name,
                len(states) > 1 and all(states[-1][k] == states[-2][k] for k in keys),
                detail="犹豫不改变草稿/目标/理解/暂停",
            )
        elif name == "searched":
            check(
                name,
                any(t["kind"] == "search" for t in result.get("tools", [])),
                detail="实际进入检索边界",
            )
        elif name == "read_source":
            check(
                name,
                any(
                    t["kind"] == "read" and t.get("ok") for t in result.get("tools", [])
                ),
                detail="实际读取固定来源",
            )
        elif name == "reuse_source":
            urls = [
                t["url"]
                for t in result.get("tools", [])
                if t["kind"] == "read" and t.get("ok")
            ]
            check(
                name,
                bool(urls) and len(urls) == len(set(urls)),
                detail="相关追问不重复读取同一来源",
            )
    return checks


def validate_judge(judge, turns):
    if set(judge.get("scores", {})) != set(DIMENSIONS):
        raise ValueError("judge dimensions mismatch")
    for score in judge["scores"].values():
        if type(score) is not int or not 0 <= score <= 3:
            raise ValueError("invalid judge score")
    for finding in judge.get("critical_findings", []):
        n = finding["turn"]
        if (
            not (1 <= n <= len(turns))
            or not finding["quote"].strip()
            or finding["quote"] not in turns[n - 1].get("response", "")
        ):
            raise ValueError("judge critical finding lacks exact public evidence")
    return judge


def classify(result):
    if result.get("schema_version") == 2:
        from evals.spec import classify as classify_v2

        return classify_v2(result)
    if result.get("execution_error"):
        return "error"
    if any(not c["passed"] for c in result.get("checks", [])):
        return "failed"
    if result.get("grading") == "rules_only":
        return "passed" if result.get("checks") else "needs_review"
    judge = result.get("judge")
    if not judge or judge.get("needs_review") or result.get("judge_error"):
        return "needs_review"
    return (
        "failed"
        if judge.get("critical_findings") or min(judge["scores"].values()) < 2
        else "passed"
    )


def aggregate(manifest, results):
    if manifest.get("schema_version") == 2:
        from evals.spec import aggregate as aggregate_v2

        return aggregate_v2(manifest, results)
    by_key = {r["trial_key"]: r for r in results}
    plan_keys = [p["trial_key"] for p in manifest["plan"]]
    if (
        len(set(plan_keys)) != len(plan_keys)
        or len(by_key) != len(results)
        or set(by_key) - set(plan_keys)
    ):
        raise ValueError("duplicate or unplanned trial keys")
    counts = Counter(dict.fromkeys(STATUSES, 0))
    modes = {m: Counter(dict.fromkeys(STATUSES, 0)) for m in MODES}
    hard = 0
    for planned in manifest["plan"]:
        r = by_key.get(planned["trial_key"], {})
        status = r.get("status", "not_run")
        if status not in STATUSES:
            raise ValueError("unknown result status")
        counts[status] += 1
        modes[planned["mode"]][status] += 1
        hard += sum(c["hard"] and not c["passed"] for c in r.get("checks", [])) + len(
            (r.get("judge") or {}).get("critical_findings", [])
        )
    n = len(manifest["plan"])
    complete = not (counts["not_run"] or counts["error"] or counts["needs_review"])
    mode_pass = all(v["passed"] >= 7 and sum(v.values()) == 8 for v in modes.values())
    eligible = manifest.get("environment", "fixture") == "fixture" and not manifest.get(
        "invalidated"
    )
    baseline = (
        eligible
        and manifest["suite"] == "full"
        and n == 40
        and counts["passed"] >= 36
        and mode_pass
        and not hard
        and complete
    )
    repeats = {}
    for p in manifest["plan"]:
        repeats.setdefault(p.get("case_id", p["trial_key"]), []).append(p.get("repeat"))
    stability_plan = len(repeats) == 10 and all(
        sorted(v, key=str) == [1, 2, 3] for v in repeats.values()
    )
    stability = (
        eligible
        and manifest["suite"] == "critical"
        and stability_plan
        and n == 30
        and counts["passed"] == 30
        and not hard
    )
    return dict(
        planned=n,
        counts=dict(counts),
        modes={m: dict(v) for m, v in modes.items()},
        pass_rate=counts["passed"] / n if n else 0,
        hard_failures=hard,
        complete=complete,
        baseline_gate=baseline,
        stability_gate=stability,
        release_gate="not_assessed",
        judge_calibration="pending_human",
        note="样本通过率，不代表线上总体概率；发布还需匹配版本的基础/稳定性门槛、人工校准与原生验收。",
    )
