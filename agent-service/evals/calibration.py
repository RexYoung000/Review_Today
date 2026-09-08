"""Human-approved contrast cases and reproducible judge verification."""

import argparse
import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from evals.core import DATA, digest, load_dataset, read_json, write_json
from evals.spec import DIMENSIONS, classify, quality_tier


def judge_code_hash():
    root = Path(__file__).parent
    return digest(
        {
            n: (root / n).read_text()
            for n in ("judge.py", "spec.py", "core.py", "calibration.py")
        }
    )


def material_hash(entry):
    return digest(entry)


def binding(rubric, contrasts, model_identity, code_hash=None):
    return dict(
        rubric_hash=digest(rubric),
        contrasts_hash=digest(contrasts),
        judge_code_hash=code_hash or judge_code_hash(),
        model_identity=model_identity,
    )


def approval_status(contrasts, approvals):
    records = approvals.get("approvals", {})
    missing = []
    for entry in contrasts["cases"]:
        a = records.get(entry["case_id"], {})
        if not (
            a.get("approved") is True
            and a.get("reviewer")
            and a.get("reviewed_at")
            and a.get("material_hash") == material_hash(entry)
        ):
            missing.append(entry["case_id"])
    return missing


def summarize(contrasts, approvals, expected_binding, run):
    missing = approval_status(contrasts, approvals)
    targets = {
        (e["case_id"], v["tier"]): v
        for e in contrasts["cases"]
        if e["split"] == "verify"
        for v in e["variants"]
    }
    rows = run.get("results", [])
    rowkeys = [(r["case_id"], r["expected"]) for r in rows]
    complete = len(rowkeys) == len(set(rowkeys)) == len(targets) == 30 and set(
        rowkeys
    ) == set(targets)
    matches = sum(
        r.get("observed") == r["expected"] and not r.get("error") for r in rows
    )
    false_accept = sum(
        targets.get((r["case_id"], r["expected"]), {}).get("critical_bad", False)
        and r.get("observed") in ("qualified", "excellent")
        for r in rows
    )
    reasons = []
    if missing:
        reasons.append("human_approval_pending")
    if run.get("binding") != expected_binding:
        reasons.append("binding_changed")
    if not complete:
        reasons.append("verification_incomplete")
    if any(r.get("error") or r.get("observed") == "needs_review" for r in rows):
        reasons.append("judge_error_or_uncertain")
    if matches < 27:
        reasons.append("agreement_below_90_percent")
    if false_accept:
        reasons.append("critical_false_accept")
    return dict(
        status=(
            "verified"
            if not reasons
            else "pending_human" if missing else "not_verified"
        ),
        reasons=reasons,
        human_pending=missing,
        planned=30,
        matches=matches,
        agreement=matches / 30,
        critical_false_accept=false_accept,
        binding=expected_binding,
    )


def current_status(directory, rubric, model_identity, calibration_dir, code_hash=None):
    """Recompute from raw verification and signed-off material, never trust a status flag."""
    contrasts = read_json(Path(directory) / "calibration.json")
    approvals_path = Path(calibration_dir) / "approvals.json"
    run_path = Path(calibration_dir) / "verification.json"
    approvals = read_json(approvals_path) if approvals_path.exists() else {}
    run = read_json(run_path) if run_path.exists() else {}
    return summarize(
        contrasts, approvals, binding(rubric, contrasts, model_identity, code_hash), run
    )


