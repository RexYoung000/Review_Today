"""Local evidence report; Feishu is the daily dashboard."""

from pathlib import Path
from evals.core import aggregate, read_json, write_json

LABELS = {
    "passed": "通过",
    "failed": "失败",
    "error": "运行错误",
    "needs_review": "待复核",
    "not_run": "未运行",
}


def build(run_dir):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    results = [read_json(p) for p in sorted((run_dir / "trials").glob("*.json"))]
    if manifest.get("schema_version") == 2:
        from evals.calibration import current_status
        from evals.spec import audit_selection

        review_file = run_dir / "effective-reviews.json"
        manifest["reviews"] = (
            read_json(review_file).get("reviews", {}) if review_file.exists() else {}
        )
        cal = current_status(
            run_dir / "data",
            read_json(run_dir / "data/rubric.json"),
            manifest.get("model_identity"),
            manifest["calibration_dir"],
            manifest.get("judge_code_hash"),
        )
        manifest["calibration_status"] = cal["status"]
        write_json(run_dir / "calibration-status.json", cal)
        write_json(
            run_dir / "audit-selection.json",
            {"trial_keys": audit_selection(manifest, results)},
        )
    summary = aggregate(manifest, results)
    write_json(run_dir / "summary.json", summary)
    lines = [
        f"# {manifest['run_id']}\n",
        f"批次：{manifest['suite']}；环境：{manifest['environment']}。人工校准：{summary['judge_calibration']}。\n",
        f"计划 {summary['planned']}，"
        + "，".join(f"{LABELS[k]} {v}" for k, v in summary["counts"].items())
        + "。\n",
        f"样本通过率 {summary['pass_rate']:.1%}；优秀率 {summary.get('excellent_rate', 0):.1%}；硬失败 {summary['hard_failures']}。不代表线上总体概率或产品发布验收。\n",
        f"代码提交：{manifest['git_commit']}；生产代码哈希：{manifest['service_hash']}\n",
        f"基础门槛：{summary['baseline_gate']}；关键重复门槛：{summary['stability_gate']}。不同批次不混合判定。\n",
        "| 模式 | 通过 | 失败 | 错误 | 待复核 | 未运行 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode, c in summary["modes"].items():
        lines.append("| " + mode + " | " + " | ".join(str(c[k]) for k in LABELS) + " |")
    lines += ["", "## 单次证据", ""]
    index = {r["trial_key"]: r for r in results}
    for planned in manifest["plan"]:
        r = index.get(planned["trial_key"], {})
        lines += [f"### {planned['trial_key']} · {LABELS[r.get('status','not_run')]}\n"]
        if not r:
            continue
        j = r.get("judge") or {}
        lines += [
            f"机器诊断：{j.get('summary') or r.get('execution_error') or r.get('judge_error') or '暂无'}\n",
            f"修复方向：{j.get('repair_direction','待诊断')}\n",
            f"维度评分：{j.get('scores',{})}；优秀分层：{r.get('quality_tier')}\n",
            f"有效结论：{summary.get('effective_results',{}).get(planned['trial_key'],{})}\n",
            f"规则失败：{[c['rule'] for c in r.get('checks',[]) if not c['passed']]}\n",
            f"请求数：{len(r.get('calls',[]))}；总耗时：{r.get('total_ms')} ms\n",
            f"裁判校验原因：{r.get('judge_error_detail', '无')}；失败原判保留在原始记录 judge_raw。\n",
        ]
        for t in r.get("turns", []):
            lines += [
                f"轮次 {t['number']}（{t.get('action','message')}）\n",
                "    用户：" + t["input"].replace("\n", "\n    "),
                "",
                "    教练：" + t.get("response", "").replace("\n", "\n    "),
                "",
            ]
        lines.append(f"原始记录：trials/{planned['trial_key']}.json\n")
    body = "\n".join(lines)
    (run_dir / "report.md").write_text(
        "\n".join(line.rstrip() for line in body.splitlines()).rstrip() + "\n"
    )
    return summary
