"""Version 2 contracts. No model, database, network, or configuration imports."""

import copy
import math
from collections import Counter
from evals.core import MODES, STATUSES, RULES, ACTIONS, digest

DIMENSIONS = (
    "intent",
    "correctness",
    "mode_delivery",
    "teaching",
    "evidence",
    "usability",
)
DOMAINS = ("science", "technology", "humanities", "language", "practice")
DOMAIN_NAMES = dict(
    zip(
        DOMAINS,
        (
            "自然科学与数学",
            "技术与工程",
            "人文与社会科学",
            "语言与表达",
            "商业与生活应用",
        ),
    )
)
TIERS = ("failed", "qualified", "excellent")


def validate(dataset, refs, rubric):
    cases = dataset["cases"]
    coverage = dataset["coverage"]
    assert_contract = lambda ok, msg: None if ok else fail(msg)
    assert_contract(set(rubric["dimensions"]) == set(DIMENSIONS), "rubric dimensions")
    assert_contract(len(cases) == coverage["total"] == 100, "total coverage")
    ids, families, texts = set(), {}, set()
    for c in cases:
        assert_contract(c["id"] not in ids, "duplicate ID")
        ids.add(c["id"])
        assert_contract(c["mode"] in MODES and c["domain"] in DOMAINS, "mode/domain")
        assert_contract(c["split"] in ("dev", "holdout"), "split")
        assert_contract(
            c["family"] not in families or families[c["family"]] == c["split"],
            "family leaked",
        )
        families[c["family"]] = c["split"]
        assert_contract(c.get("synthetic") is True, "only synthetic data is enabled")
        assert_contract(
            c.get("goal")
            and c.get("expected")
            and c.get("stage")
            and c.get("background"),
            "missing task contract",
        )
        assert_contract(
            c["knowledge"] in ("fact", "concept", "procedure"), "knowledge kind"
        )
        assert_contract(
            bool(c["reference_ids"])
            and set(c["reference_ids"]) <= refs["packs"].keys(),
            "missing reference",
        )
        assert_contract(bool(c["turns"]) and set(c["rules"]) <= RULES, "rules/turns")
        for t in c["turns"]:
            assert_contract(
                t.get("action", "message") in ACTIONS
                and (t.get("text") or t.get("action") == "ack_current"),
                "invalid action",
            )
        fingerprint = digest(c["turns"])
        assert_contract(fingerprint not in texts, "duplicate scripted input")
        texts.add(fingerprint)
        if c.get("grading", "hybrid") == "rules_only":
            assert_contract(
                c["rules"] == ["no_save", "stopped_no_output"]
                and all(t.get("action") == "stop_after_accept" for t in c["turns"]),
                "rules-only limited to stop protocol",
            )
            assert_contract(
                not c["applicable_dimensions"] and not c["excellent_criteria"],
                "stop protocol cannot claim excellence",
            )
        else:
            assert_contract(c.get("grading", "hybrid") == "hybrid", "grading policy")
            dims = c["applicable_dimensions"]
            assert_contract(
                len(dims) == len(set(dims)) and set(dims) <= set(DIMENSIONS),
                "applicable dimensions",
            )
            assert_contract(
                {"intent", "correctness", "mode_delivery", "evidence", "usability"}
                <= set(dims),
                "required dimensions cannot be waived",
            )
            assert_contract(
                set(c["na_reasons"]) == set(DIMENSIONS) - set(dims)
                and all(c["na_reasons"].values()),
                "N/A reasons",
            )
            for key in ("pass_criteria", "excellent_criteria"):
                checks = c[key]
                assert_contract(
                    checks and len({x["id"] for x in checks}) == len(checks),
                    "criterion IDs",
                )
                assert_contract(
                    all(x["text"] and x["dimension"] in dims for x in checks),
                    "criterion dimension/text",
                )
        assert_contract(
            not (
                c["split"] == "holdout"
                and (c["critical"] or c["smoke"] or c["calibration"])
            ),
            "holdout used for development",
        )
        assert_contract(not c["critical"] or c["smoke"], "critical must be in smoke")
    policy = dataset["gate_policy"]
    assert_contract(
        set(policy["case_ids"]) == ids and len(policy["case_ids"]) == len(ids),
        "gate case IDs",
    )
    assert_contract(
        set(policy["critical_ids"]) == {c["id"] for c in cases if c["critical"]},
        "gate critical IDs",
    )
    assert_contract(
        policy["per_mode"] == 20
        and policy["pass_rate"] == 0.9
        and policy["repeats"] == 3,
        "v2 gate policy",
    )
    for field, values in [("mode", MODES), ("domain", DOMAINS)]:
        assert_contract(
            Counter(c[field] for c in cases) == Counter(dict.fromkeys(values, 20)),
            field + " coverage",
        )
        for flag, count in [("smoke", 5), ("critical", 4), ("calibration", 5)]:
            assert_contract(
                Counter(c[field] for c in cases if c[flag])
                == Counter(dict.fromkeys(values, count)),
                flag + " coverage",
            )
    assert_contract(
        all(
            sum(c["mode"] == m and len(c["turns"]) > 1 for c in cases) >= 10
            for m in MODES
        ),
        "multi-turn coverage",
    )
    assert_contract(
        Counter((c["mode"], c["domain"]) for c in cases)
        == Counter({(m, d): 4 for m in MODES for d in DOMAINS}),
        "cross coverage",
    )
    assert_contract(sum(c["split"] == "holdout" for c in cases) == 25, "holdout size")
    assert_contract(
        all(
            r.get("content") and r.get("url") and r.get("kind")
            for r in refs["packs"].values()
        ),
        "reference content",
    )


