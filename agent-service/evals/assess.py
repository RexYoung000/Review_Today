"""Pair matching full and repeated batches; never equate evals with release."""

import argparse
import json
from pathlib import Path
from evals.core import read_json, write_json
from evals.report import build

MATCH_FIELDS = (
    "service_hash",
    "evaluator_hash",
    "dataset_hash",
    "rubric_hash",
    "reference_hash",
    "model_identity",
    "model_roles",
    "environment",
)


def assess(full_dir, critical_dir):
    a, b = Path(full_dir), Path(critical_dir)
    ma, mb = read_json(a / "manifest.json"), read_json(b / "manifest.json")
    sa, sb = build(a), build(b)
    mismatches = [
        k for k in MATCH_FIELDS if ma.get(k) != mb.get(k) or ma.get(k) is None
    ]
    passed = (
        ma.get("schema_version") == mb.get("schema_version") == 2
        and not mismatches
        and sa["baseline_gate"]
        and sb["stability_gate"]
    )
    return dict(
        quality_gate=(
            "passed"
            if passed
            else (
                "pending_calibration"
                if sa["judge_calibration"] != "verified"
                or sb["judge_calibration"] != "verified"
                else "not_passed"
            )
        ),
        matching_versions=not mismatches,
        mismatches=mismatches,
        full_run=ma["run_id"],
        critical_run=mb["run_id"],
        baseline_gate=sa["baseline_gate"],
        stability_gate=sb["stability_gate"],
        release_gate="not_assessed",
    )


def compare(previous, current):
    a, b = Path(previous), Path(current)
    ma, mb = read_json(a / "manifest.json"), read_json(b / "manifest.json")
    fields = (
        "dataset_hash",
        "rubric_hash",
        "reference_hash",
        "judge_code_hash",
        "model_identity",
        "model_roles",
        "environment",
        "suite",
    )
    mismatch = [k for k in fields if ma.get(k) != mb.get(k)]
    if mismatch:
        return dict(
            comparable=False, reason="标准、参考、裁判或批类型不同", mismatches=mismatch
        )
    ra = {
        r["trial_key"]: r for r in [read_json(p) for p in (a / "trials").glob("*.json")]
    }
    rb = {
        r["trial_key"]: r for r in [read_json(p) for p in (b / "trials").glob("*.json")]
    }
    shared = set(ra) & set(rb)
    return dict(
        comparable=True,
        scope="机器原判；人工复核另列",
        new_failures=sorted(
            k
            for k in shared
            if ra[k].get("status") == "passed" and rb[k].get("status") != "passed"
        ),
        recovered=sorted(
            k
            for k in shared
            if ra[k].get("status") != "passed" and rb[k].get("status") == "passed"
        ),
        shared=len(shared),
        added=sorted(set(rb) - set(ra)),
        removed=sorted(set(ra) - set(rb)),
    )


def compare_latest(current):
    current = Path(current)
    manifest = read_json(current / "manifest.json")
    candidates = []
    for p in current.parent.glob("*/manifest.json"):
        if p.parent == current:
            continue
        m = read_json(p)
        if (
            m.get("finished_at")
            and not m.get("invalidated")
            and m.get("suite") == manifest["suite"]
            and m.get("environment") == manifest["environment"]
            and m.get("started_at", "") < manifest["started_at"]
        ):
            candidates.append((m["started_at"], p.parent))
    result = dict(comparable=False, reason="尚无前一同类批次")
    if candidates:
        previous = max(candidates)[1]
        result = dict(compare(previous, current), previous_run=previous.name)
    if manifest.get("invalidated") or not manifest.get("finished_at"):
        result = dict(comparable=False, reason="当前批次未结束或已失效")
    write_json(current / "comparison.json", result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("full")
    p.add_argument("critical")
    p.add_argument("--output")
    args = p.parse_args()
    result = assess(args.full, args.critical)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