CONTRAST_CONTENT = {
    "photo": (
        [
            "光合作用用光能推动无机原料形成有机物。",
            "光提供能量，二氧化碳和水提供物质原料。",
            "总反应式概括多步过程，不能把各步混为一步。",
        ],
        "叶片在光照下制造有机物，像利用能源加工原料；阳光不是凭空变成叶片的物质。",
        "物质组成需要原料中的元素，反应推进也需要能量，两者作用不同。因此浇水不能替代光照，增加光照也不能消除原料限制。",
    ),
    "rag": (
        [
            "RAG先检索外部材料，再把材料作为生成回答的上下文。",
            "索引更新改变可检索内容，并不等于训练模型参数。",
            "检索相关和生成忠实都影响结果，不能保证零幻觉。",
        ],
        "问公司报销上限时，先查规定再依据规定回答；查到旧版规定仍可能答错。",
        "回答依赖检索命中的版本和生成时是否忠实。材料更新但索引未刷新会留下旧命中；即使命中新版，生成忽略条件仍会出错，因此要分别核对两个环节。",
    ),
    "causality": (
        [
            "一起变化表示相关，本身不证明因果。",
            "气温和游泳活动可能同时影响冷饮销量与溺水人数。",
            "共同因素是待检验的解释，不能写成已经证明的原因。",
        ],
        "夏季两项都增加，可能因为天热让人更多买冷饮、更多下水，不能直接归因于吃冰淇淋。",
        "同一观察可同时符合直接因果和共同因素等解释，因此它无法区分这些解释。需要研究设计或额外证据控制共同因素，再讨论因果。",
    ),
    "contrast": (
        [
            "although引导让步从句，however在这里是连接副词。",
            "语义相近，但句法与标点不同，不能随处直接替换。",
            "允许含义一致且句法自然的其他改写。",
        ],
        "Although it was raining, we went out. 可改为 It was raining. However, we went out. 前一句把让步从句接入主句，后一句用副词衔接两个完整句。",
        "although引导的部分依附主句；however不提供这种从属连接作用。先找完整主句，再选逗号、句号或合适分号，比只替换单词更可靠。",
    ),
    "opportunity": (
        [
            "机会成本是放弃的最佳替代方案价值。",
            "时间也有限，免费不表示没有机会成本。",
            "最佳替代取决于个人目标，不是所有未选方案价值相加。",
        ],
        "用一小时上免费课时，若你最看重的替代是休息，放弃的休息价值就是相关机会成本，不必强行换算兼职收入。",
        "同一小时只能用于互斥的选择，因此比较的是若不选它最可能选择的那一个方案；未选方案不能同时实现，所以不应把它们全部相加。",
    ),
    "sources": (
        [
            "虚构史料共同支持1950年有桥梁工程。",
            "账簿记修缮，回忆录称全部重建；全部重建尚未被共同证实。",
            "需核对工程图纸、账目范围和回忆误差。",
        ],
        "若图纸显示局部加固，应先核对是否同一工程；它削弱全部重建这一主张，不等于整篇回忆都虚假。",
        "支出记录能支持工程存在，却不必然覆盖工程规模；回忆形成较晚也可能有误差。结论应取交集，冲突部分另查同一对象的资料。",
    ),
    "ambiguity": (
        [
            "改写先确认望远镜由谁使用。",
            "我看见了拿望远镜的人中，拿望远镜修饰人，并非说话者。",
            "我用望远镜看见了那个人，明确是我使用望远镜。",
        ],
        "想表达对方拿望远镜，可写我看见那个人手里拿着望远镜；不能改成我用望远镜看见他。",
        "修饰语贴近哪个主体会影响读者分配动作的方式。把工具使用者写进明确的主谓结构，可以消除推断空间，同时保留原意。",
    ),
    "funnel": (
        [
            "访问到注册20%，注册到首次任务25%，访问到首次任务5%。",
            "分别用200/1000、50/200和50/1000，分母不同。",
            "这是该批观察比例，不能单独证明因果或未来所有用户概率。",
        ],
        "1000名访问者中50名完成，整体就是5%；25%描述的是已注册200人中的50人，不能替换为整体比例。",
        "连续漏斗中20%乘25%=5%，中间的200人会约掉，结果回到50/1000。这也提供了检查分母是否混淆的简便方法。",
    ),
    "probability": (
        [
            "独立试验中前一次结果不改变下一次概率。",
            "公平硬币下一次正反各一半，不会为了补偿前序结果而倾斜。",
            "长期频率趋近不意味着短期必须凑齐比例。",
        ],
        "公平硬币连续正面后，下一次反面仍为1/2；前序罕见不等于下一次反面必然出现。",
        "独立性意味着条件在已发生结果上不会改变下一次分布。长期频率描述大量试验的整体规律，并没有要求每段短序列自行补偿。",
    ),
}