def fail(message):
    raise ValueError(message)


def validate_verdict(judge, turns, case):
    if set(judge.get("scores", {})) != set(DIMENSIONS):
        fail("judge dimensions mismatch")
    dims = case["applicable_dimensions"]
    for dim, value in judge["scores"].items():
        if dim in dims:
            if type(value) is not int or not 0 <= value <= 3:
                fail("invalid applicable score")
        elif value is not None:
            fail("N/A dimension must be null")
    for key, criteria in [
        ("requirements", "pass_criteria"),
        ("excellence", "excellent_criteria"),
    ]:
        items = judge.get(key, [])
        if len(items) != len(case[criteria]) or {x["id"] for x in items} != {
            x["id"] for x in case[criteria]
        }:
            fail("missing or unknown criterion verdict")
        if any(type(x.get("passed")) is not bool or not x.get("reason") for x in items):
            fail("criterion verdict needs boolean and reason")
    for e in judge.get("evidence", []) + judge.get("critical_findings", []):
        n = e.get("turn")
        if (
            type(n) is not int
            or not 1 <= n <= len(turns)
            or not e.get("quote")
            or e["quote"] not in turns[n - 1].get("response", "")
        ):
            fail("judge evidence lacks exact public quote")
    if not judge.get("needs_review") and not judge.get("evidence"):
        fail("semantic verdict requires public evidence")
    return judge


def classify(result):
    if result.get("execution_error"):
        return "error"
    if any(not c["passed"] for c in result.get("checks", [])):
        return "failed"
    if result.get("grading") == "rules_only":
        return "passed" if result.get("checks") else "needs_review"
    j = result.get("judge")
    if not j or j.get("needs_review") or result.get("judge_error"):
        return "needs_review"
    try:
        validate_verdict(j, result["turns"], result["case_contract"])
    except (ValueError, KeyError, TypeError):
        return "needs_review"
    if (
        j.get("critical_findings")
        or any(v is not None and v < 2 for v in j["scores"].values())
        or not all(x["passed"] for x in j["requirements"])
    ):
        return "failed"
    return "passed"


def quality_tier(result):
    if classify(result) != "passed":
        return None
    if result.get("grading") == "rules_only":
        return "qualified"
    j = result["judge"]
    excellence = result["case_contract"]["excellent_criteria"]
    if (
        excellence
        and all(x["passed"] for x in j["excellence"])
        and all(j["scores"][x["dimension"]] == 3 for x in excellence)
    ):
        return "excellent"
    return "qualified"


def evidence_hash(result):
    return digest({k: v for k, v in result.items() if k not in ("effective_review",)})


def reviewed_result(result, review, rubric_hash):
    """An annotation cannot rewrite a failed execution or objective assertion."""
    r = copy.deepcopy(result)
    if not review:
        return r
    required = ("reviewer", "reviewed_at", "reason", "evidence")
    if (
        not all(review.get(k) for k in required)
        or review.get("rubric_hash") != rubric_hash
        or review.get("result_hash") != evidence_hash(result)
    ):
        return r
    if result.get("execution_error") or any(
        not c["passed"] for c in result.get("checks", [])
    ):
        return r
    verdict = review.get("verdict")
    if verdict not in ("failed", "qualified", "excellent", "needs_review"):
        return r
    if verdict == "excellent" and result.get("grading") == "rules_only":
        return r
    r["status"] = "passed" if verdict in ("qualified", "excellent") else verdict
    r["quality_tier"] = verdict if r["status"] == "passed" else None
    r["effective_review"] = review
    return r


