from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from evals.core import load_dataset, digest, read_json, write_json
from evals.report import build

SERVICE = Path(__file__).resolve().parent.parent
ROOT = SERVICE.parent


def source_hash(folder="agent_service"):
    h = hashlib.sha256()
    for p in sorted((SERVICE / folder).rglob("*.py")):
        h.update(str(p.relative_to(SERVICE)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def one_trial(planned, args, directory):
    destination = directory / "trials" / f"{planned['trial_key']}.json"
    cmd = [
        sys.executable,
        "-m",
        "evals.worker",
        "--live",
        "--case",
        planned["case_id"],
        "--trial-key",
        planned["trial_key"],
        "--data",
        str(directory / "data"),
        "--output",
        str(destination),
        "--max-calls",
        str(args.max_calls),
        "--environment",
        args.environment,
    ]
    for env in args.env_file:
        cmd += ["--env-file", str(Path(env).resolve())]
    process = subprocess.Popen(
        cmd, cwd=SERVICE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        code = process.wait(timeout=args.case_timeout)
        if code:
            raise RuntimeError(f"EVAL.WORKER_EXIT_{code}")
        result = read_json(destination)
    except (subprocess.TimeoutExpired, RuntimeError, FileNotFoundError) as exc:
        process.kill()
        process.wait()
        result = (
            read_json(destination)
            if destination.exists()
            else dict(turns=[], checks=[], tools=[], judge=None, calls=[])
        )
        result.update(
            trial_key=planned["trial_key"],
            case_id=planned["case_id"],
            mode=planned["mode"],
            status="error",
            execution_error=(
                "EVAL.CASE_TIMEOUT"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "EVAL.WORKER_FAILED"
            ),
        )
        write_json(destination, result)
    return result


def run(args):
    dataset, refs, rubric = load_dataset()
    if not args.live:
        raise SystemExit("真实模型运行需显式 --live；validate 不调用模型。")
    if (
        not 1 <= args.concurrency <= 4
        or not 1 <= args.max_calls <= 80
        or not 30 <= args.case_timeout <= 1200
    ):
        raise SystemExit("invalid concurrency/call/time bounds")
    selected = [c for c in dataset["cases"] if args.suite == "full" or c[args.suite]]
    if args.case:
        if not set(args.case) <= {c["id"] for c in selected}:
            raise SystemExit("case 不在所选 suite 中")
        selected = [c for c in selected if c["id"] in args.case]
    repeats = 3 if args.suite == "critical" else 1
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + args.suite
        + "-"
        + uuid.uuid4().hex[:6]
    )
    directory = Path(args.output).resolve() / run_id
    directory.mkdir(parents=True)
    (directory / "trials").mkdir()
    for name, data in [
        ("scenarios", dataset),
        ("references", refs),
        ("rubric", rubric),
    ]:
        write_json(directory / "data" / f"{name}.json", data)
    plan = [
        dict(case_id=c["id"], mode=c["mode"], trial_key=f"{c['id']}-r{n}", repeat=n)
        for c in selected
        for n in range(1, repeats + 1)
    ]
    manifest = dict(
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        suite=args.suite,
        environment=args.environment,
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        service_hash=source_hash(),
        dataset_hash=digest(dataset),
        rubric_hash=digest(rubric),
        reference_hash=digest(refs),
        evaluator_hash=source_hash("evals"),
        python_version=sys.version.split()[0],
        plan=plan,
        synthetic=True,
        judge_calibration="pending_human",
        limits=dict(
            max_calls_per_trial=args.max_calls,
            max_calls_batch=len(plan) * args.max_calls,
            case_timeout=args.case_timeout,
            concurrency=args.concurrency,
        ),
        started_with_dirty_evaluator=bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--", "agent-service/evals"],
                cwd=ROOT,
                text=True,
            )
        ),
    )
    write_json(directory / "manifest.json", manifest)
    build(directory)
    print(
        json.dumps(
            dict(
                run_dir=str(directory),
                planned=len(plan),
                max_calls=manifest["limits"]["max_calls_batch"],
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        pending = {pool.submit(one_trial, p, args, directory): p for p in plan}
        while pending:
            done, _ = concurrent.futures.wait(
                pending, timeout=30, return_when=concurrent.futures.FIRST_COMPLETED
            )
            if not done:
                print(json.dumps(dict(running=len(pending), run_id=run_id)), flush=True)
            for future in done:
                p = pending.pop(future)
                r = future.result()
                print(
                    json.dumps(
                        dict(
                            trial=p["trial_key"],
                            status=r["status"],
                            calls=len(r.get("calls", [])),
                            error=r.get("execution_error"),
                            judge_error=r.get("judge_error"),
                        ),
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                build(directory)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["service_hash_end"] = source_hash()
    manifest["evaluator_hash_end"] = source_hash("evals")
    if manifest["evaluator_hash_end"] != manifest["evaluator_hash"]:
        manifest["invalidated"] = "evaluator changed during run"
    if manifest["service_hash_end"] != manifest["service_hash"]:
        manifest["invalidated"] = "service changed during run"
    write_json(directory / "manifest.json", manifest)
    print(json.dumps(build(directory), ensure_ascii=False), flush=True)
    if args.feishu_config:
        from evals.feishu import sync

        try:
            sync(directory, Path(args.feishu_config))
        except Exception as exc:
            write_json(
                directory / "feishu-sync-error.json",
                dict(
                    error=type(exc).__name__,
                    message=str(exc),
                    local_results_preserved=True,
                ),
            )
            print("飞书同步失败，本地结果保留；用 sync 重试。", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Review Today Harness 质量评测")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="验证40场景，不调用模型")
    p = sub.add_parser("run")
    p.add_argument("--live", action="store_true")
    p.add_argument(
        "--suite", choices=["calibration", "full", "critical"], default="calibration"
    )
    p.add_argument("--case", action="append")
    p.add_argument("--environment", choices=["fixture", "online"], default="fixture")
    p.add_argument(
        "--feishu-config", help="运行完成后自动同步飞书；同步失败保留本地结果"
    )
    p.add_argument("--env-file", action="append", default=[])
    p.add_argument("--max-calls", type=int, default=40)
    p.add_argument("--case-timeout", type=int, default=600)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--output", default=str(ROOT / "output/harness-evals"))
    p = sub.add_parser("report")
    p.add_argument("run_dir")
    p = sub.add_parser("sync")
    p.add_argument("run_dir")
    p.add_argument("--config", required=True)
    p = sub.add_parser("provision")
    p.add_argument("--config", required=True)
    p = sub.add_parser("review")
    p.add_argument("run_dir")
    p.add_argument("--config", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        d, r, b = load_dataset()
        print(
            json.dumps(
                dict(
                    cases=len(d["cases"]),
                    dataset_hash=digest(d),
                    references=len(r["packs"]),
                    rubric=b["version"],
                ),
                ensure_ascii=False,
            )
        )
    elif args.command == "run":
        run(args)
    elif args.command == "report":
        print(json.dumps(build(args.run_dir), ensure_ascii=False))
    else:
        from evals.feishu import provision, sync, pull_reviews

        if args.command == "provision":
            provision(Path(args.config))
        elif args.command == "sync":
            sync(Path(args.run_dir), Path(args.config))
        else:
            pull_reviews(Path(args.run_dir), Path(args.config))


if __name__ == "__main__":
    main()
