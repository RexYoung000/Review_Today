"""Opt-in old/new generation samples; no routing, web, App or save acceptance.

Run with a saved previous system prompt and an explicit JSON evidence output:
  .venv/bin/python -m tests.coach_rule_loading_real_smoke \
    --baseline-system /tmp/previous-coach-system.txt --output /tmp/rule-samples.json
"""
import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path


MATERIAL = """RAG（检索增强生成）在回答前从外部知识库检索资料，把相关资料和问题交给模型生成回答。
它可补充模型训练时没有的资料，例如昨天更新的内部说明；它不保证资料相关、最新或回答正确。
本次只学外部资料为什么有用，检索实现与评估留到后续步骤。"""
TEACHING_BINDING_RULE = (
    "\n本轮使用可验证的教学输出：只要给出检查题就必须同时提供 check_binding，不能为 null。"
    "题目完整条件只放 check_question，不在 message 末尾另写想一想或检查一下。"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-system", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = args.baseline_system.read_text()
    # No module opens a daily database; isolate the configuration before imports.
    with tempfile.TemporaryDirectory(prefix="review-today-rule-samples-") as tmp:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(tmp) / "isolated.sqlite3")
        from agent_service.config import COACH_MODEL, PROVIDER
        from agent_service.conversation_prompts import coach_system
        from agent_service.context_budget import estimate
        from agent_service.openai_client import ModelCallError, parse_model
        from agent_service.schemas import ConversationOutput, TeachingConversationOutput

        cases = [
            ("answer", "用一句话解释 RAG 是什么。", ConversationOutput),
            ("teaching", "教我 RAG，面向初学者。先用一两句定义，给紧凑地图，然后只讲为什么需要外部资料这一步。"
             "出一道仅检查本步所教概念的题，不在正文重复题目。", TeachingConversationOutput),
        ]
        report = dict(kind="generation_component", model=COACH_MODEL, provider=PROVIDER,
                      reasoning_effort="none", baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
                      rule_sizes={scene: dict(chars=len(coach_system(scene)),
                                             conservative_token_estimate=estimate(coach_system(scene)))
                                  for scene in ("answer", "teaching", "organize", "clarify")},
                      baseline_chars=len(baseline), baseline_token_estimate=estimate(baseline), samples=[])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        failures = []
        for scene, instruction, schema in cases:
            payload = dict(instruction=instruction, context=dict(current_inputs=[instruction], recent_messages=[]),
                           sources=[dict(type="user_material", content=MATERIAL)], learning_step=None,
                           capture_candidates=[], evidence=dict(state="unverified"), verification_notice="")
            for version in ("old", "new"):
                system = baseline if version == "old" else coach_system(scene)
                if scene == "teaching":
                    system += TEACHING_BINDING_RULE
                start = time.monotonic()
                partial_times, usages, requests = [], [], []
                item = dict(scene=scene, version=version, input=payload, system_chars=len(system),
                            system_sha256=hashlib.sha256(system.encode()).hexdigest())
                try:
                    result = parse_model(system, json.dumps(payload, ensure_ascii=False), schema,
                        model=COACH_MODEL, reasoning_effort="none", timeout=45, max_output_tokens=2400,
                        on_partial=lambda value: partial_times.append(time.monotonic()),
                        on_usage=usages.append, on_request=lambda: requests.append(1))
                    item["output"] = result.model_dump()
                    result.validate_request(payload)
                    if scene == "answer":
                        checks = dict(no_plan=result.learning_plan is None,
                                      no_check=not result.check_question and result.check_binding is None,
                                      one_sentence=len(re.findall(r"[。！？!?]", result.message.strip())) == 1)
                    else:
                        checks = dict(has_plan=result.learning_plan is not None,
                                      has_grounded_check=bool(result.check_question and result.check_binding),
                                      first_step_binding=bool(result.learning_plan and result.check_binding and
                                          result.check_binding.step_title == result.learning_plan.steps[0]))
                    item.update(output=result.model_dump(), checks=checks, passed=all(checks.values()))
                    if not item["passed"]:
                        failures.append(f"{scene}/{version}: sample checks")
                except ModelCallError as error:
                    item.update(passed=False, error_code=error.code, diagnostic=error.diagnostic)
                    failures.append(f"{scene}/{version}: {error.code}")
                item.update(elapsed_ms=round((time.monotonic() - start) * 1000),
                            first_partial_ms=round((partial_times[0] - start) * 1000) if partial_times else None,
                            partials=len(partial_times), transport_requests=len(requests), usage=usages)
                report["samples"].append(item)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({k: item[k] for k in ("scene", "version", "passed", "elapsed_ms", "transport_requests")}), flush=True)
        if failures:
            raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