def aggregate(manifest, results):
    plan = manifest["plan"]
    keys = [p["trial_key"] for p in plan]
    by_key = {r["trial_key"]: r for r in results}
    if (
        len(set(keys)) != len(keys)
        or len(by_key) != len(results)
        or set(by_key) - set(keys)
    ):
        fail("duplicate or unplanned trial keys")
    counts = Counter(dict.fromkeys(STATUSES, 0))
    machine = Counter(dict.fromkeys(STATUSES, 0))
    modes = {m: Counter(dict.fromkeys(STATUSES, 0)) for m in MODES}
    domains = {d: Counter(dict.fromkeys(STATUSES, 0)) for d in DOMAINS}
    excellent = Counter()
    hard, completed = 0, 0
    effective = {}
    for p in plan:
        raw = by_key.get(p["trial_key"], {})
        status = raw.get("status", "not_run")
        if status not in STATUSES:
            fail("unknown status")
        machine[status] += 1
        r = reviewed_result(
            raw,
            manifest.get("reviews", {}).get(p["trial_key"]),
            manifest.get("rubric_hash"),
        )
        status = r.get("status", "not_run")
        effective[p["trial_key"]] = r
        counts[status] += 1
        modes[p["mode"]][status] += 1
        domains[p["domain"]][status] += 1
        completed += status != "not_run"
        if status == "passed" and r.get("quality_tier") == "excellent":
            excellent["total"] += 1
            excellent[p["mode"]] += 1
            excellent[p["domain"]] += 1
        hard += sum(
            c.get("hard", False) and not c["passed"] for c in r.get("checks", [])
        )
        if not r.get("effective_review") or status != "passed":
            hard += len((r.get("judge") or {}).get("critical_findings", []))
    policy = manifest["gate_policy"]
    complete = not any(counts[k] for k in ("not_run", "error", "needs_review"))
    eligible = (
        manifest.get("environment") == "fixture"
        and not manifest.get("invalidated")
        and bool(manifest.get("finished_at"))
    )
    case_ids = [p["case_id"] for p in plan]
    full_plan = len(case_ids) == len(set(case_ids)) and set(case_ids) == set(
        policy["case_ids"]
    )
    mode_pass = all(
        sum(v.values()) == policy["per_mode"]
        and v["passed"] >= math.ceil(policy["per_mode"] * policy["pass_rate"])
        for v in modes.values()
    )
    critical_ok = all(
        effective[p["trial_key"]].get("status") == "passed"
        for p in plan
        if p["case_id"] in policy["critical_ids"]
    )
    base = (
        eligible
        and manifest["suite"] == "full"
        and full_plan
        and mode_pass
        and critical_ok
        and not hard
        and complete
    )
    repeat_map = {}
    for p in plan:
        repeat_map.setdefault(p["case_id"], []).append(p["repeat"])
    repeat_plan = set(repeat_map) == set(policy["critical_ids"]) and all(
        sorted(v) == list(range(1, policy["repeats"] + 1)) for v in repeat_map.values()
    )
    stable = (
        eligible
        and manifest["suite"] == "critical"
        and repeat_plan
        and counts["passed"] == len(plan)
        and not hard
        and complete
    )
    calibrated = manifest.get("calibration_status") == "verified"
    n = len(plan)
    return dict(
        planned=n,
        completed=completed,
        counts=dict(counts),
        machine_counts=dict(machine),
        modes={k: dict(v) for k, v in modes.items()},
        domains={k: dict(v) for k, v in domains.items()},
        excellent=dict(excellent),
        excellent_rate=excellent["total"] / n if n else 0,
        pass_rate=counts["passed"] / n if n else 0,
        machine_pass_rate=machine["passed"] / n if n else 0,
        hard_failures=hard,
        complete=complete,
        candidate_baseline_gate=bool(base),
        candidate_stability_gate=bool(stable),
        baseline_gate=bool(base and calibrated),
        stability_gate=bool(stable and calibrated),
        release_gate="not_assessed",
        judge_calibration=manifest.get("calibration_status", "pending_human"),
        effective_results={
            k: {
                "status": r.get("status", "not_run"),
                "quality_tier": r.get("quality_tier"),
                "reviewed": bool(r.get("effective_review")),
            }
            for k, r in effective.items()
        },
        note="合格包括优秀；全部计划项保留分母；固定样本表现不是总体成功概率。正式门槛须校准且版本匹配，原生验收独立。",
    )


def audit_selection(manifest, results):
    chosen = set()
    for mode in MODES:
        passed = [
            r for r in results if r.get("mode") == mode and r.get("status") == "passed"
        ]
        passed.sort(key=lambda r: digest([manifest["run_id"], r["trial_key"]]))
        chosen.update(r["trial_key"] for r in passed[: math.ceil(len(passed) * 0.1)])
    chosen.update(
        r["trial_key"]
        for r in results
        if r.get("status") == "needs_review"
        or (r.get("judge") or {}).get("critical_findings")
        or any(c.get("hard") and not c["passed"] for c in r.get("checks", []))
    )
    return sorted(chosen)
