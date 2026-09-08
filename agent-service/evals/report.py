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
    summary = aggregate(manifest, results)
    write_json(run_dir / "summary.json", summary)
    lines = [
        f"# {manifest['run_id']}\n",
        f"批次：{manifest['suite']}；环境：{manifest['environment']}。人工校准：待完成。\n",
        f"计划 {summary['planned']}，"
        + "，".join(f"{LABELS[k]} {v}" for k, v in summary["counts"].items())
        + "。\n",
        f"样本通过率 {summary['pass_rate']:.1%}；硬失败 {summary['hard_failures']}。不代表线上总体概率或产品发布验收。\n",
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
            f"维度评分：{j.get('scores',{})}\n",
            f"规则失败：{[c['rule'] for c in r.get('checks',[]) if not c['passed']]}\n",
            f"请求数：{len(r.get('calls',[]))}；总耗时：{r.get('total_ms')} ms\n",
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
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")
    return summary
