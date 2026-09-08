"""Feishu user CLI adapter. Cloud mutations are serial, keyed, and recoverable."""

from __future__ import annotations
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from evals.core import DATA, DIMENSIONS, load_dataset, read_json, write_json
from evals.report import build, LABELS

MODE_NAMES = dict(
    zip(
        (
            "auto",
            "memory_organization",
            "source_learning",
            "topic_exploration",
            "problem_solving",
        ),
        ("Auto", "知识整理", "资料学习", "主题探索", "问题攻克"),
    )
)
SCORES = dict(zip(DIMENSIONS, ("意图", "正确性", "产品边界", "教学", "依据", "表达")))


def text(name):
    return dict(name=name, type="text")


def num(name):
    return dict(name=name, type="number", style=dict(type="plain", precision=2))


def flag(name):
    return dict(name=name, type="checkbox")


def select(name, values):
    return dict(
        name=name, type="select", multiple=False, options=[dict(name=x) for x in values]
    )


def link(name, table):
    return dict(name=name, type="link", link_table=table)


SCHEMAS = {
    "样本": [
        text("样本键"),
        text("编号"),
        text("名称"),
        select("模式", MODE_NAMES.values()),
        text("版本"),
        select("分组", ["dev", "holdout"]),
        flag("校准样本"),
        flag("关键样本"),
        text("知识类型"),
        text("用户目标"),
        text("用户输入"),
        text("预期与断言"),
        text("参考材料"),
        text("候选变更备注"),
    ],
    "评测批次": [
        text("批次键"),
        text("批类型"),
        text("开始时间"),
        text("工具环境"),
        text("代码版本"),
        text("生产源码哈希"),
        text("样本哈希"),
        text("评分标准哈希"),
        text("模型角色"),
        num("计划数"),
        num("通过数"),
        num("失败数"),
        num("运行错误数"),
        num("待复核数"),
        num("未运行数"),
        num("通过率"),
        num("硬失败数"),
        text("门槛"),
        text("人工校准"),
        text("本地报告"),
        flag("最新批次"),
        flag("最新同类批次"),
    ],
    "结果明细": [
        text("结果键"),
        link("样本", "样本"),
        link("批次", "评测批次"),
        text("样本编号"),
        select("模式", MODE_NAMES.values()),
        text("批类型"),
        text("工具环境"),
        select("机器结果", LABELS.values()),
        num("通过标记"),
        num("试验数"),
    ]
    + [num(v) for v in SCORES.values()]
    + [
        text("失败断言"),
        text("机器诊断"),
        text("修复方向"),
        text("对话记录"),
        text("诊断证据"),
        num("总耗时秒"),
        num("首段正文秒"),
        num("模型请求数"),
        num("已报告tokens"),
        text("原始记录"),
        select(
            "人工结论", ["待复核", "同意通过", "同意失败", "机器误判", "样本需修订"]
        ),
        text("人工原因"),
        flag("最新批次"),
        flag("最新同类批次"),
    ],
    "问题处理": [
        text("问题键"),
        link("样本", "样本"),
        link("首次结果", "结果明细"),
        link("最近结果", "结果明细"),
        text("问题分类"),
        text("问题说明"),
        text("证据"),
        text("建议检查入口"),
        select(
            "处理状态",
            [
                "待分析",
                "待确认修复",
                "已批准修复",
                "修复中",
                "待回归",
                "已关闭",
                "样本问题",
            ],
        ),
        text("人工确认与备注"),
    ],
}
MANUAL = {
    "样本": {"候选变更备注"},
    "评测批次": {"人工校准"},
    "结果明细": {"人工结论", "人工原因"},
    "问题处理": {"首次结果", "处理状态", "人工确认与备注"},
}


class LarkError(RuntimeError):
    pass