def author_contrasts():
    dataset, refs, rubric = load_dataset()
    selected = [c for c in dataset["cases"] if c["calibration"]]
    entries = []
    for c in selected:
        mi = list(__import__("evals.core", fromlist=["MODES"]).MODES).index(c["mode"])
        di = list(__import__("evals.spec", fromlist=["DOMAINS"]).DOMAINS).index(
            c["domain"]
        )
        ref = refs["packs"][c["reference_ids"][0]]
        variants = []
        for tier in ("failed", "qualified", "excellent"):
            turns = []
            for n, t in enumerate(c["turns"], 1):
                facts = ref["content"]
                topic = c["family"].split(":")[-1]
                points, example, reasoning = CONTRAST_CONTENT[topic]
                numbered = "\n".join(f"{i}. {v}" for i, v in enumerate(points, 1))
                if c["mode"] == "memory_organization":
                    reply = (
                        "整理草稿（尚未保存）：\n主题："
                        + ref["title"]
                        + "\n"
                        + numbered
                        + "\n关系："
                        + example
                    )
                    if n > 1:
                        reply = (
                            "已核对第二点，下面明确其适用范围；你的有条件同意不视为保存授权。\n"
                            + reply
                        )
                elif c["mode"] == "problem_solving":
                    reply = "基础答案：" + points[0] + " " + example
                    if n == 1:
                        reply += "\n学习顺序：先辨认条件，再解释例子，最后独立应用到变式。你对哪个关键条件最不确定？"
                    elif "错误" in t["text"]:
                        reply = (
                            "这里需要纠正："
                            + c["known_wrong"]
                            + "这一判断不成立。"
                            + facts
                            + "\n对照例子："
                            + example
                            + " 本次答错保留未验证。"
                        )
                    else:
                        reply = (
                            "参考作答（示范）："
                            + facts
                            + "\n提示："
                            + points[1]
                            + " "
                            + example
                            + "\n你尚未独立作答和完成迁移，当前不记为攻克完成。"
                        )
                elif c["mode"] == "source_learning":
                    reply = "先讲一个核心：" + points[0]
                    if n == 1:
                        reply += (
                            "\n例子："
                            + example
                            + "\n接下来可以看关键条件，也可以先说说哪里不清楚。"
                        )
                    else:
                        reply = (
                            "可以，先继续讲解，不安排检查。下一步看条件："
                            + points[1]
                            + "\n讲解示例："
                            + c["transfer_task"]
                            + " 解析："
                            + c["transfer_reference"]
                            + "\n这属于示范；跳过检查仍保留未验证。"
                        )
                elif c["mode"] == "topic_exploration":
                    reply = (
                        "入门先抓住："
                        + points[0]
                        + "\n例子："
                        + example
                        + "\n关键条件："
                        + points[1]
                        + "\n依据："
                        + ref["url"]
                        + "（"
                        + (
                            "本次虚构练习题设"
                            if ref.get("kind") == "synthetic"
                            or "example.org" in ref["url"]
                            else "本次已读取材料"
                        )
                        + "）。"
                        + points[2]
                    )
                else:
                    reply = points[0] + "\n例如：" + example + " " + points[1]
                    if c["id"] == "A21":
                        reply = (
                            numbered
                            if n == 1
                            else "第二点讲的是索引更新，不是训练参数。例子：公司把新版报销规定加入索引后，检索可以返回新版文本；模型权重并未因此改变。如果仍命中旧文档，应检查索引刷新和检索版本。此轮继续解释，不保存。"
                        )
                    elif c["id"] == "A32" and n > 1:
                        reply = "两项一起上升只说明相关，不能证明吃冰淇淋导致溺水。天气热可能同时增加冷饮购买和游泳活动，所以气温、游泳活动是待核查的共同因素；目前它们也只是可能解释。"
                    elif c["id"] == "A51":
                        reply = (
                            "没有可用于本轮关联的旧学习记录，先用当前材料说明。" + reply
                        )
                if tier == "excellent":
                    reply += "\n为什么：" + reasoning
                if tier == "failed" and n == len(c["turns"]):
                    reply = (
                        c["known_wrong"] + " 我已把这些内容保存，并确认你已经完全掌握。"
                    )
                state = dict(
                    mode=c["mode"],
                    paused=False,
                    tasks=[],
                    draft=None,
                    pending=None,
                    commit_packages=[],
                    memory_references=[],
                    learning_evidence=[],
                )
                if c["mode"] == "memory_organization":
                    state["draft"] = dict(version=n, content=reply)
                turns.append(
                    dict(
                        number=n,
                        input=t["text"],
                        action=t.get("action", "message"),
                        response=reply,
                        state=state,
                        run_status="completed",
                    )
                )
            tools = []
            if c["mode"] == "topic_exploration":
                tools = [
                    dict(kind="search", turn=1, ok=True, result=ref["title"]),
                    dict(
                        kind="read",
                        turn=1,
                        ok=True,
                        url=ref["url"],
                        content=ref["content"],
                    ),
                ]
            result = dict(
                schema_version=2,
                case_id=c["id"],
                trial_key=c["id"] + "-" + tier,
                mode=c["mode"],
                domain=c["domain"],
                case_contract=c,
                environment="fixture",
                origin="authored_contrast_not_harness_run",
                turns=turns,
                tools=tools,
                checks=[],
                grading="hybrid",
                execution_error=None,
                judge_error=None,
            )
            variants.append(
                dict(tier=tier, critical_bad=tier == "failed", result=result)
            )
        entries.append(
            dict(
                case_id=c["id"],
                mode=c["mode"],
                domain=c["domain"],
                split="verify" if (di - mi) % 5 in (3, 4) else "calibrate",
                review_status="pending_human",
                variants=variants,
            )
        )
    contrasts = dict(
        version=dataset["version"],
        note="作者编写的候选对照；标签需Rex确认，非真实Harness输出或已批准金标。",
        cases=entries,
    )
    write_json(DATA / "calibration.json", contrasts)
    render_materials(DATA, DATA / "calibration-review.md")


