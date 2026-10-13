"""Read-only synthetic capture inspection; never calls a provider or writes cards."""
import argparse
import json
from unittest.mock import patch

from agent_service.capture import run_capture
from agent_service.schemas import ExtractPayload, RiskVerdict, SemanticVerdict

SOURCE = "植物利用光能，把二氧化碳和水转化为有机物，并释放氧气。"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--expect-feedback", action="store_true", help="Use only after REPAIR-01 implementation.")
args = parser.parse_args()
GOOD = ExtractPayload.model_validate({
    "understood_as": "用户想记住光合作用的过程。", "theme": "光合作用",
    "attribution": "claim", "knowledge": [{
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "learning_goal": "解释光合作用如何利用原料生成有机物并释放氧气。",
        "knowledge_type": "concept", "theme": "光合作用",
        "content_language": "zh", "question_language": "zh", "answer_language": "zh",
        "evidence_excerpt": SOURCE, "evidence_locator": "", "title": "光合作用",
        "explanation": "1. 植物利用光能。\n2. 二氧化碳和水转化为有机物。\n3. 这个过程会释放氧气。",
        "scoring_spec": {"learning_goal": "解释光合作用的过程。",
            "must_cover": ["光能", "二氧化碳和水", "有机物", "氧气"],
            "acceptable_paraphrases": [], "common_misconceptions": [],
            "evidence": SOURCE, "order_rules": ""},
        "questions": [{"variant_index": 0, "prompt_text": "请解释植物进行光合作用的过程。"}],
    }],
})


def inspect(name, *, bad=False, callback_present=False):
    value = GOOD.model_copy(deep=True)
    if bad:
        value.knowledge[0].theme = "技术"
    calls = []

    def model(system, user, schema, **kwargs):
        calls.append({"schema": schema.__name__, "repair": "上一稿：" in user,
                      "system": system, "user": user})
        if schema is ExtractPayload:
            return value.model_copy(deep=True)
        if schema is SemanticVerdict:
            # A permissive synthetic reviewer leaves the deterministic theme
            # check responsible for rejecting the bad card on both passes.
            return SemanticVerdict(ok=True)
        if schema is RiskVerdict:
            return RiskVerdict(risk=False, reason="合成稳定知识")
        raise AssertionError(f"unexpected schema: {schema.__name__}")

    callback = (lambda *args, **kwargs: None) if callback_present else None
    result = run_capture(name, SOURCE, "zh", confirmed_content=True,
                         model_runner=model, quality_runner=callback)
    repairs = [call for call in calls if call["repair"]]
    issues = result.get("semantic_issues", [])
    issue_received = [issue in repairs[0]["user"] for issue in issues] if repairs else []
    assert result["outcome"] == ("needs_attention" if bad else "committing")
    assert len(repairs) == int(bad)
    if bad:
        assert issues and all(issue_received) == (callback_present or args.expect_feedback)
        assert not any(call["schema"] == "RiskVerdict" for call in calls)
    return {"case": name, "callback_present": callback_present, "outcome": result["outcome"],
            "error_code": result.get("error_code"), "repair_used": result["repair_used"],
            "semantic_ok": result["semantic_ok"], "semantic_issues": issues,
            "exact_issues_in_repair_user_prompt": issue_received,
            "semantic_check_count": sum(call["schema"] == "SemanticVerdict" for call in calls),
            "repair_count": len(repairs), "calls": calls}


with patch("agent_service.capture.parse_model", side_effect=AssertionError("network forbidden")), \
     patch("agent_service.capture.fetch_public_url", side_effect=AssertionError("network forbidden")), \
     patch("agent_service.capture.web_search_text", side_effect=AssertionError("network forbidden")):
    results = [inspect("valid_default"), inspect("bad_theme_default", bad=True),
               inspect("bad_theme_callback_falls_back", bad=True, callback_present=True)]

print(json.dumps({"synthetic": True, "real_model_calls": 0, "card_writes": 0,
                  "results": results}, ensure_ascii=False, indent=2))