class CLI:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.binary = shutil.which("lark-cli") or str(
            Path.home() / ".local/bin/lark-cli"
        )
        self.config = read_json(self.config_path) if self.config_path.exists() else {}

    def save(self):
        write_json(self.config_path, self.config)

    def call(self, command, **kwargs):
        cmd = [self.binary, "base", "+" + command, "--as", "user"]
        if "format" not in kwargs:
            kwargs["format"] = "json"
        for key, value in kwargs.items():
            option = "--" + key.replace("_", "-")
            if value is None:
                continue
            if isinstance(value, bool):
                if value:
                    cmd.append(option)
            else:
                cmd += [
                    option,
                    (
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, (dict, list))
                        else str(value)
                    ),
                ]
        env = {
            **os.environ,
            "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
            "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
        }
        try:
            r = subprocess.run(
                cmd,
                cwd=self.config_path.parent,
                env=env,
                text=True,
                capture_output=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            raise LarkError("CLI timeout; mutation outcome may be uncertain") from None
        try:
            payload = json.loads(r.stdout if r.returncode == 0 else r.stderr)
        except json.JSONDecodeError:
            payload = {}
        if r.returncode or payload.get("ok") is False:
            error = payload.get("error") or {}
            # No auth bodies or environment variables in durable results.
            raise LarkError(
                f"{command}: exit={r.returncode} code={error.get('code','unknown')} message={error.get('message','CLI failed')}"
            )
        return payload.get("data", payload)

    def fields(self, table):
        fields = self.call(
            "field-list", base_token=self.config["base_token"], table_id=table
        )["fields"]
        return {f["name"]: f for f in fields}

    def records(self, table):
        rows = []
        offset = 0
        # Artifacts must be relative to CLI cwd. Each complete page is checked.
        with tempfile.TemporaryDirectory(
            prefix=".eval-read-", dir=self.config_path.parent
        ) as d:
            while True:
                dest = Path(d) / f"page-{offset}.ndjson"
                self.call(
                    "record-list",
                    base_token=self.config["base_token"],
                    table_id=table,
                    format="ndjson",
                    output=str(dest.relative_to(self.config_path.parent)),
                    offset=offset,
                    limit=2000,
                )
                manifest = read_json(dest.with_suffix(".manifest.json"))
                page = [
                    json.loads(line)
                    for line in dest.read_text().splitlines()
                    if line.strip()
                ]
                if len(page) != manifest["records_count"]:
                    raise LarkError("record manifest count mismatch")
                rows.extend(page)
                if not manifest["has_more"]:
                    break
                if not page:
                    raise LarkError("empty page with has_more")
                offset += len(page)
        return rows

    def upsert(self, table_name, rows):
        table = self.config["tables"][table_name]
        key = SCHEMAS[table_name][0]["name"]
        fields = self.fields(table)
        if any(set(row) - set(fields) for row in rows):
            raise LarkError("schema mismatch before write")

        def indexed():
            records = self.records(table)
            out = {}
            for row in records:
                if row.get(key) in out:
                    raise LarkError(
                        "duplicate business key; manual inspection required"
                    )
                out[row.get(key)] = row
            return out

        current = indexed()
        uncertain = self.config.setdefault("uncertain_creates", {}).get(table, [])
        if any(k not in current for k in uncertain):
            raise LarkError(
                "previous create uncertain; inspect remote records before clearing pending marker"
            )
        if uncertain:
            self.config["uncertain_creates"].pop(table)
            self.save()
        creates = [r for r in rows if r[key] not in current]
        updates = {
            current[r[key]]["record_id"]: {
                k: v for k, v in r.items() if k not in MANUAL[table_name]
            }
            for r in rows
            if r[key] in current
        }
        for start in range(0, len(creates), 200):
            part = creates[start : start + 200]
            self.config["uncertain_creates"][table] = [r[key] for r in part]
            self.save()
            try:
                response = self.call(
                    "record-batch-create",
                    base_token=self.config["base_token"],
                    table_id=table,
                    json=dict(create_records=part),
                )
                ids = response["record_id_list"]
                if len(ids) != len(part):
                    raise LarkError("create response length mismatch")
                for row, rid in zip(part, ids):
                    current[row[key]] = {**row, "record_id": rid}
            except LarkError:
                recovered = indexed()
                if not all(r[key] in recovered for r in part):
                    raise
                current.update(recovered)
            self.config["uncertain_creates"].pop(table, None)
            self.save()
        pairs = list(updates.items())
        for start in range(0, len(pairs), 200):
            self.call(
                "record-batch-update",
                base_token=self.config["base_token"],
                table_id=table,
                json=dict(update_records=dict(pairs[start : start + 200])),
            )
        return {r[key]: current[r[key]]["record_id"] for r in rows}


@contextmanager
def locked(config):
    config = Path(config)
    config.parent.mkdir(parents=True, exist_ok=True)
    with config.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield CLI(config)


def provision(config):
    with locked(config) as cli:
        if "base_token" not in cli.config:
            if cli.config.get("base_creation_pending"):
                raise LarkError(
                    "base creation outcome uncertain; recover returned Base URL before retry"
                )
            cli.config.update(
                name="Review Today｜Harness 质量评测", base_creation_pending=True
            )
            cli.save()
            result = cli.call(
                "base-create",
                name=cli.config["name"],
                table_name="样本",
                fields=SCHEMAS["样本"],
                time_zone="Asia/Shanghai",
            )
            cli.config.update(
                base_token=result["base"]["base_token"],
                url=result["base"]["url"],
                tables={"样本": result["table"]["id"]},
                base_creation_pending=False,
            )
            cli.save()
        print(
            json.dumps(
                dict(url=cli.config["url"], base_token=cli.config["base_token"]),
                ensure_ascii=False,
            ),
            flush=True,
        )
        base = cli.config["base_token"]
        found = {
            t["name"]: t["id"]
            for t in cli.call("table-list", base_token=base, limit=100)["tables"]
        }
        for name, schema in SCHEMAS.items():
            if name not in found:
                result = cli.call(
                    "table-create", base_token=base, name=name, fields=schema
                )
                found[name] = result["table"]["id"]
            cli.config.setdefault("tables", {})[name] = found[name]
            cli.save()
            if set(f["name"] for f in schema) - set(cli.fields(found[name])):
                raise LarkError("existing table has incomplete schema")
        # A dedicated Base is small; reject ambiguous paginated inventories rather than assuming completeness.
        dashboards = cli.call("dashboard-list", base_token=base, page_size=100)
        if dashboards.get("has_more"):
            raise LarkError("paginate dashboard inventory before provisioning")
        print(
            json.dumps(
                dict(stage="tables_ready", dashboard_inventory=dashboards),
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not cli.config.get("dashboard_id"):
            items = dashboards.get("items", dashboards.get("dashboards", []))
            old = next((d for d in items if d.get("name") == "质量总览"), None)
            result = old or cli.call(
                "dashboard-create", base_token=base, name="质量总览"
            )
            cli.config["dashboard_id"] = (
                result.get("dashboard_id")
                or result.get("id")
                or result.get("dashboard", {}).get("dashboard_id")
            )
            if not cli.config["dashboard_id"]:
                print(json.dumps(result, ensure_ascii=False))
                raise LarkError("dashboard create schema needs inspection")
            cli.save()
        print(
            json.dumps(
                dict(stage="dashboard_ready", config=cli.config), ensure_ascii=False
            ),
            flush=True,
        )
        configure_dashboard(cli)


def configure_dashboard(cli):
    base = cli.config["base_token"]
    dashboard = cli.config["dashboard_id"]
    inventory = cli.call(
        "dashboard-block-list", base_token=base, dashboard_id=dashboard, page_size=100
    )
    if inventory.get("has_more"):
        raise LarkError("paginate dashboard blocks before update")
    items = inventory.get("items", inventory.get("blocks", []))
    blocks = {b["name"]: b.get("block_id", b.get("id")) for b in items}
    latest = dict(
        conjunction="and",
        conditions=[dict(field_name="最新批次", operator="is", value=True)],
    )
    configs = [
        (
            "怎么看这张表",
            "text",
            dict(
                text="## Harness 质量评测\n先看最新批次，再到结果明细阅读失败证据和给出人工结论。\n- 机器裁判尚待人工校准\n- 通过率只代表计划样本；错误、待复核、未运行都保留分母\n- 基础40题与关键10题各3次分开判定\n- 问题默认待分析，确认后修复；不会自动改产品或金标\n- 固定来源与真实联网分开，模拟ACK不证明Mac持久化"
            ),
        )
    ]
    for title, field in [
        ("最新通过", "通过数"),
        ("最新失败", "失败数"),
        ("运行错误", "运行错误数"),
        ("机器待判", "待复核数"),
        ("计划场景", "计划数"),
        ("硬失败", "硬失败数"),
    ]:
        configs.append(
            (
                title,
                "statistics",
                dict(
                    table_name="评测批次",
                    series=[dict(field_name=field, rollup="SUM")],
                    filter=latest,
                ),
            )
        )
    configs += [
        (
            "待人工复核",
            "statistics",
            dict(
                table_name="结果明细",
                series=[dict(field_name="试验数", rollup="SUM")],
                filter=dict(
                    conjunction="and",
                    conditions=[
                        dict(field_name="最新批次", operator="is", value=True),
                        dict(field_name="人工结论", operator="is", value="待复核"),
                    ],
                ),
            ),
        ),
        (
            "各模式通过情况",
            "column",
            dict(
                table_name="结果明细",
                series=[dict(field_name="通过标记", rollup="SUM")],
                group_by=[dict(field_name="模式", mode="integrated")],
                filter=latest,
            ),
        ),
        (
            "最新批次结果分布",
            "ring",
            dict(
                table_name="结果明细",
                count_all=True,
                group_by=[dict(field_name="机器结果", mode="integrated")],
                filter=latest,
            ),
        ),
        (
            "批次通过率趋势",
            "line",
            dict(
                table_name="评测批次",
                series=[dict(field_name="通过率", rollup="AVERAGE")],
                filter=dict(
                    conjunction="and",
                    conditions=[
                        dict(field_name="工具环境", operator="is", value="fixture")
                    ],
                ),
                group_by=[
                    dict(
                        field_name="开始时间",
                        mode="integrated",
                        sort=dict(type="group", order="asc"),
                    ),
                    dict(field_name="批类型", mode="integrated"),
                ],
            ),
        ),
        (
            "待处理问题分类",
            "bar",
            dict(
                table_name="问题处理",
                count_all=True,
                group_by=[dict(field_name="问题分类", mode="integrated")],
                filter=dict(
                    conjunction="and",
                    conditions=[
                        dict(field_name="处理状态", operator="isNot", value="已关闭")
                    ],
                ),
            ),
        ),
    ]
    configs.append(
        (
            "完整基线通过率（%）",
            "statistics",
            dict(
                table_name="评测批次",
                series=[dict(field_name="通过率", rollup="SUM")],
                filter=latest,
            ),
        )
    )
    critical_filter = dict(
        conjunction="and",
        conditions=[
            dict(field_name="最新同类批次", operator="is", value=True),
            dict(field_name="批类型", operator="is", value="critical"),
            dict(field_name="工具环境", operator="is", value="fixture"),
        ],
    )
    for title, field in [
        ("关键重复通过", "通过数"),
        ("关键重复计划", "计划数"),
        ("关键重复错误", "运行错误数"),
    ]:
        configs.append(
            (
                title,
                "statistics",
                dict(
                    table_name="评测批次",
                    series=[dict(field_name=field, rollup="SUM")],
                    filter=critical_filter,
                ),
            )
        )
    created = False
    for name, kind, data in configs:
        if name in blocks:
            continue
        r = cli.call(
            "dashboard-block-create",
            base_token=base,
            dashboard_id=dashboard,
            name=name,
            type=kind,
            data_config=data,
        )
        block = r.get("block_id") or r.get("id") or r.get("block", {}).get("block_id")
        cli.config.setdefault("blocks", {})[name] = block
        cli.save()
        created = True
        print(
            json.dumps(dict(component=name, result=r), ensure_ascii=False), flush=True
        )
    if created:
        cli.call("dashboard-arrange", base_token=base, dashboard_id=dashboard)
    cli.config["dashboard_url"] = cli.config["url"] + "?block=" + dashboard
    cli.save()
    # View names allow users to find failures without asking an AI for a report.
    for table, name, conditions in [
        (
            "结果明细",
            "失败与异常",
            [["机器结果", "intersects", ["失败", "运行错误", "待复核"]]],
        ),
        ("结果明细", "人工校准", [["人工结论", "intersects", ["待复核"]]]),
        ("问题处理", "尚未关闭", [["处理状态", "disjoint", ["已关闭"]]]),
    ]:
        marker = f"{table}/{name}"
        if marker in cli.config.get("views", {}):
            continue
        existing_views = cli.call(
            "view-list",
            base_token=base,
            table_id=cli.config["tables"][table],
            limit=200,
        )
        if existing_views.get("has_more"):
            raise LarkError("paginate views before provisioning")
        views = existing_views.get("views", [])
        if not any(v["name"] == name for v in views):
            cli.call(
                "view-create",
                base_token=base,
                table_id=cli.config["tables"][table],
                json=dict(name=name, type="grid"),
            )
        cli.call(
            "view-set-filter",
            base_token=base,
            table_id=cli.config["tables"][table],
            view_id=name,
            json=dict(logic="and", conditions=conditions),
        )
        cli.config.setdefault("views", {})[marker] = True
        cli.save()
    print(
        json.dumps(dict(dashboard=cli.config["dashboard_url"]), ensure_ascii=False),
        flush=True,
    )


def sample_rows(dataset, refs):
    return [
        dict(
            zip(
                (
                    "样本键",
                    "编号",
                    "名称",
                    "模式",
                    "版本",
                    "分组",
                    "校准样本",
                    "关键样本",
                    "知识类型",
                    "用户目标",
                    "用户输入",
                    "预期与断言",
                    "参考材料",
                    "候选变更备注",
                ),
                (
                    dataset["version"] + ":" + c["id"],
                    c["id"],
                    c["title"],
                    [MODE_NAMES[c["mode"]]],
                    dataset["version"],
                    [c["split"]],
                    c["calibration"],
                    c["critical"],
                    c["knowledge"],
                    c["goal"],
                    "\n".join(
                        f"{i}. [{t.get('action','message')}] {t['text']}"
                        for i, t in enumerate(c["turns"], 1)
                    ),
                    c["expected"] + "\n规则：" + ", ".join(c["rules"]),
                    "\n\n".join(
                        refs["packs"][k]["title"]
                        + "\n"
                        + refs["packs"][k]["url"]
                        + "\n"
                        + refs["packs"][k]["content"]
                        for k in c["reference_ids"]
                    ),
                    "",
                ),
            )
        )
        for c in dataset["cases"]
    ]


ENTRY = {
    "intent": "agent_service/conversation.py + conversation_prompts.py",
    "content": "conversation_prompts.py + 对应参考包",
    "authorization": "conversation.py 的版本绑定与 _save_memory",
    "learning_state": "learning_progress.py + _evaluate",
    "source": "conditional_teaching.py 的来源读取与证据评估",
    "memory": "learning_memory.py + memory_policy",
    "usability": "conversation_prompts.py + answer_style.py",
    "environment": "openai_client.py + execution_policy.py",
    "structured_output": "structured_output.py + conversation._call 的结构化格式恢复",
    "scenario_precondition": "先检查该场景前一轮实际输出与状态，再区分产品行为和脚本前置条件",
    "uncertain": "先人工复核样本与轨迹",
    "none": "无需修复",
}


def latest_flags(batches):
    """The main dashboard prefers a full fixture baseline; cohorts stay separate."""
    if not batches:
        return {}
    full = [
        b
        for b in batches
        if b.get("批类型") == "full"
        and b.get("工具环境") == "fixture"
        and b.get("计划数") == 40
    ]
    fixture = [b for b in batches if b.get("工具环境") == "fixture"]
    focus = max(full or fixture or batches, key=lambda b: b["开始时间"])["批次键"]
    cohorts = {}
    for b in batches:
        group = (b.get("批类型"), b.get("工具环境"))
        if group not in cohorts or b["开始时间"] > cohorts[group]["开始时间"]:
            cohorts[group] = b
    return {
        b["批次键"]: {
            "最新批次": b["批次键"] == focus,
            "最新同类批次": b["批次键"]
            == cohorts[(b.get("批类型"), b.get("工具环境"))]["批次键"],
        }
        for b in batches
    }


def reconcile_latest(cli):
    tables = cli.config["tables"]
    batches = cli.records(tables["评测批次"])
    flags = latest_flags(batches)
    for table, records in [
        ("评测批次", batches),
        ("结果明细", cli.records(tables["结果明细"])),
    ]:
        changes = {}
        for row in records:
            key = (
                row["批次键"]
                if table == "评测批次"
                else row["结果键"].rsplit("/", 1)[0]
            )
            expected = flags.get(key, {"最新批次": False, "最新同类批次": False})
            if any(row.get(k) != v for k, v in expected.items()):
                changes[row["record_id"]] = expected
        pairs = list(changes.items())
        for start in range(0, len(pairs), 200):
            cli.call(
                "record-batch-update",
                base_token=cli.config["base_token"],
                table_id=tables[table],
                json={"update_records": dict(pairs[start : start + 200])},
            )


def error_category(error):
    if not error:
        return "uncertain"
    if error.startswith("RT.INTENT."):
        return "intent"
    if error.startswith(("RT.PLAN.", "RT.PRACTICE.")):
        return "learning_state"
    if error == "RT.MODEL.SCHEMA":
        return "structured_output"
    if error.startswith("EVAL.") and "PRECONDITION" in error:
        return "scenario_precondition"
    if error.startswith("RT.MODEL."):
        return "environment"
    return "uncertain"


CATEGORIES = {
    "intent": "意图识别",
    "content": "内容正确性",
    "authorization": "授权与保存",
    "learning_state": "学习状态",
    "source": "资料来源",
    "memory": "学习记忆",
    "usability": "表达体验",
    "environment": "模型运行环境",
    "uncertain": "待进一步定位",
    "structured_output": "结构化格式",
    "scenario_precondition": "场景前置条件",
    "none": "待人工复核",
}


def sync(run_dir, config):
    run_dir = Path(run_dir).resolve()
    manifest = read_json(run_dir / "manifest.json")
    dataset, refs, _ = load_dataset(run_dir / "data")
    summary = build(run_dir)
    if not manifest.get("synthetic"):
        raise LarkError("only synthetic evaluation batches may be synchronized")
    results = {
        r["trial_key"]: r
        for r in [read_json(p) for p in (run_dir / "trials").glob("*.json")]
    }
    with locked(config) as cli:
        base = cli.config["base_token"]
        tables = cli.config["tables"]
        samples = cli.upsert("样本", sample_rows(dataset, refs))
        previous = cli.records(tables["评测批次"])
        # Syncing an older batch cannot steal the dashboard latest marker.
        is_latest = not any(
            r.get("开始时间", "") > manifest["started_at"] for r in previous
        )
        roles = next(
            (r.get("model_roles") for r in results.values() if r.get("model_roles")),
            None,
        )
        batch = {
            "批次键": manifest["run_id"],
            "批类型": manifest["suite"],
            "开始时间": manifest["started_at"],
            "工具环境": manifest["environment"],
            "代码版本": manifest["git_commit"],
            "生产源码哈希": manifest["service_hash"],
            "样本哈希": manifest["dataset_hash"],
            "评分标准哈希": manifest["rubric_hash"],
            "模型角色": json.dumps(roles, ensure_ascii=False),
            "计划数": summary["planned"],
            "通过数": summary["counts"]["passed"],
            "失败数": summary["counts"]["failed"],
            "运行错误数": summary["counts"]["error"],
            "待复核数": summary["counts"]["needs_review"],
            "未运行数": summary["counts"]["not_run"],
            "通过率": summary["pass_rate"] * 100,
            "硬失败数": summary["hard_failures"],
            "门槛": f"基础={summary['baseline_gate']}；关键重复={summary['stability_gate']}；未放行产品",
            "人工校准": "待完成",
            "本地报告": str(run_dir / "report.md"),
            "最新批次": is_latest,
        }
        batches = cli.upsert("评测批次", [batch])
        batch_id = batches[manifest["run_id"]]
        rows = []
        issues = []
        for p in manifest["plan"]:
            r = results.get(p["trial_key"], {})
            j = r.get("judge") or {}
            status = r.get("status", "not_run")
            key = manifest["run_id"] + "/" + p["trial_key"]
            turns = r.get("turns", [])
            rule_fail = [c["rule"] for c in r.get("checks", []) if not c["passed"]]
            diagnosis = (
                j.get("summary")
                or r.get("execution_error")
                or r.get("judge_error")
                or (
                    "仅规则判定：停止协议无需生成回答"
                    if r.get("grading") == "rules_only"
                    else "等待运行"
                )
            )
            transcript = "\n\n".join(
                f"轮次{t['number']} [{t.get('action','message')}]\n用户：{t['input']}\n教练：{t.get('response','')}"
                for t in turns
            )
            calls = r.get("calls", [])
            usage = [c["usage"] for c in calls if c.get("usage")]
            first = next(
                (
                    t["first_text_ms"] / 1000
                    for t in turns
                    if t.get("first_text_ms") is not None
                ),
                None,
            )
            row = {
                "结果键": key,
                "样本": [{"id": samples[dataset["version"] + ":" + p["case_id"]]}],
                "批次": [{"id": batch_id}],
                "样本编号": p["case_id"],
                "模式": [MODE_NAMES[p["mode"]]],
                "批类型": manifest["suite"],
                "工具环境": manifest["environment"],
                "机器结果": [LABELS[status]],
                "通过标记": int(status == "passed"),
                "试验数": 1,
                "失败断言": ", ".join(rule_fail),
                "机器诊断": diagnosis,
                "修复方向": j.get("repair_direction", "先检查运行错误或人工复核"),
                "对话记录": transcript[:50000],
                "诊断证据": json.dumps(
                    dict(
                        evidence=j.get("evidence"),
                        critical=j.get("critical_findings"),
                        rules=r.get("checks"),
                    ),
                    ensure_ascii=False,
                )[:20000],
                "总耗时秒": r.get("total_ms", 0) / 1000,
                "首段正文秒": first,
                "模型请求数": len(calls),
                "已报告tokens": (
                    sum(u.get("total_tokens") or 0 for u in usage) if usage else None
                ),
                "原始记录": str(run_dir / "trials" / f"{p['trial_key']}.json"),
                "人工结论": ["待复核"],
                "人工原因": "",
                "最新批次": is_latest,
            }
            row.update(
                {label: j.get("scores", {}).get(dim) for dim, label in SCORES.items()}
            )
            rows.append(row)
            if status in ("failed", "error", "needs_review"):
                category = j.get("diagnosis") or error_category(
                    r.get("execution_error") or r.get("judge_error")
                )
                if rule_fail and not r.get("execution_error"):
                    category = "rules:" + ",".join(sorted(rule_fail))
                issues.append(
                    (
                        key,
                        p["case_id"],
                        category,
                        diagnosis,
                        row["诊断证据"],
                        ENTRY.get(category, "先对照失败断言检查对应状态门禁")
                        + "\n"
                        + j.get("repair_direction", ""),
                    )
                )
        record_ids = cli.upsert("结果明细", rows)
        problem_rows = []
        for key, case_id, category, diagnosis, evidence, entry in issues:
            problem_rows.append(
                {
                    "问题键": dataset["version"] + ":" + case_id + ":" + category,
                    "样本": [{"id": samples[dataset["version"] + ":" + case_id]}],
                    "首次结果": [{"id": record_ids[key]}],
                    "最近结果": [{"id": record_ids[key]}],
                    "问题分类": CATEGORIES.get(
                        category,
                        "程序断言" if category.startswith("rules:") else category,
                    ),
                    "问题说明": diagnosis,
                    "证据": evidence,
                    "建议检查入口": entry,
                    "处理状态": ["待分析"],
                    "人工确认与备注": "",
                }
            )
        # Repeated critical trials produce one issue per case/category, retaining the first observation.
        unique = {}
        for row in problem_rows:
            if row["问题键"] in unique:
                row["首次结果"] = unique[row["问题键"]]["首次结果"]
            unique[row["问题键"]] = row
        if unique:
            cli.upsert("问题处理", list(unique.values()))
        reconcile_latest(cli)
        cloud = cli.records(tables["结果明细"])
        actual = [r for r in cloud if r["结果键"].startswith(manifest["run_id"] + "/")]
        if len(actual) != len(rows) or len({r["结果键"] for r in actual}) != len(rows):
            raise LarkError("post-sync count/uniqueness verification failed")
        if sum(r.get("通过标记", 0) for r in actual) != summary["counts"]["passed"]:
            raise LarkError("post-sync pass count mismatch")
        receipt = dict(
            synced_at=datetime.now(timezone.utc).isoformat(),
            run_id=manifest["run_id"],
            cloud_records=len(actual),
            passed=summary["counts"]["passed"],
            base_url=cli.config["url"],
            dashboard_url=cli.config.get("dashboard_url"),
            verified=True,
        )
        write_json(run_dir / "feishu-sync.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)


def pull_reviews(run_dir, config):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    with locked(config) as cli:
        rows = cli.records(cli.config["tables"]["结果明细"])
        reviews = [
            {k: r.get(k) for k in ("结果键", "机器结果", "人工结论", "人工原因")}
            for r in rows
            if r["结果键"].startswith(manifest["run_id"] + "/")
        ]
        write_json(
            run_dir / "human-reviews.json",
            dict(
                read_at=datetime.now(timezone.utc).isoformat(),
                reviews=reviews,
                note="人工意见与原始机器评分分开；不自动改金标或放行。",
            ),
        )
        print(
            json.dumps(
                dict(
                    review_file=str(run_dir / "human-reviews.json"),
                    records=len(reviews),
                ),
                ensure_ascii=False,
            )
        )