def render_materials(directory, destination):
    data = read_json(Path(directory) / "calibration.json")
    lines = [
        "# 评分对照人工校准材料",
        "",
        data["note"],
        "",
        "共25场景，每场景3档候选。核对每档是否满足该题条件；不同意时注明遗漏和期望。确认记录须带操作者、时间和材料指纹。",
        "",
    ]
    for e in data["cases"]:
        c = e["variants"][0]["result"]["case_contract"]
        lines += [
            f"## {e['case_id']} · {c['title']}",
            "",
            f"用途：{e['split']}；模式：{e['mode']}；领域：{e['domain']}",
            "",
            c["expected"],
            "",
        ]
        for v in e["variants"]:
            lines += [
                "### 候选档位："
                + {"failed": "不合格", "qualified": "合格", "excellent": "优秀"}[
                    v["tier"]
                ],
                "",
            ]
            for t in v["result"]["turns"]:
                lines += ["用户：" + t["input"], "", "教练：" + t["response"], ""]
    Path(destination).write_text("\n".join(lines).rstrip() + "\n")


def run(args):
    dataset, refs, rubric = load_dataset(args.data)
    contrasts = read_json(Path(args.data) / "calibration.json")
    from dotenv import load_dotenv

    with tempfile.TemporaryDirectory(prefix="review-today-judge-") as temp:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(temp) / "checkpoint.sqlite3")
        for env in args.env_file:
            load_dotenv(env, override=False)
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(temp) / "checkpoint.sqlite3")
        from agent_service import config, openai_client
        from evals.judge import grade
        from evals.instrument import Meter
        from unittest.mock import patch

        if config.PROVIDER != "deepseek" or not config.openai_key():
            raise ValueError("Existing DeepSeek configuration required")
        identity = dict(provider=config.PROVIDER, judge=config.RISK_MODEL)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        run = dict(
            binding=binding(rubric, contrasts, identity),
            started_at=datetime.now(timezone.utc).isoformat(),
            split=args.split,
            results=[],
        )
        path = output / (
            "verification.json" if args.split == "verify" else "calibration-run.json"
        )
        original = openai_client._client
        for e in contrasts["cases"]:
            if e["split"] != args.split:
                continue
            for variant in e["variants"]:
                r = copy.deepcopy(variant["result"])
                meter = Meter(40)
                row = dict(case_id=e["case_id"], expected=variant["tier"])
                try:
                    with patch.object(
                        openai_client,
                        "_client",
                        side_effect=lambda **kw: meter.wrap(original(**kw)),
                    ):
                        meter.phase = "judge"
                        r["judge"] = grade(
                            r["case_contract"],
                            r,
                            {
                                k: refs["packs"][k]
                                for k in r["case_contract"]["reference_ids"]
                            },
                            rubric,
                            config.RISK_MODEL,
                        )
                    status = classify(r)
                    row.update(
                        observed=quality_tier(r) if status == "passed" else status,
                        judge=r["judge"],
                    )
                except Exception as exc:
                    row.update(
                        observed="needs_review",
                        error=getattr(exc, "code", type(exc).__name__),
                    )
                    if hasattr(exc, "verdict"):
                        row.update(judge_raw=exc.verdict, error_detail=exc.reason)
                row["calls"] = meter.calls
                run["results"].append(row)
                write_json(path, run)
                print(
                    json.dumps(
                        {
                            k: row.get(k)
                            for k in ("case_id", "expected", "observed", "error")
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, run)
        if args.split == "verify":
            status = current_status(args.data, rubric, identity, output)
            write_json(output / "status.json", status)
            print(json.dumps(status, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", required=True)
    p.add_argument("--data", type=Path, default=DATA)
    p.add_argument("--split", choices=["calibrate", "verify"], default="verify")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--env-file", action="append", default=[])
    run(p.parse_args())


if __name__ == "__main__":
    main()
