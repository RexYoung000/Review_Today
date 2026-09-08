"""Additive v2 Base schema, review transport, and progress updates."""

import json
from datetime import datetime, timezone
from pathlib import Path
from evals.core import DATA, load_dataset, read_json, write_json
from evals.spec import DOMAIN_NAMES, evidence_hash
from evals.calibration import material_hash

TIER_LABELS = {
    "qualified": "合格",
    "excellent": "优秀",
    "failed": "不合格",
    "needs_review": "待判",
}


def extend_schema(schemas, manual):
    def text(n):
        return dict(name=n, type="text")

    def flag(n):
        return dict(name=n, type="checkbox")

    def num(n):
        return dict(name=n, type="number", style=dict(type="plain", precision=2))

    def select(n, options):
        return dict(
            name=n,
            type="select",
            multiple=False,
            options=[dict(name=x) for x in options],
        )

    additions = {
        "样本": [
            text("领域"),
            text("任务阶段"),
            text("评分标准"),
            text("合格条件"),
            text("优秀条件"),
            text("维度适用性"),
            flag("日常回归"),
            text("对照指纹"),
            text("不合格对照"),
            text("合格对照"),
            text("优秀对照"),
            flag("对照确认"),
            text("校准人"),
            text("校准时间"),
            text("校准说明"),
            num("校准待审标记"),
        ],
        "评测批次": [
            text("样本版本"),
            text("标准版本"),
            text("运行状态"),
            num("已完成数"),
            text("更新时间"),
            num("优秀数"),
            num("优秀率"),
            num("机器通过数"),
            num("机器通过率"),
            text("标准校准状态"),
            text("版本比较"),
            text("任务状态"),
        ],
        "结果明细": [
            text("领域"),
            text("标准版本"),
            text("优秀分层"),
            num("优秀标记"),
            text("有效结论"),
            num("有效通过标记"),
            text("适用维度"),
            flag("需人工抽查"),
            text("结果指纹"),
            select(
                "复核等级", ["未复核", "不合格", "合格", "优秀", "待判", "样本问题"]
            ),
            text("复核人"),
            text("复核时间"),
            text("复核依据"),
        ],
        "问题处理": [
            text("机器根因候选"),
            text("最近出现时间"),
            text("根因类别"),
            text("根因组"),
            text("关联复测"),
            flag("再次出现"),
            text("再次出现批次"),
        ],
    }
    for name, fields in additions.items():
        schemas[name].extend(fields)
    schemas["结果明细"].append(num("模式交付"))
    manual["样本"].update({"对照确认", "校准人", "校准时间", "校准说明"})
    manual["结果明细"].update({"复核等级", "复核人", "复核时间", "复核依据"})
    manual["问题处理"].update({"根因类别", "根因组", "关联复测"})


def enrich_samples(rows, dataset, contrasts=None):
    if dataset.get("schema_version") != 2:
        return rows
    entries = {e["case_id"]: e for e in (contrasts or {}).get("cases", [])}
    for row, c in zip(rows, dataset["cases"]):
        row.update(
            {
                "领域": DOMAIN_NAMES[c["domain"]],
                "任务阶段": c["stage"],
                "评分标准": dataset["version"],
                "合格条件": "\n".join(x["text"] for x in c["pass_criteria"]),
                "优秀条件": "\n".join(x["text"] for x in c["excellent_criteria"]),
                "维度适用性": json.dumps(
                    dict(applicable=c["applicable_dimensions"], na=c["na_reasons"]),
                    ensure_ascii=False,
                ),
                "日常回归": c["smoke"],
                "校准待审标记": int(c["calibration"]),
            }
        )
        entry = entries.get(c["id"])
        if entry:
            row.update(
                {
                    "对照指纹": material_hash(entry),
                    "对照确认": False,
                    "校准人": "",
                    "校准时间": "",
                    "校准说明": "",
                }
            )
            for v in entry["variants"]:
                field = {
                    "failed": "不合格对照",
                    "qualified": "合格对照",
                    "excellent": "优秀对照",
                }[v["tier"]]
                row[field] = (
                    "候选对照，需人工确认；非真实Harness输出。\n\n"
                    + "\n\n".join(
                        f"用户：{t['input']}\n教练：{t['response']}"
                        for t in v["result"]["turns"]
                    )
                )
    return rows


def calibration_rows(config, data=DATA):
    from evals.feishu import locked, sample_rows

    dataset, refs, _ = load_dataset(data)
    contrasts = read_json(Path(data) / "calibration.json")
    with locked(config) as cli:
        rows = enrich_samples(sample_rows(dataset, refs), dataset, contrasts)
        old = {r["样本键"]: r for r in cli.records(cli.config["tables"]["样本"])}
        for row in rows:
            previous = old.get(row["样本键"], {})
            if previous.get("对照确认") and previous.get("对照指纹") != row.get(
                "对照指纹"
            ):
                raise ValueError(
                    "Approved calibration material changed: create a new dataset version"
                )
            if (
                previous.get("对照确认")
                and previous.get("校准人")
                and previous.get("校准时间")
            ):
                row["校准待审标记"] = 0
        ids = cli.upsert("样本", rows)
        return dict(samples=len(ids), calibration_cases=len(contrasts["cases"]))


def pull_calibration(config, output, data=DATA):
    from evals.feishu import locked

    dataset, _, _ = load_dataset(data)
    contrasts = read_json(Path(data) / "calibration.json")
    with locked(config) as cli:
        rows = {r["样本键"]: r for r in cli.records(cli.config["tables"]["样本"])}
    approvals = {}
    for e in contrasts["cases"]:
        r = rows.get(dataset["version"] + ":" + e["case_id"], {})
        approvals[e["case_id"]] = dict(
            approved=r.get("对照确认") is True,
            reviewer=r.get("校准人"),
            reviewed_at=r.get("校准时间"),
            notes=r.get("校准说明"),
            material_hash=r.get("对照指纹"),
        )
    write_json(
        Path(output) / "approvals.json",
        dict(pulled_at=datetime.now(timezone.utc).isoformat(), approvals=approvals),
    )
    from evals.calibration import approval_status

    return dict(
        approved=25 - len(approval_status(contrasts, {"approvals": approvals})),
        total=25,
    )


