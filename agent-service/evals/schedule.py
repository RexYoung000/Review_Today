"""Local scheduler entry point. Polling and model execution are separate opt-ins."""

import argparse
import fcntl
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from evals.core import digest, read_json, write_json

ZONE = ZoneInfo("Asia/Shanghai")
PATHS = (
    "agent-service/agent_service",
    "agent-service/evals",
    "agent-service/pyproject.toml",
)


def weekly_slot(now):
    local = now.astimezone(ZONE)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    if monday > local:
        monday -= timedelta(days=7)
    return monday.isoformat()


def choose(now, fingerprint, state, calibrated, weekly=False):
    if not calibrated:
        return dict(action="blocked", reason="human_calibration_required")
    if (weekly or state.get("weekly_slot") is not None) and state.get(
        "weekly_slot"
    ) != weekly_slot(now):
        return dict(action="weekly", slot=weekly_slot(now))
    if not weekly and state.get("fingerprint") != fingerprint:
        return dict(action="smoke")
    return dict(action="unchanged")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def public_identity(root, python, env_files):
    script = """import json,os,sys,tempfile
from dotenv import load_dotenv
for path in sys.argv[1:]:load_dotenv(path,override=False)
os.environ['REVIEW_TODAY_HARNESS_DB']=os.path.join(tempfile.gettempdir(),'review-today-identity-only.sqlite3')
from agent_service import config
print(json.dumps(dict(provider=config.PROVIDER,judge=config.RISK_MODEL,router=config.ROUTER_MODEL,coach=config.COACH_MODEL)))
"""
    return json.loads(
        subprocess.check_output(
            [python, "-c", script, *env_files],
            cwd=Path(root) / "agent-service",
            text=True,
        )
    )


def run(args):
    root = Path(args.repo).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with (output / "schedule.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps(dict(action="already_running")))
            return
        state_path = output / "schedule-state.json"
        state = read_json(state_path) if state_path.exists() else {}
        commit = git(root, "rev-parse", args.branch + "^{commit}")
        tree = git(root, "ls-tree", "-r", commit, "--", *PATHS)
        identity = public_identity(root, args.python, args.env_file)
        fingerprint = digest(dict(tree=tree, models=identity))
        # Calibration is recomputed against committed judge/data content, not dirty edits.
        contrasts = json.loads(
            git(root, "show", commit + ":agent-service/evals/data/calibration.json")
        )
        rubric = json.loads(
            git(root, "show", commit + ":agent-service/evals/data/rubric.json")
        )
        judge_hash = digest(
            {
                n: git(root, "show", commit + ":agent-service/evals/" + n) + "\n"
                for n in ("judge.py", "spec.py", "core.py", "calibration.py")
            }
        )
        from evals.calibration import binding, summarize

        caldir = Path(args.calibration_dir)
        approvals = (
            read_json(caldir / "approvals.json")
            if (caldir / "approvals.json").exists()
            else {}
        )
        verification = (
            read_json(caldir / "verification.json")
            if (caldir / "verification.json").exists()
            else {}
        )
        expected = binding(
            rubric,
            contrasts,
            dict(provider=identity["provider"], judge=identity["judge"]),
            judge_hash,
        )
        calibration = summarize(contrasts, approvals, expected, verification)
        decision = choose(
            datetime.now(ZONE),
            fingerprint,
            state,
            calibration["status"] == "verified",
            args.weekly,
        )
        decision.update(
            commit=commit, fingerprint=fingerprint, calibration=calibration["status"]
        )
        write_json(output / "schedule-decision.json", decision)
        print(json.dumps(decision, ensure_ascii=False), flush=True)
        if not args.execute or decision["action"] not in ("weekly", "smoke"):
            return
        # Durable dispatch marker prevents repeated charges after uncertain interruption.
        if state.get("inflight"):
            print(
                json.dumps(
                    dict(
                        action="needs_attention",
                        reason="previous_dispatch_incomplete",
                        inflight=state["inflight"],
                    )
                )
            )
            return
        state["inflight"] = decision
        write_json(state_path, state)
        try:
            with tempfile.TemporaryDirectory(
                prefix="review-today-eval-checkout-"
            ) as temp:
                checkout = Path(temp) / "repo"
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "worktree",
                        "add",
                        "--detach",
                        str(checkout),
                        commit,
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                try:
                    suites = (
                        ["full", "critical"]
                        if decision["action"] == "weekly"
                        else ["smoke"]
                    )
                    for suite in suites:
                        cmd = [
                            args.python,
                            "-m",
                            "evals",
                            "run",
                            "--live",
                            "--suite",
                            suite,
                            "--output",
                            str(output),
                            "--calibration-dir",
                            str(caldir.resolve()),
                        ]
                        if args.feishu_config:
                            cmd += [
                                "--feishu-config",
                                str(Path(args.feishu_config).resolve()),
                            ]
                        for env in args.env_file:
                            cmd += ["--env-file", str(Path(env).resolve())]
                        subprocess.run(cmd, cwd=checkout / "agent-service", check=True)
                finally:
                    subprocess.run(
                        ["git", "-C", str(root), "worktree", "remove", str(checkout)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )
            state["fingerprint"] = fingerprint
            if decision["action"] == "weekly":
                state["weekly_slot"] = decision["slot"]
            state.pop("inflight", None)
            state.pop("error", None)
            write_json(state_path, state)
        except Exception as exc:
            state["error"] = type(exc).__name__
            write_json(state_path, state)
            raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="codex/harness-evaluations")
    p.add_argument("--python", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--calibration-dir", required=True)
    p.add_argument("--feishu-config")
    p.add_argument("--env-file", action="append", default=[])
    p.add_argument("--weekly", action="store_true")
    p.add_argument("--execute", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
