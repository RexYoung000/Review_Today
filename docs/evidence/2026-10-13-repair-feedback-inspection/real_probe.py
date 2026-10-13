"""Opt-in repair components: controlled bad draft, real review/repair, no card writes."""
import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="review-today-repair-real-") as tmp:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(tmp) / "isolated.sqlite3")
        os.environ["REVIEW_TODAY_JEV_TEST"] = "0"
        from agent_service.capture import run_capture
        from agent_service.config import COACH_MODEL, PROVIDER
        from agent_service.openai_client import ModelCallError, parse_model
        from agent_service.schemas import ExtractPayload, RiskVerdict, SemanticVerdict

        source = "植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。"
        base = ExtractPayload.model_validate({
            "understood_as": "用户想记住光合作用的过程。", "theme": "光合作用",
            "attribution": "claim", "knowledge": [{
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "learning_goal": "解释光合作用如何利用原料生成有机物并释放氧气。",
                "knowledge_type": "concept", "theme": "光合作用",
                "content_language": "zh", "question_language": "zh", "answer_language": "zh",
                "evidence_excerpt": source, "evidence_locator": "", "title": "光合作用",
                "explanation": "1. 植物利用光能。\n2. 二氧化碳和水转化为有机物。\n3. 这个过程会释放氧气。",
                "scoring_spec": {"learning_goal": "解释光合作用的过程。",
                    "must_cover": ["光能", "二氧化碳和水", "有机物", "氧气"],
                    "acceptable_paraphrases": [], "common_misconceptions": [],
                    "evidence": source, "order_rules": ""},
                "questions": [{"variant_index": 0, "prompt_text": "请解释植物进行光合作用的过程。"}],
            }],
        })
        report = {"kind": "directed_capture_repair_components", "provider": PROVIDER,
                  "model": COACH_MODEL, "card_writes": 0, "source": source,
                  "source_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [Path("agent_service/capture/__init__.py"), Path("agent_service/capture/prompts.py")]},
                  "samples": []}
        for name in ["generic_theme", "nonliteral_evidence"]:
            bad = base.model_copy(deep=True)
            if name == "generic_theme":
                bad.knowledge[0].theme = "技术"
            else:
                bad.knowledge[0].evidence_excerpt = "QA-ONLY：原文不存在的引文"
            sample = {"case": name, "initial_draft": bad.model_dump(), "calls": []}

            def runner(system, user, schema, **kwargs):
                repair = schema is ExtractPayload and "上一稿：" in user
                if schema is ExtractPayload and not repair:
                    return bad.model_copy(deep=True)  # controlled initial defect
                if schema is RiskVerdict:
                    return RiskVerdict(risk=False, reason="合成稳定来源；风险节点受控")
                assert schema in {ExtractPayload, SemanticVerdict}
                call = {"schema": schema.__name__, "repair": repair,
                        "system": system, "user": user, "usage": [], "requests": 0}
                sample["calls"].append(call)
                started = time.monotonic()

                def requested():
                    call["requests"] += 1

                try:
                    output = parse_model(system, user, schema, model=COACH_MODEL,
                        reasoning_effort="none", timeout=45,
                        max_output_tokens=3600 if repair else 1000,
                        on_usage=call["usage"].append, on_request=requested)
                    call["output"] = output.model_dump()
                    return output
                except ModelCallError as error:
                    call.update(error_code=error.code, diagnostic=error.diagnostic)
                    raise
                finally:
                    call["elapsed_ms"] = round((time.monotonic() - started) * 1000)

            with patch("agent_service.capture.fetch_public_url", side_effect=AssertionError("web forbidden")), \
                 patch("agent_service.capture.web_search_text", side_effect=AssertionError("web forbidden")):
                result = run_capture("synthetic-repair-" + name, source, "zh",
                                     confirmed_content=True, model_runner=runner)
            sample["result"] = {k: v for k, v in result.items()
                                if k not in {"model_runner", "search_runner", "quality_runner"}}
            repairs = [call for call in sample["calls"] if call["repair"]]
            cards = result.get("extracted", {}).get("knowledge", [])
            checks = {"committable": result.get("outcome") == "committing",
                      "one_repair": len(repairs) == 1,
                      "rechecked": sum(call["schema"] == "SemanticVerdict" for call in sample["calls"]) == 2,
                      "feedback_present": bool(repairs and "检查不符合项" in repairs[0]["user"]),
                      "source_quotes_literal": bool(cards) and all(
                          item["evidence_excerpt"] in source and item["scoring_spec"]["evidence"] in source for item in cards),
                      "specific_theme": bool(cards) and all(item["theme"] != "技术" for item in cards)}
            sample.update(checks=checks, passed=all(checks.values()))
            report["samples"].append(sample)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"case": name, "passed": sample["passed"], "checks": checks,
                              "real_calls": len(sample["calls"])}, ensure_ascii=False), flush=True)
        if not all(sample["passed"] for sample in report["samples"]):
            raise SystemExit("directed repair sample failed; original outputs preserved")


if __name__ == "__main__":
    main()