def review_rows(run_dir, rows):
    run_dir = Path(run_dir)
    m = read_json(run_dir / "manifest.json")
    reviews = {}
    for row in rows:
        key = row.get("结果键", "")
        if not key.startswith(m["run_id"] + "/"):
            continue
        trial = key[len(m["run_id"]) + 1 :]
        path = run_dir / "trials" / f"{trial}.json"
        if not path.exists():
            continue
        raw = read_json(path)
        selected = row.get("复核等级", [])
        label = selected[0] if isinstance(selected, list) and selected else None
        verdict = {
            **{v: k for k, v in TIER_LABELS.items()},
            "样本问题": "needs_review",
        }.get(label)
        if not verdict:
            continue
        reviews[trial] = dict(
            verdict=verdict,
            reviewer=row.get("复核人"),
            reviewed_at=row.get("复核时间"),
            reason=row.get("人工原因"),
            evidence=row.get("复核依据"),
            rubric_hash=m["rubric_hash"],
            result_hash=row.get("结果指纹"),
        )
    write_json(
        run_dir / "effective-reviews.json",
        dict(pulled_at=datetime.now(timezone.utc).isoformat(), reviews=reviews),
    )
    return reviews


def batch_fields(manifest, summary):
    return {
        "样本版本": manifest.get("dataset_version", "v1"),
        "标准版本": manifest.get("rubric_version", "v1"),
        "运行状态": (
            "无效"
            if manifest.get("invalidated")
            else "已结束" if manifest.get("finished_at") else "运行中"
        ),
        "已完成数": summary.get(
            "completed", summary["planned"] - summary["counts"]["not_run"]
        ),
        "更新时间": datetime.now(timezone.utc).isoformat(),
        "优秀数": summary.get("excellent", {}).get("total", 0),
        "优秀率": summary.get("excellent_rate", 0) * 100,
        "机器通过数": summary.get("machine_counts", summary["counts"])["passed"],
        "机器通过率": summary.get("machine_pass_rate", summary["pass_rate"]) * 100,
        "标准校准状态": summary["judge_calibration"],
        "任务状态": (
            "定时任务暂停，待人工校准及调度验收"
            if summary["judge_calibration"] != "verified"
            else "校准已验证；调度状态见本地自动任务"
        ),
    }


def issue_update(incoming, previous):
    """Old-batch replays cannot rewind an issue or reopen a later human closure."""
    if previous and incoming["最近出现时间"] <= previous.get("最近出现时间", ""):
        return None
    if previous.get("处理状态") == ["已关闭"]:
        incoming.update({"再次出现": True, "处理状态": ["待分析"]})
    else:
        incoming["再次出现"] = previous.get("再次出现", False)
    return incoming


def root_candidate(category):
    if category == "scenario_precondition":
        return "样本条件（待人工确认）"
    if category in ("judge", "judge_format"):
        return "裁判（待人工确认）"
    if category in ("environment", "transport"):
        return "运行环境（待人工确认）"
    if category in ("runner", "budget", "timeout"):
        return "评测执行（待人工确认）"
    return "产品行为或样本预期（待人工确认）"


def result_fields(planned, result, manifest, summary, audit):
    effective = summary.get("effective_results", {}).get(planned["trial_key"], {})
    status = effective.get("status", result.get("status", "not_run"))
    tier = effective.get("quality_tier", result.get("quality_tier"))
    return {
        "领域": DOMAIN_NAMES.get(planned.get("domain"), "历史未分类"),
        "标准版本": manifest.get("rubric_version", "v1"),
        "优秀分层": TIER_LABELS.get(tier, "未评优秀"),
        "优秀标记": int(status == "passed" and tier == "excellent"),
        "有效结论": TIER_LABELS.get(tier, status),
        "有效通过标记": int(status == "passed"),
        "适用维度": ", ".join(
            result.get("case_contract", {}).get("applicable_dimensions", [])
        ),
        "需人工抽查": planned["trial_key"] in audit,
        "结果指纹": evidence_hash(result) if result else "",
        "复核等级": ["未复核"],
        "复核人": "",
        "复核时间": "",
        "复核依据": "",
    }


def sync_progress(run_dir, config):
    """Only batch progress, at most once a minute; never move the latest baseline."""
    from evals.feishu import locked
    from evals.report import build

    run_dir = Path(run_dir)
    m = read_json(run_dir / "manifest.json")
    marker = run_dir / "progress-sync.json"
    now = datetime.now(timezone.utc)
    if (
        marker.exists()
        and (now - datetime.fromisoformat(read_json(marker)["at"])).total_seconds() < 60
    ):
        return
    s = build(run_dir)
    row = {
        "批次键": m["run_id"],
        "批类型": m["suite"],
        "开始时间": m["started_at"],
        "工具环境": m["environment"],
        "计划数": s["planned"],
        "通过数": s["counts"]["passed"],
        "失败数": s["counts"]["failed"],
        "运行错误数": s["counts"]["error"],
        "待复核数": s["counts"]["needs_review"],
        "未运行数": s["counts"]["not_run"],
        "通过率": s["pass_rate"] * 100,
        **batch_fields(m, s),
    }
    with locked(config) as cli:
        cli.upsert("评测批次", [row])
    write_json(marker, {"at": now.isoformat()})
