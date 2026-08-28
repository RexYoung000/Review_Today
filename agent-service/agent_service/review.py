import json

from agent_service.capture.prompts import GRADE_SYSTEM
from agent_service.openai_client import parse_model
from agent_service.schemas import GradeRequest, GradeResult


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def _grade_input(body: GradeRequest) -> str:
    spec = body.scoring_spec
    payload = {
        "primary_language": body.primary_language,
        "hint_used": body.hint_used,
        "prompt_text": body.prompt_text,
        "learning_goal": spec.learning_goal,
        "must_cover": spec.must_cover,
        "acceptable_paraphrases": spec.acceptable_paraphrases,
        "common_misconceptions": spec.common_misconceptions,
        "evidence": spec.evidence,
        "order_rules": spec.order_rules,
        # Keep the user's answer verbatim. JSON is only the request envelope, not a
        # separate extraction or normalization step.
        "answer_text": body.answer_text,
    }
    return "请直接评估以下 JSON 中的原始回答，不要改写或预提取用户回答：\n" + json.dumps(
        payload,
        ensure_ascii=False,
    )


def grade_answer(body: GradeRequest) -> GradeResult:
    parsed = parse_model(GRADE_SYSTEM, _grade_input(body), GradeResult)
    result = GradeResult.model_validate(parsed.model_dump())
    result.attempt_id = body.attempt_id
    result.hint_used = body.hint_used
    if result.agent_grade == "good" and body.hint_used:
        result.agent_grade = "hard"
    if body.primary_language.lower().startswith("zh") and not _has_cjk(result.brief_feedback):
        raise ValueError("brief_feedback must use the user's primary language")
    return result
